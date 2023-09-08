import logging
from time import time
from threading import Lock
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from StreamDownloader.utils import FormatFileSize, FormatSeconds, FormatPercent
DEFAULT_CHUNK_SIZE = 2048
DEFAULT_BUFFER_SIZE = 4096
log = logging.getLogger(__name__)

class Downloader(object):
    __doc__ = 'docstring for Chunk'

    def __init__(self, url, http_client, file, max_workers=5, reporter=None, requests_params=None):
        self.max_workers = max_workers
        self.url = url
        self.http_client = http_client
        self.file = file
        self.__lock = Lock()
        self.__dl_bytes = 0
        self.file_size = 0
        self.speed = ''
        self.eta = ''
        self.percent = ''
        self._start_time = 0
        self._pre_time = 0
        self._speeds = deque(maxlen=5)
        self._etas = deque(maxlen=5)
        self.reporter = reporter
        self.thread_pool = None
        self.futures = []
        self.closed = False
        self.download_completed = False
        if requests_params:
            requests_params.pop('url', None)
            self.request_params = requests_params
        else:
            self.request_params = {}

    def shutdown(self, wait=True):
        self.closed = True
        if self.thread_pool:
            self.thread_pool.shutdown(wait)

    def wrapCallbackError(self, state):
        try:
            self.reporter and self.reporter(state)
        except Exception as err:
            log.warning('Call reporter function error %s' % err, exc_info=log.isEnabledFor(logging.DEBUG))

    @property
    def dl_bytes(self):
        return self.__dl_bytes

    @dl_bytes.setter
    def dl_bytes(self, num):
        with self.__lock:
            self.__dl_bytes = num
        now = time()
        if now - self._pre_time > 0.2:
            self._pre_time = now
            speed = float(num)/(now - self._start_time)
            self._speeds.appendleft(speed)
            speed_avg = sum(self._speeds)/5
            self.speed = '%s/s' % FormatFileSize(speed_avg)
            if self.file_size != -1:
                if speed_avg > 0.0:
                    eta = (self.file_size - num)/speed_avg
                    self._etas.appendleft(eta)
                    self.eta = FormatSeconds(int(sum(self._etas)/5))
                self.percent = FormatPercent(float(num/self.file_size)*100.0)

    def firstChunk(self, response, start, end):
        recv_bytes = 0
        total = end - start + 1
        f = None
        try:
            f = open(self.file, 'r+b', buffering=DEFAULT_BUFFER_SIZE)
            f.seek(start)
            for chunk in response.iter_content(DEFAULT_CHUNK_SIZE):
                if self.closed:
                    return
                chunk_len = len(chunk)
                recv_bytes += chunk_len
                if recv_bytes > total:
                    remain = chunk_len - (recv_bytes - total)
                    f.write(chunk[:remain])
                    self.dl_bytes += remain
                    return
                f.write(chunk)
                self.dl_bytes += chunk_len
                if recv_bytes == total:
                    return
        except Exception as err:
            self.closed = True
            raise err
        finally:
            response.close()
            if f:
                f.flush()
                f.close()

    def create_request_params(self, start=None, end=None, is_first_segment=False):
        request_params = dict(self.request_params)
        if 'headers' in request_params:
            headers = dict(request_params['headers'])
        else:
            headers = {}
        if start != None and end != None:
            headers.update({'Range': 'bytes=%d-%d' % (start, end)})
        elif start != None:
            headers.update({'Range': 'bytes=%d-' % start})
        request_params['headers'] = headers
        return request_params

    def down(self, start, end):
        f = None
        try:
            request_params = self.create_request_params(start, end)
            r = self.http_client.get(self.url, stream=True, **request_params)
            f = open(self.file, 'r+b', buffering=DEFAULT_BUFFER_SIZE)
            f.seek(start)
            for chunk in r.iter_content(DEFAULT_CHUNK_SIZE):
                if self.closed:
                    return
                f.write(chunk)
                self.dl_bytes += len(chunk)
        except Exception as err:
            self.closed = True
            raise err
        finally:
            if f:
                f.flush()
                f.close()

    def downInfinite(self, response):
        self.file_size = -1
        with open(self.file, 'wb', buffering=DEFAULT_BUFFER_SIZE) as f:
            for chunk in response.iter_content(DEFAULT_CHUNK_SIZE):
                if self.closed:
                    f.flush()
                    return
                f.write(chunk)
                self.dl_bytes += len(chunk)
                f.flush()

    def run(self):
        self.wrapCallbackError({'state': 'start'})
        self.__dl_bytes = 0
        self.file_size = -1
        self.futures = []
        self._start_time = self._pre_time = time()
        request_params = self.create_request_params(is_first_segment=True)
        res = self.http_client.get(self.url, stream=True, **request_params)
        self.url = res.url
        if res.status_code == 200:
            self.file_size = int(res.headers.get('Content-Length', -1))
        elif res.status_code == 206:
            range_info = res.headers.get('Content-Range').split(' ')[1]
            (bytes_range, size) = range_info.split('/')
            if bytes_range == '*':
                raise Exception('Range Not Satisfiable %s' % res.headers.get('Content-Range'))
            if size != '*':
                self.file_size = int(size)
            else:
                self.file_size = -1
        if self.file_size == -1:
            log.warning('File size is unknow. Downloading indefinitely.')
            self.thread_pool = ThreadPoolExecutor(1)
            self.futures.append(self.thread_pool.submit(self.downInfinite, res))
            return
        if self.file_size <= 10485760:
            self.max_workers = 1
        with open(self.file, 'wb') as f:
            f.truncate(self.file_size)
        self.thread_pool = ThreadPoolExecutor(self.max_workers)
        chunk_size = -(-self.file_size//self.max_workers)
        for i in range(self.max_workers):
            start = i*chunk_size
            end = start + chunk_size - 1
            if end >= self.file_size:
                end = self.file_size - 1
            show_range(start, end)
            if i == 0:
                future = self.thread_pool.submit(self.firstChunk, res, start, end)
            else:
                future = self.thread_pool.submit(self.down, start, end)
            self.futures.append(future)

    def wait(self):
        s = 'Downloading'
        while not self.closed:
            try:
                for f in as_completed(self.futures, timeout=1):
                    f.result()
                s = 'done'
                break
            except TimeoutError:
                continue
            except Exception as err:
                log.debug('Download segment http error %s', err, exc_info=True)
                raise err
            finally:
                self.wrapCallbackError({'state': s, 'speed': self.speed, 'eta': self.eta, 'per': self.percent, 'total': self.file_size, 'bytes': self.dl_bytes})

def show_range(start, end):
    log.debug('start %d - end %d has bytes %d' % (start, end, end - start + 1))

