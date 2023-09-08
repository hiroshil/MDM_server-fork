import io
import re
import logging
import socket
import ssl
import math
import threading
from time import time
from subprocess import Popen, PIPE
from websocket import create_connection, WebSocket, STATUS_NORMAL
from websocket._abnf import ABNF
import six
import struct
import urllib.request
from io import BytesIO
import gzip
import zlib
from hashlib import md5
from Crypto.Cipher import AES
from streamlink import StreamError
from streamlink.stream import Stream
from streamlink.buffers import RingBuffer
BLOCK_SIZE = 16
log = logging.getLogger(__name__)

def pad(data):
    padding = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return data + padding*chr(padding)

def unpadPkcs7(paddedData):
    '''
    Remove the PKCS#7 padding
    '''
    val = ord(paddedData[-1:])
    if val > BLOCK_SIZE:
        raise StreamError('Input is not padded or padding is corrupt, got padding size of {0}'.format(val))
    return paddedData[:-val]

class HydraxNotFoundPasswordEncrypt(Exception):

    def __init__(self):
        super().__init__('Not found password use to encrypt content')

class MyWebsocket(WebSocket):
    __doc__ = 'docstring for MyWebsocket'

    def close(self, status=STATUS_NORMAL, reason=six.b(''), timeout=3):
        if self.connected:
            if status < 0 or status >= ABNF.LENGTH_16:
                raise ValueError('code is invalid range')
            try:
                self.connected = False
                self.send(struct.pack('!H', status) + reason, ABNF.OPCODE_CLOSE)
                sock_timeout = self.sock.gettimeout()
                self.sock.settimeout(timeout)
                try:
                    self.recv_frame()
                except:
                    pass
                self.sock.settimeout(sock_timeout)
                self.sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
        self.shutdown()

