import logging
import re
import struct
from uuid import uuid4
from collections import defaultdict, namedtuple
from Crypto.Cipher import AES
from threading import Lock
from pyrate_limiter import Limiter, RequestRate
from streamlink.exceptions import StreamError, TooManySegmentsError, TooManySegmentUnableHandle
from streamlink.stream import hls_playlist
from streamlink.stream.ffmpegmux import FFMPEGMuxer, MuxedStream
from streamlink.stream.http import HTTPStream
from streamlink.stream.segmented import SegmentedStreamReader, SegmentedStreamWriter, SegmentedStreamWorker
log = logging.getLogger(__name__)
Sequence = namedtuple('Sequence', 'num segment')

def num_to_iv(n):
    return struct.pack('>8xq', n)

def pkcs7_decode(paddedData, keySize=16):
    '''
    Remove the PKCS#7 padding
    '''
    val = ord(paddedData[-1:])
    if val > keySize:
        raise StreamError('Input is not padded or padding is corrupt, got padding size of {0}'.format(val))
    return paddedData[:-val]

class HLSStreamWriter(SegmentedStreamWriter):
    validate_magic_ts = re.compile(b'G.{187}G.{187}G', re.DOTALL)

    def __init__(self, reader, *args, **kwargs):
        options = reader.stream.session.options
        kwargs['retries'] = options.get('hls-segment-attempts')
        kwargs['threads'] = options.get('hls-segment-threads')
        kwargs['timeout'] = options.get('hls-segment-timeout')
        kwargs['ignore_names'] = options.get('hls-segment-ignore-names')
        SegmentedStreamWriter.__init__(self, reader, *args, **kwargs)
        rate_request = options.get('hls-segment-rate-request')
        if rate_request:
            rate_delay = options.get('hls-segment-rate-delay') or 1
            log.debug('hls-segment-rate-delay {}', rate_delay)
            log.debug('hls-segment-rate-request {}', rate_request)
            self.limiter = Limiter(RequestRate(rate_request, rate_delay))
            self._default_bucket = uuid4().hex
        else:
            self.limiter = None
            self._default_bucket = None
        self.bytes_recv = 0
        self.bytes_max = 0
        self.bytes_remain = 0
        self.byterange_offsets = defaultdict(int)
        self.key_data = None
        self.key_uri = None
        self.key_uri_override = options.get('hls-segment-key-uri')
        self.num_error = 0
        self.max_num_error = 5
        self.error = None
        self._lock_error = Lock()
        self._buffer_write_size = 0
        if self.ignore_names:
            self.ignore_names = list(set(self.ignore_names))
            self.ignore_names = '|'.join(list(map(re.escape, self.ignore_names)))
            self.ignore_names_re = re.compile('(?:{blacklist})\\.ts'.format(blacklist=self.ignore_names), re.IGNORECASE)

    def create_decryptor(self, key, sequence):
        if key.method != 'AES-128':
            raise StreamError('Unable to decrypt cipher %s' % key.method)
        if not self.key_uri_override and not key.uri:
            raise StreamError('Missing URI to decryption key')
        key_uri = self.key_uri_override if self.key_uri_override else key.uri
        if self.key_uri != key_uri:
            res = self.session.http.get(key_uri, exception=StreamError, retries=self.retries, **self.reader.request_params)
            res.encoding = 'binary/octet-stream'
            self.key_data = res.content
            self.key_uri = key_uri
        iv = key.iv or num_to_iv(sequence)
        iv = b'\x00'*(16 - len(iv)) + iv
        return AES.new(self.key_data, AES.MODE_CBC, iv)

    def create_request_params(self, sequence):
        request_params = dict(self.reader.request_params)
        headers = request_params.pop('headers', {})
        if sequence.segment.byterange:
            bytes_start = self.byterange_offsets[sequence.segment.uri]
            if sequence.segment.byterange.offset is not None:
                bytes_start = sequence.segment.byterange.offset
            bytes_len = max(sequence.segment.byterange.range - 1, 0)
            bytes_end = bytes_start + bytes_len
            headers['Range'] = 'bytes={0}-{1}'.format(bytes_start, bytes_end)
            self.byterange_offsets[sequence.segment.uri] = bytes_end + 1
        request_params['headers'] = headers
        if not sequence.segment.key:
            request_params['stream'] = True
        return request_params

    def _fetch(self, sequence, retries=None):
        if self.closed or not retries:
            return
        try:
            request_params = self.create_request_params(sequence)
            if self.ignore_names and self.ignore_names_re.search(sequence.segment.uri):
                log.debug('Skipping segment {}', sequence.num)
                return
            return self.session.http.get(sequence.segment.uri, timeout=self.timeout, exception=StreamError, retries=self.retries, **request_params)
        except StreamError as err:
            log.error('Failed to open segment {0}: {1}', sequence.num, err)
            with self._lock_error:
                self.num_error += 1
                if self.num_error >= self.max_num_error:
                    self.error = TooManySegmentsError()
                    self.reader.worker.close()
                    self.close()

    def fetch(self, sequence, retries=None):
        if self.limiter:
            with self.limiter.ratelimit(self._default_bucket, delay=True):
                return self._fetch(sequence, retries)
        else:
            return self._fetch(sequence, retries)

    def validateAndTrim(self, sequence, chunk):
        m = self.validate_magic_ts.search(chunk)
        if m:
            return chunk[m.start():]
        raise StreamError('Segments is not ts file %s' % sequence.segment.uri)

    def _write_buffer(self, data):
        self._buffer_write_size += len(data)
        self.reader.buffer.write(data)

    def get_content_length(self, http_response):
        content_length = 0
        if http_response.status_code == 200:
            content_length = int(http_response.headers.get('Content-Length', 0))
        elif http_response.status_code == 206:
            content_length = int(http_response.headers.get('Content-Length', 0))
            if not content_length:
                try:
                    range_info = http_response.headers.get('Content-Range').split(' ')[1]
                    start_end = range_info.split('/')[0]
                    (start, end) = start_end.split('-')
                    content_length = int(end) - int(start)
                except:
                    pass
        return content_length

    def update_total_bytes(self, length, sequence_num):
        if length > self.bytes_max:
            self.bytes_max = length
        self.bytes_recv += length
        self.reader.stream.total_bytes = self.bytes_recv + self.bytes_max*(self.reader.worker.last_sequence_num - sequence_num)

    def _write(self, sequence, res, chunk_size=32768):
        if sequence.segment.key and sequence.segment.key.method != 'NONE':
            try:
                decryptor = self.create_decryptor(sequence.segment.key, sequence.num)
            except StreamError as err:
                log.error('Failed to create decryptor: {0}', err)
                self.close()
                return
            data = res.content
            garbage_len = len(data) % 16
            if garbage_len:
                log.debug('Cutting off {0} bytes of garbage before decrypting', garbage_len)
                decrypted_chunk = decryptor.decrypt(data[:-garbage_len])
            else:
                decrypted_chunk = decryptor.decrypt(data)
            chunk = pkcs7_decode(decrypted_chunk)
            chunk = self.validateAndTrim(sequence, chunk)
            self._write_buffer(chunk)
        else:
            for chunk in res.iter_content(chunk_size):
                self._write_buffer(chunk)
        log.debug('Download of segment {0} complete', sequence.num)

    def write(self, sequence, res, chunk_size=32768):
        try:
            self._buffer_write_size = 0
            self._write(sequence, res, chunk_size)
            if self._buffer_write_size:
                self.update_total_bytes(self._buffer_write_size, sequence.num)
        except Exception as err:
            log.error('write data from url %s error %s' % (sequence.segment.uri, err))
            with self._lock_error:
                self.num_error += 1
                if self.num_error >= self.max_num_error:
                    self.error = TooManySegmentUnableHandle()
                    self.reader.worker.close()
                    self.close()
        finally:
            res.close()

