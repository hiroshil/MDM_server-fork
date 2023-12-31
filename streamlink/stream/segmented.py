import concurrent.futures.thread
import logging
from concurrent import futures
from threading import Thread, Event
from .stream import StreamIO
from ..buffers import RingBuffer
from ..compat import queue
log = logging.getLogger(__name__)

class SegmentedStreamWorker(Thread):
    __doc__ = """The general worker thread.

    This thread is responsible for queueing up segments in the
    writer thread.
    """

    def __init__(self, reader, **kwargs):
        self.closed = False
        self.reader = reader
        self.writer = reader.writer
        self.stream = reader.stream
        self.session = reader.stream.session
        self._wait = None
        Thread.__init__(self, name='Thread-{0}'.format(self.__class__.__name__))
        self.daemon = True

    def close(self):
        'Shuts down the thread.'
        if not self.closed:
            log.debug('Closing worker thread')
        self.closed = True
        if self._wait:
            self._wait.set()

    def wait(self, time):
        '''Pauses the thread for a specified time.

        Returns False if interrupted by another thread and True if the
        time runs out normally.
        '''
        self._wait = Event()
        return not self._wait.wait(time)

    def iter_segments(self):
        '''The iterator that generates segments for the worker thread.

        Should be overridden by the inheriting class.
        '''
        while False:
            yield None

    def run(self):
        for segment in self.iter_segments():
            if self.closed:
                break
            self.writer.put(segment)
        self.writer.put(None)
        self.close()

class SegmentedStreamWriter(Thread):
    __doc__ = """The writer thread.

    This thread is responsible for fetching segments, processing them
    and finally writing the data to the buffer.
    """

    def __init__(self, reader, size=3, retries=None, threads=None, timeout=None, ignore_names=None):
        self.closed = False
        self.reader = reader
        self.stream = reader.stream
        self.session = reader.stream.session
        if not retries:
            retries = self.session.options.get('stream-segment-attempts')
        if not threads:
            threads = self.session.options.get('stream-segment-threads')
        if not timeout:
            timeout = self.session.options.get('stream-segment-timeout')
        self.retries = retries
        self.timeout = timeout
        self.ignore_names = ignore_names
        self.executor = futures.ThreadPoolExecutor(max_workers=threads)
        if threads:
            size = threads - 2
            if size <= 0:
                size = 3
        self.threads = threads
        self.futures = queue.Queue(size)
        Thread.__init__(self, name='Thread-{0}'.format(self.__class__.__name__))
        self.daemon = True

    def close(self):
        'Shuts down the thread.'
        if not self.closed:
            log.debug('Closing writer thread')
        self.closed = True
        self.reader.buffer.close()
        self.executor.shutdown(wait=False)
        try:
            pass
        except queue.Empty:
            pass
        if concurrent.futures.thread._threads_queues:
            concurrent.futures.thread._threads_queues.clear()

    def put(self, segment):
        'Adds a segment to the download pool and write queue.'
        if self.closed:
            return
        if segment is not None:
            future = self.executor.submit(self.fetch, segment, retries=self.retries)
        else:
            future = None
        self.queue(self.futures, (segment, future))

    def queue(self, queue_, value):
        'Puts a value into a queue but aborts if this thread is closed.'
        while not self.closed:
            try:
                queue_.put(value, block=True, timeout=1)
                return
            except queue.Full:
                continue

    def fetch(self, segment, **kwargs):
        '''Fetches a segment.

        Should be overridden by the inheriting class.
        '''
        pass

    def write(self, segment, result, **kwargs):
        '''Writes a segment to the buffer.

        Should be overridden by the inheriting class.
        '''
        pass

    def run(self):
        while not self.closed:
            try:
                (segment, future) = self.futures.get(block=True, timeout=0.5)
            except queue.Empty:
                continue
            if future is None:
                break
            while not self.closed:
                try:
                    result = future.result(timeout=0.5)
                except futures.TimeoutError:
                    continue
                except futures.CancelledError:
                    break
                if result is not None:
                    self.write(segment, result)
                break
        self.close()

class SegmentedStreamReader(StreamIO):
    __worker__ = SegmentedStreamWorker
    __writer__ = SegmentedStreamWriter

    def __init__(self, stream, timeout=None):
        StreamIO.__init__(self)
        self.session = stream.session
        self.stream = stream
        if not timeout:
            timeout = self.session.options.get('stream-timeout')
        self.timeout = timeout

    def setWorker(cls, worker):
        cls.__worker__ = worker

    def setWriter(cls, writer):
        cls.__writer__ = writer

    def open(self):
        buffer_size = self.session.get_option('ringbuffer-size')
        self.buffer = RingBuffer(buffer_size)
        self.writer = self.__writer__(self)
        self.worker = self.__worker__(self)
        self.writer.start()
        self.worker.start()

    def close(self):
        self.worker.close()
        self.writer.close()
        self.buffer.close()

    def read(self, size):
        if not self.buffer:
            return b''
        return self.buffer.read(size, block=self.writer.is_alive(), timeout=self.timeout)

