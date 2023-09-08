import itertools
import logging
import datetime
import os.path
from threading import Lock
from collections import namedtuple
import requests
from uuid import uuid4
from pyrate_limiter import Limiter, RequestRate
from streamlink import StreamError
from streamlink.compat import urlparse, urlunparse
from streamlink.stream.http import valid_args, normalize_key
from streamlink.stream.stream import Stream
from streamlink.stream.dash_manifest import MPD, sleeper, sleep_until, utc, freeze_timeline
from streamlink.stream.ffmpegmux import FFMPEGMuxer
from streamlink.stream.segmented import SegmentedStreamReader, SegmentedStreamWorker, SegmentedStreamWriter
from streamlink.utils.l10n import Language
from streamlink.exceptions import TooManySegmentsError, TooManySegmentUnableHandle
log = logging.getLogger(__name__)
Sequence = namedtuple('Sequence', 'num segment')

class DASHStreamWriter(SegmentedStreamWriter):

    def __init__(self, reader, *args, **kwargs):
        options = reader.stream.session.options
        kwargs['retries'] = options.get('dash-segment-attempts')
        kwargs['threads'] = options.get('dash-segment-threads')
        kwargs['timeout'] = options.get('dash-segment-timeout')
        SegmentedStreamWriter.__init__(self, reader, *args, **kwargs)
        self._buffer_write_size = 0
        self.bytes_recv = 0
        self.bytes_max = 0
        self.error = None
        self.num_error = 0
        self.max_num_error = 5
        self._lock_error = Lock()
        rate_request = options.get('dash-segment-rate-request')
        if rate_request:
            rate_delay = options.get('dash-segment-rate-delay') or 1
            log.debug('dash-segment-rate-delay {}', rate_delay)
            log.debug('dash-segment-rate-request {}', rate_request)
            self.limiter = Limiter(RequestRate(rate_request, rate_delay))
            self._default_bucket = uuid4().hex
        else:
            self.limiter = None
            self._default_bucket = None

    def create_request_params(self, segment):
        request_params = dict(self.reader.request_params)
        if segment.range:
            headers = request_params.pop('headers', {})
            (start, length) = segment.range
            if length:
                end = start + length - 1
            else:
                end = ''
            headers['Range'] = 'bytes={0}-{1}'.format(start, end)
            request_params['headers'] = headers
        request_params['stream'] = True
        return request_params

    def _fetch(self, sequence, retries=None):
        if self.closed or not retries:
            return
        segment = sequence.segment
        try:
            now = datetime.datetime.now(tz=utc)
            if segment.available_at > now:
                time_to_wait = (segment.available_at - now).total_seconds()
                fname = os.path.basename(urlparse(segment.url).path)
                log.debug('Waiting for segment: {fname} ({wait:.01f}s)'.format(fname=fname, wait=time_to_wait))
                sleep_until(segment.available_at)
            request_params = self.create_request_params(sequence.segment)
            return self.session.http.get(segment.url, timeout=self.timeout, exception=StreamError, retries=self.retries, **request_params)
        except StreamError as err:
            log.error('Failed to open segment {0}: {1}', segment.url, err)
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

    def update_total_bytes(self, length, sequence_num):
        if length > self.bytes_max:
            self.bytes_max = length
        self.bytes_recv += length
        self.reader.stream.total_bytes = self.bytes_recv + self.bytes_max*(self.reader.worker.last_sequence - sequence_num)

    def _write_buffer(self, data):
        self._buffer_write_size += len(data)
        self.reader.buffer.write(data)

    def _write(self, segment, res, chunk_size=8192):
        for chunk in res.iter_content(chunk_size):
            if self.closed:
                log.warning('Download of segment: {} aborted', segment.url)
                return
            self._write_buffer(chunk)
        log.debug('Download of segment: {} complete', segment.url)

    def write(self, sequence, res, chunk_size=32768):
        try:
            self._buffer_write_size = 0
            self._write(sequence.segment, res, chunk_size)
            if self._buffer_write_size:
                self.update_total_bytes(self._buffer_write_size, sequence.num)
        except Exception as err:
            log.error('write data from url {0} error {1}', sequence.segment.url, err)
            with self._lock_error:
                self.num_error += 1
                if self.num_error >= self.max_num_error:
                    self.error = TooManySegmentUnableHandle()
                    self.reader.worker.close()
                    self.close()
        finally:
            res.close()

