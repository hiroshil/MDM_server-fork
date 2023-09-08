import os
import sys
import errno
import logging
from threading import Event
from time import time, sleep
from itertools import chain
from collections import deque
from functools import partial
from traceback import format_exc
from concurrent.futures import ThreadPoolExecutor, wait
from streamlink import Streamlink, StreamError, PluginError, NoPluginError
from streamlink.utils.named_pipe import NamedPipe
from streamlink.stream.hls import HLSStream, MuxedHLSStream
from streamlink.stream.http import HTTPStream
from streamlink.compat import which
from StreamDownloader.constants import STREAM_SYNONYMS
from StreamDownloader.compat import is_win32
from StreamDownloader.output import FileOutput, PlayerOutput
from StreamDownloader.HttpMultiDownloader import Downloader
from StreamDownloader.utils import FormatFileSize, FormatSeconds, FormatPercent
ACCEPTABLE_ERRNO = (errno.EPIPE, errno.EINVAL, errno.ECONNRESET)
try:
    ACCEPTABLE_ERRNO += (errno.WSAECONNABORTED,)
except AttributeError:
    pass
CURRENT_DIR = os.getcwd()
FFMPEG_LOCATION = os.path.join(CURRENT_DIR, 'data', 'executes', 'ffmpeg.exe')
NODEJS_LOCATION = os.path.join(CURRENT_DIR, 'data', 'executes', 'node.exe')

class StreamDownloaderError(Exception):
    pass

log = logging.getLogger('StreamDownloader')

def find_ffmpeg():
    if FFMPEG_LOCATION and os.path.exists(FFMPEG_LOCATION):
        return FFMPEG_LOCATION
    default = ['ffmpeg', 'ffmpeg.exe', 'avconv', 'avconv.exe']
    for cmd in default:
        if which(cmd):
            return cmd

def find_nodejs():
    if NODEJS_LOCATION and os.path.exists(NODEJS_LOCATION):
        return NODEJS_LOCATION
    default = ['node', 'node.exe']
    for cmd in default:
        if which(cmd):
            return cmd