def sizeof_fmt(num, suffix='B'):
    num = float(num)
    for unit in ('', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi'):
        if abs(num) < 1024.0:
            return '%3.1f%s%s' % (num, unit, suffix)
        num /= 1024.0
    return '%.1f%s%s' % (num, 'Yi', suffix)

class WebSocketStreamReader(io.IOBase):
    __doc__ = 'docstring for WebSocketStreamReader'
    re_metadata = re.compile('^\\_?(sd|mHd|hd|fullHd|origin|$)\\_(\\d+)\\_(\\d+)\\_(.*)')
    re_parse_chunk = re.compile('^(\\d+)_(\\d)_')
    re_remove = re.compile('\\d+')
    DATA_CHUNK_OK = 0
    MISS_DATA_CHUNK = 1
    NEED_DECRYPT = 2

    def __init__(self, stream):
        super().__init__()
        self.stream = stream
        self.quality = self.stream.quality
        buffer_size = self.stream.session.get_option('ringbuffer-size')
        self.buffer = RingBuffer(buffer_size)
        self.timeout = self.stream.session.options.get('stream-timeout')
        self.http_timeout = self.stream.session.http.timeout
        self.ws = None
        self.resolution = ''
        self.old_resolution = ''
        self.file_length = 0
        self.old_fileLength = 0
        self.chunk_length = 0
        self.__closed = False
        self.max_try_data_error = 10
        self.retries_data_err = 0
        self.hydrax_key_encrypt = b''
        self.password = ''
        self.last_chunk_index = 0
        self.last_chunk_length = 0
        self._error = None

    def _checkStateDataChunk(self, data_len, current_chunk):
        if self.last_chunk_index != current_chunk and data_len == self.chunk_length or self.last_chunk_index == current_chunk and data_len == self.last_chunk_length:
            return self.DATA_CHUNK_OK
        if self.last_chunk_index != current_chunk and data_len > self.chunk_length or self.last_chunk_index == current_chunk and data_len > self.last_chunk_length:
            return self.NEED_DECRYPT
        return self.MISS_DATA_CHUNK

    def _processChunk(self):
        current_chunk = 0
        try:
            while not self.__closed and self.ws.connected:
                data = self.ws.recv()
                data_len = len(data)
                if not data_len:
                    break
                if data_len == 1 and data[0] == 48:
                    self.ws_send(str((current_chunk + 1)*self.chunk_length))
                else:
                    if isinstance(data, bytes):
                        sign_data = data[:40].decode('latin1')
                    else:
                        sign_data = data[:40]
                    match = self.re_parse_chunk.match(sign_data)
                    if not match:
                        raise IOError('data not supported %r' % sign_data)
                    data_media = data[len(match.group(0)):]
                    current_chunk = int(match.group(1))
                    data_media_len = len(data_media)
                    state = self._checkStateDataChunk(data_media_len, current_chunk)
                    if state == self.NEED_DECRYPT:
                        data_media = self.decrypt(data_media, self.makeKey(self.password, current_chunk))
                        data_media_len = len(data_media)
                        state = self._checkStateDataChunk(data_media_len, current_chunk)
                        if state != self.DATA_CHUNK_OK:
                            self._resetButKeepVideoQuality(current_chunk*self.chunk_length)
                        else:
                            self.buffer.write(data_media)
                            if self.last_chunk_index == current_chunk:
                                break
                    elif state == self.MISS_DATA_CHUNK:
                        self._resetButKeepVideoQuality(current_chunk*self.chunk_length)
                    else:
                        self.buffer.write(data_media)
                        if self.last_chunk_index == current_chunk:
                            break
                    self.buffer.write(data_media)
                    if self.last_chunk_index == current_chunk:
                        break
        except Exception as err:
            log.error('Process data chunk error (%s)' % err, exc_info=log.isEnabledFor(logging.DEBUG))
            self._error = err
        finally:
            self.close()

    def _resetButKeepVideoQuality(self, offset):
        print('reset video')
        self.retries_data_err += 1
        if self.retries_data_err > self.max_try_data_error:
            raise IOError('Missing data per a chunk')
        while self.retries_data_err <= self.max_try_data_error:
            if self.__closed:
                return
            self.ws.close()
            self._reset(offset)
            if self.file_length == self.old_fileLength and self.resolution == self.old_resolution:
                return
            self.retries_data_err += 1
        raise StreamError('Reset video quality failed')

    def makePassword(self, reverse_id):
        if reverse_id:
            return re.sub('[0-9]+', '', reverse_id)
        return reverse_id

    def myReverse(self, hydrax_id):
        n = 2
        id_len = len(hydrax_id)
        return ''.join(reversed([hydrax_id[i:i + n] for i in range(0, id_len, n)]))

    def _reset(self, offset=0):
        config = self.stream.config
        headers = []
        for (key, value) in self.stream.session.http.headers.items():
            if key.lower() == 'origin' and config.get('origin_header', '') == '':
                config['origin_header'] = value
            elif key.lower() == 'user-agent' or key.lower() == 'referer':
                headers.append('%s:%s' % (key, value))
        headers.append('Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits')
        headers.append('Pragma: no-cache')
        headers.append('Cache-Control: no-cache')
        reverse_id = self.myReverse(config['id'])
        self.password = self.makePassword(reverse_id)
        if self.password:
            self.hydrax_key_encrypt = self.makeKey(self.password)
        else:
            raise HydraxNotFoundPasswordEncrypt()
        headers.append('Sec-WebSocket-Protocol: %s' % reverse_id)
        self.ws = create_connection('wss://%s' % config['domain'], timeout=self.http_timeout, class_=MyWebsocket, sslopt={'cert_reqs': ssl.CERT_NONE}, enable_multithread=True, origin=config['origin_header'], header=headers)
        self.ws_send('%s_%d' % (self.quality, int(time())))
        data = self.ws.recv()
        data = self.decrypt(data.decode('utf8').encode('latin1'), self.hydrax_key_encrypt)
        if isinstance(data, bytes):
            sign_data = data[:32].decode('latin1')
        else:
            sign_data = data[:32]
        log.debug('id: %s - sign data %r' % (config.get('id'), sign_data))
        match = self.re_metadata.match(sign_data)
        if match:
            self.resolution = match.group(1)
            self.file_length = int(match.group(2))
            self.chunk_length = int(match.group(3))
            self.last_chunk_length = self.file_length % self.chunk_length or self.chunk_length
            self.last_chunk_index = math.ceil(self.file_length/self.chunk_length) - 1
            log.debug('id: %s - Quality: %s - file size: %s' % (config.get('id'), self.resolution, self.file_length))
            self.ws_send(str(offset))
        else:
            log.debug('sign_data %s' % sign_data)
            raise IOError('hydrax server return missing metadata')

    def makeKey(self, data1, data2=''):
        m = md5(bytes('%s%s' % (data1, data2), 'ascii'))
        return m.hexdigest().encode('ascii')

    def encrypt(self, data):
        cipher = AES.new(self.hydrax_key_encrypt, AES.MODE_ECB)
        data = pad(data)
        if isinstance(data, str):
            data = data.encode('latin1')
        enc = cipher.encrypt(data)
        return enc.decode('latin1').encode('utf-8')

    def decrypt(self, data, key):
        cipher = AES.new(key, AES.MODE_ECB)
        plain = cipher.decrypt(data)
        return unpadPkcs7(plain)

    def ws_send(self, data):
        self.ws.send(self.encrypt(data), ABNF.OPCODE_BINARY)

    def open(self):
        self._reset()
        self.old_resolution = self.resolution
        self.old_fileLength = self.file_length
        threading.Thread(target=self._processChunk, daemon=True).start()

    def read(self, size=-1):
        if self._error:
            raise IOError('Process data chunk error (%s)' % self._error)
        return self.buffer.read(size, True, self.timeout)

    def close(self):
        self.__closed = True
        self.buffer.close()
        self.ws.close()

class WebSocketStream(Stream):
    __doc__ = 'docstring for WebSocketStream'

    def __init__(self, session_, config, quality):
        super().__init__(session_)
        self.config = config
        self.quality = quality
        self.reader = None

    @property
    def total_bytes(self):
        if self.reader != None:
            return self.reader.file_length
        return 0

    @total_bytes.setter
    def total_bytes(self, value):
        pass

    def open(self):
        self.reader = WebSocketStreamReader(self)
        self.reader.open()
        return self.reader

PATCH_JS = """
global.atob = function(str){
    return Buffer.from(str, \"base64\").toString();
}

global.PLAYER = function(obj){
    console.log(obj);
    return {};
}
"""
PATCH_SoTrymConfigDefault_JS = """
global.window = {}
Object.defineProperty(window, \"SoTrymConfigDefault\", {
    set: function(value){
        console.log(JSON.stringify(value));
    },
    get: function(){}
},
{
    configurable: true,
    writable: true,
});
"""

def run_nodejs(cmd, pipe_input=None):
    stdin = PIPE if pipe_input else None
    with Popen(cmd, stdin=stdin, stdout=PIPE, stderr=PIPE) as p:
        (stdout_data, stderr_data) = p.communicate(input=pipe_input)
        if p.returncode != 0:
            raise RuntimeError('nodejs returns non-zero value! Error msg: %s' % stderr_data.decode('utf-8'))
        elif stderr_data:
            log.warning('nodejs has warnings: %s' % stderr_data.decode('utf-8'))
        return stdout_data.decode('utf8')
    return ''

def request(url, headers):
    headers['Accept-Encoding'] = 'gzip'
    http_request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(http_request) as r:
        content_encoding = r.info().get('Content-Encoding')
        if content_encoding == 'gzip':
            f = gzip.GzipFile(fileobj=BytesIO(r.read()))
            data = f.read()
            f.close()
        elif content_encoding == 'deflate':
            data = zlib.decompress(r.read(), -zlib.MAX_WBITS)
        else:
            data = r.read()
    return (data.decode('utf-8'), r.geturl())