class HLSStreamWorker(SegmentedStreamWorker):

    def __init__(self, *args, **kwargs):
        SegmentedStreamWorker.__init__(self, *args, **kwargs)
        self.stream = self.reader.stream
        self.playlist_changed = False
        self.playlist_end = None
        self.playlist_sequence = -1
        self.playlist_sequences = []
        self.playlist_reload_time = 15
        self.total_sequences = 0
        self.last_sequence_num = 0
        self.live_edge = self.session.options.get('hls-live-edge')
        self.playlist_reload_retries = self.session.options.get('hls-playlist-reload-attempts')
        self.duration_offset_start = int(self.stream.start_offset + (self.session.options.get('hls-start-offset') or 0))
        self.duration_limit = self.stream.duration or (int(self.session.options.get('hls-duration')) if self.session.options.get('hls-duration') else None)
        self.hls_live_restart = self.stream.force_restart or self.session.options.get('hls-live-restart')
        self.reload_playlist()
        if self.playlist_end is None:
            if self.duration_offset_start > 0:
                log.debug('Time offsets negative for live streams, skipping back {0} seconds', self.duration_offset_start)
            self.duration_offset_start = -self.duration_offset_start
        if self.duration_offset_start != 0:
            self.playlist_sequence = self.duration_to_sequence(self.duration_offset_start, self.playlist_sequences)
        if self.playlist_sequences:
            log.debug('First Sequence: {0}; Last Sequence: {1}', self.playlist_sequences[0].num, self.playlist_sequences[-1].num)
            log.debug('Start offset: {0}; Duration: {1}; Start Sequence: {2}; End Sequence: {3}', self.duration_offset_start, self.duration_limit, self.playlist_sequence, self.playlist_end)

    def reload_playlist(self):
        if self.closed:
            return
        self.reader.buffer.wait_free()
        log.debug('Reloading playlist')
        res = self.session.http.get(self.stream.url, exception=StreamError, retries=self.playlist_reload_retries, **self.reader.request_params)
        try:
            playlist = hls_playlist.load(res.text, res.url)
        except ValueError as err:
            raise StreamError(err)
        if playlist.is_master:
            raise StreamError("Attempted to play a variant playlist, use 'hls://{0}' instead".format(self.stream.url))
        if playlist.iframes_only:
            raise StreamError('Streams containing I-frames only is not playable')
        media_sequence = playlist.media_sequence or 0
        sequences = [Sequence(media_sequence + i, s) for (i, s) in enumerate(playlist.segments)]
        if sequences:
            self.process_sequences(playlist, sequences)

    def process_sequences(self, playlist, sequences):
        (first_sequence, last_sequence) = (sequences[0], sequences[-1])
        self.last_sequence_num = last_sequence.num
        if first_sequence.segment.key and first_sequence.segment.key.method != 'NONE':
            log.debug('Segments in this playlist are encrypted')
        self.playlist_changed = [s.num for s in self.playlist_sequences] != [s.num for s in sequences]
        self.playlist_reload_time = playlist.target_duration or last_sequence.segment.duration
        self.playlist_sequences = sequences
        if not self.playlist_changed:
            self.playlist_reload_time = max(self.playlist_reload_time/2, 1)
        if playlist.is_endlist:
            self.playlist_end = last_sequence.num
        if self.playlist_sequence < 0:
            if self.playlist_end is None and not self.hls_live_restart:
                edge_index = -min(len(sequences), max(int(self.live_edge), 1))
                edge_sequence = sequences[edge_index]
                self.playlist_sequence = edge_sequence.num
            else:
                self.playlist_sequence = first_sequence.num

    def valid_sequence(self, sequence):
        return sequence.num >= self.playlist_sequence

    def duration_to_sequence(self, duration, sequences):
        d = 0
        default = -1
        sequences_order = sequences if duration >= 0 else reversed(sequences)
        for sequence in sequences_order:
            if d >= abs(duration):
                return sequence.num
            d += sequence.segment.duration
            default = sequence.num
        return default

    def iter_segments(self):
        total_duration = 0
        while not self.closed:
            for sequence in filter(self.valid_sequence, self.playlist_sequences):
                log.debug('Adding segment {0} to queue', sequence.num)
                yield sequence
                total_duration += sequence.segment.duration
                if self.duration_limit and total_duration >= self.duration_limit:
                    log.info('Stopping stream early after {}', self.duration_limit)
                    return
                stream_end = self.playlist_end and sequence.num >= self.playlist_end
                if self.closed or stream_end:
                    return
                self.playlist_sequence = sequence.num + 1
            if self.wait(self.playlist_reload_time):
                try:
                    self.reload_playlist()
                except StreamError as err:
                    log.warning('Failed to reload playlist: {0}', err)

