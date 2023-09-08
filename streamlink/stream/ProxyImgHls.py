import time
import logging
from streamlink.stream.hls import HLSStream, HLSStreamReader, HLSStreamWriter
from pyrate_limiter import Duration, Limiter, RequestRate
log = logging.getLogger(__name__)

class ProxyImg_HLSStreamWriter(HLSStreamWriter):

    def __init__(self, reader, *args, **kwargs):
        reader.stream.session.options.set('hls-segment-rate-request', 1)
        print('ProxyImg_HLSStreamWriter')
        super().__init__(reader, *args, **kwargs)

    def _write(self, sequence, res, chunk_size=32768):
        chunks = res.iter_content(chunk_size)
        check_data = b''
        for chunk in chunks:
            check_data += chunk
            if len(check_data) >= chunk_size:
                break
        chunk = self.validateAndTrim(sequence, check_data)
        self._write_buffer(chunk)
        for chunk in chunks:
            self._write_buffer(chunk)

class ProxyImg_HLSStreamReader(HLSStreamReader):
    __writer__ = ProxyImg_HLSStreamWriter

class ProxyImg_HLSStream(HLSStream):
    stream_reader = ProxyImg_HLSStreamReader

    def __repr__(self):
        return '<ProxyImg_HLSStream({0!r})>'.format(self.url)