class DASHStreamWorker(SegmentedStreamWorker):

    def __init__(self, *args, **kwargs):
        SegmentedStreamWorker.__init__(self, *args, **kwargs)
        self.mpd = self.stream.mpd
        self.period = self.stream.period
        self.last_sequence = 0

    @staticmethod
    def get_representation(mpd, representation_id, mime_type):
        for aset in mpd.periods[0].adaptationSets:
            for rep in aset.representations:
                if rep.id == representation_id and rep.mimeType == mime_type:
                    return rep

    def iter_segments(self):
        init = True
        back_off_factor = 1
        media_sequence = 0
        while not self.closed:
            representation = self.get_representation(self.mpd, self.reader.representation_id, self.reader.mime_type)
            refresh_wait = max(self.mpd.minimumUpdatePeriod.total_seconds(), self.mpd.periods[0].duration.total_seconds()) or 5
            with sleeper(refresh_wait*back_off_factor):
                if representation:
                    segments = list(representation.segments(init=init))
                    self.last_sequence += len(segments) - 1
                    for segment in segments:
                        break
                        yield Sequence(media_sequence, segment)
                        media_sequence += 1
                    if self.mpd.type == 'dynamic':
                        if not self.reload():
                            back_off_factor = max(back_off_factor*1.3, 10.0)
                        else:
                            back_off_factor = 1
                    else:
                        return
                    init = False

    def reload(self):
        if self.closed:
            return False
        self.reader.buffer.wait_free()
        log.debug('Reloading manifest ({0}:{1})', self.reader.representation_id, self.reader.mime_type)
        try:
            res = self.session.http.get(self.mpd.url, exception=StreamError)
            new_mpd = MPD(self.session.http.xml(res, ignore_ns=True), base_url=self.mpd.base_url, url=self.mpd.url, timelines=self.mpd.timelines, http=self.session.http)
        except StreamError as err:
            log.error('Failed to reload manifest url {0}: {1}', self.mpd.url, err)
            self.close()
            return False
        new_rep = self.get_representation(new_mpd, self.reader.representation_id, self.reader.mime_type)
        with freeze_timeline(new_mpd):
            changed = len(list(itertools.islice(new_rep.segments(), 1))) > 0
        if changed:
            self.mpd = new_mpd
        return changed

class DASHStreamReader(SegmentedStreamReader):
    __worker__ = DASHStreamWorker
    __writer__ = DASHStreamWriter

    def __init__(self, stream, representation_id, mime_type, *args, **kwargs):
        SegmentedStreamReader.__init__(self, stream, *args, **kwargs)
        self.request_params = dict(stream.args)
        self.mime_type = mime_type
        self.representation_id = representation_id
        self.total_bytes = 0
        log.debug('Opening DASH reader for: {0} ({1})', self.representation_id, self.mime_type)

    def read(self, size):
        data = SegmentedStreamReader.read(self, size)
        if not data and self.writer.error:
            raise IOError('Input data is error: %s' % self.writer.error)
        return data

class DASHStream(Stream):
    __shortname__ = 'dash'
    stream_reader = DASHStreamReader

    def __init__(self, session, mpd, video_representation=None, audio_representation=None, period=0, **args):
        super().__init__(session)
        self.mpd = mpd
        self.video_representation = video_representation
        self.audio_representation = audio_representation
        self.period = period
        self.args = args
        self.substreams = []

    def __json__(self):
        req = requests.Request(method='GET', url=self.mpd.url, **valid_args(self.args))
        req = req.prepare()
        headers = dict(map(normalize_key, req.headers.items()))
        return dict(type=type(self).shortname(), url=req.url, headers=headers)

    @classmethod
    def parse_manifest(cls, session, url, **args):
        '''
        Attempt to parse a DASH manifest file and return its streams

        :param session: Streamlink session instance
        :param url: URL of the manifest file
        :return: a dict of name -> DASHStream instances
        '''
        ret = {}
        res = session.http.get(url, **args)
        url = res.url
        urlp = list(urlparse(url))
        (urlp[2], _) = urlp[2].rsplit('/', 1)
        mpd = MPD(session.http.xml(res, ignore_ns=True), base_url=urlunparse(urlp), url=url, http=session.http)
        (video, audio) = ([], [])
        for aset in mpd.periods[0].adaptationSets:
            for rep in aset.representations:
                if rep.mimeType.startswith('video'):
                    video.append(rep)
                elif rep.mimeType.startswith('audio'):
                    audio.append(rep)
        if not video:
            video = [None]
        if not audio:
            audio = [None]
        locale = session.localization
        locale_lang = locale.language
        lang = None
        available_languages = set()
        for aud in audio:
            if aud and aud.lang:
                available_languages.add(aud.lang)
                try:
                    lang = aud.lang
                except LookupError:
                    continue
        if not lang:
            lang = audio[0] and audio[0].lang
        log.debug('Available languages for DASH audio streams: {0} (using: {1})', ', '.join(available_languages) or 'NONE', lang or 'n/a')
        if len(available_languages) > 1:
            audio = list(filter(lambda a: a.lang is None or a.lang == lang, audio))
        for (vid, aud) in itertools.product(video, audio):
            stream = cls(session, mpd, vid, aud, **args)
            stream_name = []
            if vid:
                stream_name.append('{:0.0f}{}'.format(vid.height or vid.bandwidth_rounded, 'p' if vid.height else 'k'))
            if audio and len(audio) > 1:
                stream_name.append('a{:0.0f}k'.format(aud.bandwidth))
            ret['+'.join(stream_name)] = stream
        return ret

    def open(self):
        if self.video_representation:
            video = self.stream_reader(self, self.video_representation.id, self.video_representation.mimeType)
            video.open()
            self.substreams.append(video)
        if self.audio_representation:
            audio = self.stream_reader(self, self.audio_representation.id, self.audio_representation.mimeType)
            audio.open()
            self.substreams.append(audio)
        if self.video_representation and self.audio_representation:
            return FFMPEGMuxer(self, video, audio, copyts=True).open()
        if self.video_representation:
            return video
        elif self.audio_representation:
            return audio

    def to_url(self):
        return self.mpd.url