class HLSStreamReader(SegmentedStreamReader):
    __worker__ = HLSStreamWorker
    __writer__ = HLSStreamWriter

    def __init__(self, stream, *args, **kwargs):
        SegmentedStreamReader.__init__(self, stream, *args, **kwargs)
        self.request_params = dict(stream.args)
        self.timeout = stream.session.options.get('hls-timeout')
        self.request_params.pop('exception', None)
        self.request_params.pop('stream', None)
        self.request_params.pop('timeout', None)
        self.request_params.pop('url', None)

    def read(self, size):
        data = SegmentedStreamReader.read(self, size)
        if not data and self.writer.error:
            raise IOError('Input data is error: %s' % self.writer.error)
        return data

class MuxedHLSStream(MuxedStream):
    __shortname__ = 'hls-multi'

    def __init__(self, hls_stream, session, video, audio, force_restart=False, ffmpeg_options=None, **args):
        tracks = [video]
        maps = ['0:v?', '0:a?']
        if audio:
            if isinstance(audio, list):
                tracks.extend(audio)
            else:
                tracks.append(audio)
        for i in range(1, len(tracks)):
            maps.append('{0}:a'.format(i))
        substreams = map(lambda url: hls_stream(session, url, force_restart=force_restart, **args), tracks)
        ffmpeg_options = ffmpeg_options or {}
        super().__init__(session, *substreams, format='mpegts', maps=maps, **ffmpeg_options)