class StreamDownloader(object):
    __doc__ = 'docstring for StreamDownloader'

    def __init__(self, url, filename, headers, quality='best', threads=5, options=None, del_file_error=True, reporter=None, cookies=None):
        self.url = url
        self.filename = filename
        self.quality = quality
        self.http_threads = threads
        self.streamlink = Streamlink()
        default_options = {'hls-segment-attempts': 3, 'hls-segment-threads': threads, 'hls-segment-timeout': 30.0, 'dash-segment-attempts': 3, 'dash-segment-timeout': 30.0, 'ringbuffer-size': 33554432, 'http-timeout': 60, 'stream-timeout': 60, 'http-headers': headers}
        threads = int(threads/2)
        if threads < 1:
            threads = 1
        default_options['dash-segment-threads'] = threads
        if options:
            default_options.update(options)
        self.setOptions(default_options)
        if cookies:
            for cookie in cookies:
                self.streamlink.http.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
        self.del_file_error = del_file_error
        self.streams = None
        self.plugin = None
        self.reporter = reporter
        self.stream_fd = None
        self.stream_output = None
        self.subtitle_downloader = None
        self.http_multi_downloader = None
        self.ev_close = Event()
        self.ev_close.clear()
        self.closed = False
        self.setOption('ffmpeg-ffmpeg', find_ffmpeg())
        self.setOption('node-nodejs', find_nodejs())

    def wrapCallbackError(self, state):
        try:
            self.reporter and self.reporter(state)
        except:
            log.debug('Call reporter function error', exc_info=True)

    def delFileError(self):
        try:
            if self.del_file_error and os.path.exists(self.filename):
                os.remove(self.filename)
        except Exception as err:
            log.warning("Don't delete %s err %s" % (self.filename, err))

    def setOptions(self, options):
        for (key, value) in options.items():
            self.setOption(key, value)

    def setOption(self, key, value):
        self.streamlink.set_option(key, value)

    def _close_sub_downloader(self):
        if self.subtitle_downloader:
            self.subtitle_downloader.shutdown()
        if self.http_multi_downloader:
            self.http_multi_downloader.shutdown()

    def close(self, wait=True):
        self.closed = True
        if wait:
            while True:
                self._close_sub_downloader()
                if self.ev_close.wait(0.5):
                    break
        else:
            self._close_sub_downloader()

    def httpStreamMultiDownload(self, stream):
        max_workers = stream.max_workers or self.http_threads
        self.http_multi_downloader = Downloader(stream.url, self.streamlink.http, self.filename, max_workers, self.reporter, stream.args)
        self.http_multi_downloader.run()
        self.http_multi_downloader.wait()
        self.http_multi_downloader.shutdown()

    def getQualities(self):
        validstreams = []
        self.handleUrl()
        for name in sorted(self.streams.keys(), key=lambda stream_name: self.plugin.stream_weight(stream_name)):
            if name in STREAM_SYNONYMS:
                continue
            validstreams.append(name)
        return validstreams

    def printQualities(self):
        streams_name = self.getQualities()
        if streams_name:
            print(', '.join(streams_name))
        else:
            print('Undefined')

    def resolve_stream_name(self, streams, stream_name):
        'Returns the real stream name of a synonym.'
        if stream_name in STREAM_SYNONYMS and stream_name in streams:
            for (name, stream) in streams.items():
                if stream is streams[stream_name] and name not in STREAM_SYNONYMS:
                    return name
        return stream_name

    def openStream(self, stream):
        try:
            stream_fd = stream.open()
        except StreamError as err:
            raise StreamError('Could not open stream: %s' % err)
        try:
            log.debug('Pre-buffering 8192 bytes')
            prebuffer = stream_fd.read(8192)
        except IOError as err:
            stream_fd.close()
            raise StreamError('Failed to read data from stream: %s' % err)
        if not prebuffer:
            stream_fd.close()
            raise StreamError('No data returned from stream')
        return (stream_fd, prebuffer)

    def createOutput(self, stream):
        out = namedpipe = None
        log.debug('createOutput')
        if (isinstance(stream, HLSStream) or isinstance(stream, MuxedHLSStream)) and getattr(stream, 'toMp4', True):
            log.debug('create FFmpeg output')
            try:
                namedpipe = NamedPipe('streamlinkpipe_%s' % os.getpid())
            except IOError as err:
                raise StreamDownloaderError('Failed to create pipe %s' % err)
            ffmpeg_exe = find_ffmpeg()
            if not ffmpeg_exe:
                raise StreamDownloaderError('Did not find ffmpeg')
            args = '-i %s -y -c copy -bsf:a aac_adtstoasc "%s"' % (namedpipe.path, self.filename)
            out = PlayerOutput(ffmpeg_exe, args=args, namedpipe=namedpipe, kill=False)
        else:
            log.debug('FileOutput')
            out = FileOutput(self.filename)
        return out

    def progress(self, stream_iter, stream):
        start = pre_time = time()
        speeds = deque(maxlen=5)
        etas = deque(maxlen=5)
        bytes_recv = 0
        total_bytes = 0
        speed = ''
        eta = ''
        percent = ''
        for data in stream_iter:
            break
            yield data
            bytes_recv += len(data)
            total_bytes = stream.total_bytes
            now = time()
            if not self.closed or now - pre_time > 0.2:
                speed = bytes_recv/(now - start)
                speeds.appendleft(speed)
                speed_avg = sum(speeds)/5
                speed = '%s/s' % FormatFileSize(speed_avg)
                if total_bytes:
                    if speed_avg > 0.0:
                        eta = (total_bytes - bytes_recv)/speed_avg
                        etas.appendleft(eta)
                        eta = FormatSeconds(int(sum(etas)/5))
                    percent = FormatPercent(float(bytes_recv/total_bytes)*100.0)
                pre_time = now
            self.wrapCallbackError({'state': 'Downloading', 'speed': speed, 'eta': eta, 'per': percent, 'total': total_bytes, 'bytes': bytes_recv})

    def readStream(self, stream, stream_fd, output, prebuffer, chunk_size=32768):
        'Reads data from stream and then writes it to the output.'
        is_player = isinstance(output, PlayerOutput)
        is_fifo = is_player and output.namedpipe
        stream_iterator = chain([prebuffer], iter(partial(stream_fd.read, chunk_size), b''))
        stream_iterator = self.progress(stream_iterator, stream)
        try:
            for data in stream_iterator:
                if self.closed:
                    break
                if is_win32 and is_fifo:
                    output.player.poll()
                    if output.player.returncode is not None:
                        log.debug('Player closed')
                        break
                try:
                    output.write(data)
                except IOError as err:
                    if is_player and err.errno in ACCEPTABLE_ERRNO:
                        raise StreamDownloaderError('FFmpeg closed')
                    else:
                        raise StreamDownloaderError('Error when writing to output: %s, exiting' % err)
                    break
        except IOError as err:
            raise StreamDownloaderError('Error when reading from stream: %s, exiting' % err)
        finally:
            output.close()
            stream_fd.close()
            log.debug('Stream ended')

    def outputStream(self, stream):
        if type(stream) == HTTPStream and isinstance(stream, HTTPStream):
            self.httpStreamMultiDownload(stream)
            return True
        try:
            (stream_fd, prebuffer) = self.openStream(stream)
        except StreamError as err:
            raise StreamDownloaderError('Could not open stream %r %s' % (stream, err))
        output = self.createOutput(stream)
        if not output:
            return False
        try:
            output.open()
        except (IOError, OSError) as err:
            if isinstance(output, PlayerOutput):
                raise StreamDownloaderError('Failed to start ffmpeg: (%s)' % err)
            else:
                raise StreamDownloaderError('Failed to open output: %s (%s)' % (self.filename, err))
            return False
        self.readStream(stream, stream_fd, output, prebuffer)
        return True

    def handleStream(self):
        stream_name = self.quality
        streams = self.streams
        if stream_name in streams:
            stream_name = self.resolve_stream_name(streams, stream_name)
        alt_streams = list(filter(lambda k: stream_name in k and stream_name != k, sorted(streams.keys())))
        error = None
        for stream_name in [stream_name] + alt_streams:
            stream = streams[stream_name]
            if stream.meta.get('plugin', None):
                try:
                    self.handleSubtitles(stream.meta['plugin'])
                except Exception as err:
                    log.warning('handle subtitles error %s', err, exc_info=log.isEnabledFor(logging.DEBUG))
            try:
                if self.outputStream(stream):
                    return
            except Exception as err:
                error = err
                log.debug('Handle stream name %s error %s', stream_name, err, exc_info=True)
        if error:
            raise error

    def handleSubtitles(self, plugin):
        if not hasattr(plugin, 'subtitles'):
            return
        subtitles = plugin.subtitles()
        if not subtitles:
            return
        self.subtitle_downloader = MultiSubtitlesDownloader(self.streamlink.http)
        for (lang, subtiles_stream) in subtitles.items():
            filename = os.path.splitext(self.filename)[0] + '.%s.srt' % lang
            self.subtitle_downloader.add(subtiles_stream, filename)

    def handleUrl(self):
        self.ev_close.set()
        url = self.url
        if self.streams and self.plugin:
            return
        self.streams = self.plugin = None
        if self.closed:
            return
        self.wrapCallbackError({'state': 'analyzing'})
        try:
            self.plugin = self.streamlink.resolve_url(url)
        except NoPluginError:
            raise
        except PluginError as err:
            log.debug('Plugin error %s', err, exc_info=True)
            raise err
        if self.closed:
            return
        try:
            self.streams = self.plugin.streams()
        except Exception as err:
            log.debug('Get stream error: %s', err, exc_info=True)
            raise err
        if not self.streams:
            raise StreamDownloaderError('Streams not found on this url %s' % url)

    def _download(self):
        self.handleUrl()
        self.wrapCallbackError({'state': 'start'})
        self.ev_close.clear()
        self.handleSubtitles(self.plugin)
        self.handleStream()
        if self.subtitle_downloader:
            self.subtitle_downloader.wait()
            self.subtitle_downloader.shutdown()

    def download(self):
        try:
            self._download()
        except Exception as err:
            self.delFileError()
            raise err
        finally:
            self.ev_close.set()
            self.wrapCallbackError({'state': 'done'})
            try:
                self.streamlink.close()
            except:
                pass

class MultiSubtitlesDownloader(object):
    __doc__ = 'docstring for MultiSubtitlesDownloader'

    def __init__(self, http, max_workers=3):
        self.log = logging.getLogger('%s.SubDownloader' % __name__)
        self.http = http
        self.threadpool = ThreadPoolExecutor(max_workers)
        self.futures = []
        self.downloaders = []
        self.done_counter = 0
        self.closed = False

    def shutdown(self):
        self.closed = True
        for downloader in self.downloaders:
            downloader.shutdown()
        self.threadpool.shutdown()

    def wait(self):
        (done, _) = wait(self.futures)
        for f in done:
            if self.closed:
                return
            try:
                f.result()
            except Exception as err:
                self.log.error('Download subtitles error %s', err, exc_info=log.isEnabledFor(logging.DEBUG))

    def download(self, stream, filename):
        http_multi_downloader = Downloader(stream.url, self.http, filename, 1)
        self.downloaders.append(http_multi_downloader)
        http_multi_downloader.run()
        http_multi_downloader.wait()
        http_multi_downloader.shutdown()
        self.downloaders.remove(http_multi_downloader)

    def add(self, stream, filename):
        future = self.threadpool.submit(self.download, stream, filename)
        self.futures.append(future)