class HLSStream(HTTPStream):
    __doc__ = """Implementation of the Apple HTTP Live Streaming protocol

    *Attributes:*

    - :attr:`url` The URL to the HLS playlist.
    - :attr:`args` A :class:`dict` containing keyword arguments passed
      to :meth:`requests.request`, such as headers and cookies.

    """
    __shortname__ = 'hls'
    stream_reader = HLSStreamReader
    muxed_hls = MuxedHLSStream

    def __init__(self, session_, url, force_restart=False, start_offset=0, duration=None, **args):
        HTTPStream.__init__(self, session_, url, **args)
        self.toMp4 = True
        self.force_restart = force_restart
        self.start_offset = start_offset
        self.duration = duration

    def __repr__(self):
        return '<HLSStream({0!r})>'.format(self.url)

    def __json__(self):
        json = HTTPStream.__json__(self)
        del json['method']
        del json['body']
        return json

    def setToMp4(self, ok):
        self.toMp4 = ok
        return self

    def open(self):
        reader = self.stream_reader(self)
        reader.open()
        return reader

    @classmethod
    def parse_variant_playlist(cls, session_, url, name_key='name', name_prefix='', check_streams=False, force_restart=False, name_fmt=None, start_offset=0, duration=None, **request_params):
        '''Attempts to parse a variant playlist and return its streams.

        :param url: The URL of the variant playlist.
        :param name_key: Prefer to use this key as stream name, valid keys are:
                         name, pixels, bitrate.
        :param name_prefix: Add this prefix to the stream names.
        :param check_streams: Only allow streams that are accessible.
        :param force_restart: Start at the first segment even for a live stream
        :param name_fmt: A format string for the name, allowed format keys are
                         name, pixels, bitrate.
        '''
        locale = session_.localization
        name_key = request_params.pop('namekey', name_key)
        name_prefix = request_params.pop('nameprefix', name_prefix)
        audio_select = session_.options.get('hls-audio-select') or []
        res = session_.http.get(url, exception=IOError, **request_params)
        try:
            parser = hls_playlist.load(res.text, base_uri=res.url)
        except ValueError as err:
            raise IOError('Failed to parse playlist: {0}'.format(err))
        streams = {}
        if not parser.is_master:
            streams['720p'] = cls(session_, url, **request_params)
            return streams
        for playlist in filter(lambda p: not p.is_iframe, parser.playlists):
            names = dict(name=None, pixels=None, bitrate=None)
            audio_streams = []
            fallback_audio = []
            default_audio = []
            preferred_audio = []
            for media in playlist.media:
                if media.type == 'VIDEO' and media.name:
                    names['name'] = media.name
                elif media.type == 'AUDIO':
                    audio_streams.append(media)
            for media in audio_streams:
                if not media.uri:
                    continue
                if not fallback_audio:
                    if media.default:
                        fallback_audio = [media]
                if not default_audio:
                    if media.autoselect and locale.equivalent(language=media.language):
                        default_audio = [media]
                if not ('*' in audio_select or (media.language in audio_select or media.name in audio_select) or preferred_audio) or media.default and locale.explicit and locale.equivalent(language=media.language):
                    preferred_audio.append(media)
            fallback_audio = fallback_audio or len(audio_streams) and (audio_streams[0].uri and [audio_streams[0]])
            if playlist.stream_info.resolution:
                (width, height) = playlist.stream_info.resolution
                names['pixels'] = '{0}p'.format(height)
            if playlist.stream_info.bandwidth:
                bw = playlist.stream_info.bandwidth
                if bw >= 1000:
                    names['bitrate'] = '{0}k'.format(int(bw/1000.0))
                else:
                    names['bitrate'] = '{0}k'.format(bw/1000.0)
            if name_fmt:
                stream_name = name_fmt.format(**names)
            else:
                stream_name = names.get(name_key) or (names.get('name') or (names.get('pixels') or names.get('bitrate')))
            if not stream_name:
                pass
            else:
                if stream_name in streams:
                    stream_name = '{0}_alt'.format(stream_name)
                    num_alts = len(list(filter(lambda n: n.startswith(stream_name), streams.keys())))
                    if num_alts >= 2:
                        pass
                    elif num_alts > 0:
                        stream_name = '{0}{1}'.format(stream_name, num_alts + 1)
                if check_streams:
                    try:
                        session_.http.get(playlist.uri, **request_params)
                    except KeyboardInterrupt:
                        raise
                    except Exception:
                        continue
                external_audio = preferred_audio or (default_audio or fallback_audio)
                if external_audio and FFMPEGMuxer.is_usable(session_):
                    external_audio_msg = ', '.join(['(language={0}, name={1})'.format(x.language, x.name or 'N/A') for x in external_audio])
                    log.debug('Using external audio tracks for stream {0} {1}', name_prefix + stream_name, external_audio_msg)
                    stream = cls.muxed_hls(cls, session_, video=playlist.uri, audio=[x.uri for x in external_audio if x.uri], force_restart=force_restart, start_offset=start_offset, duration=duration, **request_params)
                else:
                    stream = cls(session_, playlist.uri, force_restart=force_restart, start_offset=start_offset, duration=duration, **request_params)
                streams[name_prefix + stream_name] = stream
        return streams

