import time
import ssl
from requests import Session, __build__ as requests_version
from requests.adapters import HTTPAdapter
from streamlink.packages.requests_file import FileAdapter
from streamlink.packages.requests_blob import BlobAdapter
try:
    from requests.packages.urllib3.util import Timeout
    TIMEOUT_ADAPTER_NEEDED = requests_version < 131840
except ImportError:
    TIMEOUT_ADAPTER_NEEDED = False
try:
    from requests.packages import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except (ImportError, AttributeError):
    pass
from ...exceptions import PluginError
from ...utils import parse_json, parse_xml
__all__ = ['HTTPSession']
DEFAULT_POOLBLOCK = False
DEFAULT_POOL_CONNECTIONS = 20
DEFAULT_POOLSIZE = 50
cipher_suite = {'chrome': ['TLS_AES_128_GCM_SHA256', 'TLS_AES_256_GCM_SHA384', 'TLS_CHACHA20_POLY1305_SHA256', 'ECDHE-ECDSA-AES128-GCM-SHA256', 'ECDHE-RSA-AES128-GCM-SHA256', 'ECDHE-ECDSA-AES256-GCM-SHA384', 'ECDHE-RSA-AES256-GCM-SHA384', 'ECDHE-ECDSA-CHACHA20-POLY1305', 'ECDHE-RSA-CHACHA20-POLY1305', 'ECDHE-RSA-AES128-SHA', 'ECDHE-RSA-AES256-SHA', 'AES128-GCM-SHA256', 'AES256-GCM-SHA384', 'AES128-SHA', 'AES256-SHA', 'DES-CBC3-SHA'], 'firefox': ['TLS_AES_128_GCM_SHA256', 'TLS_CHACHA20_POLY1305_SHA256', 'TLS_AES_256_GCM_SHA384', 'ECDHE-ECDSA-AES128-GCM-SHA256', 'ECDHE-RSA-AES128-GCM-SHA256', 'ECDHE-ECDSA-CHACHA20-POLY1305', 'ECDHE-RSA-CHACHA20-POLY1305', 'ECDHE-ECDSA-AES256-GCM-SHA384', 'ECDHE-RSA-AES256-GCM-SHA384', 'ECDHE-ECDSA-AES256-SHA', 'ECDHE-ECDSA-AES128-SHA', 'ECDHE-RSA-AES128-SHA', 'ECDHE-RSA-AES256-SHA', 'DHE-RSA-AES128-SHA', 'DHE-RSA-AES256-SHA', 'AES128-SHA', 'AES256-SHA', 'DES-CBC3-SHA'], 'default': [ssl._DEFAULT_CIPHERS, '!AES128-SHA', '!ECDHE-RSA-AES256-SHA']}

def _parse_keyvalue_list(val):
    for keyvalue in val.split(';'):
        try:
            (key, value) = keyvalue.split('=', 1)
            yield (key.strip(), value.strip())
        except ValueError:
            continue

class HTTPAdapterWithReadTimeout(HTTPAdapter):
    __doc__ = """This is a backport of the timeout behaviour from requests 2.3.0+
       where timeout is applied to both connect and read."""

    def get_connection(self, *args, **kwargs):
        conn = super().get_connection(self, *args, **kwargs)
        if not hasattr(conn.urlopen, 'wrapped'):
            orig_urlopen = conn.urlopen

            def urlopen(*args, **kwargs):
                timeout = kwargs.pop('timeout', None)
                if isinstance(timeout, Timeout):
                    timeout = Timeout.from_float(timeout.connect_timeout)
                return orig_urlopen(*args, timeout=timeout, **kwargs)

            conn.urlopen = urlopen
            conn.urlopen.wrapped = True
        return conn

class TlsBrowserHTTPAdapter(HTTPAdapter):

    def __init__(self, *args, **kwargs):
        self.ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        self.ssl_context.check_hostname = False
        self.ssl_context.set_ciphers(':'.join(cipher_suite['chrome']))
        self.ssl_context.set_ecdh_curve('prime256v1')
        self.ssl_context.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3 | ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
        kwargs['pool_connections'] = DEFAULT_POOL_CONNECTIONS
        kwargs['pool_maxsize'] = DEFAULT_POOLSIZE
        kwargs['pool_block'] = DEFAULT_POOLBLOCK
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, *args, **kwargs):
        kwargs['ssl_context'] = self.ssl_context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs['ssl_context'] = self.ssl_context
        return super().proxy_manager_for(*args, **kwargs)

class HTTPSession(Session):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timeout = 20.0
        self.verify = False
        self.mount('https://', TlsBrowserHTTPAdapter())
        http_adapter = self.get_adapter('http://')
        http_adapter.init_poolmanager(DEFAULT_POOL_CONNECTIONS, DEFAULT_POOLSIZE, DEFAULT_POOLBLOCK)
        self.mount('file://', FileAdapter())
        self.mount('blob://', BlobAdapter())

    @classmethod
    def determine_json_encoding(cls, sample):
        '''
        Determine which Unicode encoding the JSON text sample is encoded with

        RFC4627 (http://www.ietf.org/rfc/rfc4627.txt) suggests that the encoding of JSON text can be determined
        by checking the pattern of NULL bytes in first 4 octets of the text.
        :param sample: a sample of at least 4 bytes of the JSON text
        :return: the most likely encoding of the JSON text
        '''
        nulls_at = [i for (i, j) in enumerate(bytearray(sample[:4])) if j == 0]
        if nulls_at == [0, 1, 2]:
            return 'UTF-32BE'
        if nulls_at == [0, 2]:
            return 'UTF-16BE'
        if nulls_at == [1, 2, 3]:
            return 'UTF-32LE'
        elif nulls_at == [1, 3]:
            return 'UTF-16LE'
        else:
            return 'UTF-8'

    @classmethod
    def json(cls, res, *args, **kwargs):
        'Parses JSON from a response.'
        if res.encoding is None:
            res.encoding = cls.determine_json_encoding(res.content[:4])
        return parse_json(res.text, *args, **kwargs)

    @classmethod
    def xml(cls, res, *args, **kwargs):
        'Parses XML from a response.'
        return parse_xml(res.text, *args, **kwargs)

    def parse_cookies(self, cookies, **kwargs):
        '''Parses a semi-colon delimited list of cookies.

        Example: foo=bar;baz=qux
        '''
        for (name, value) in _parse_keyvalue_list(cookies):
            self.cookies.set(name, value, **kwargs)

    def parse_headers(self, headers):
        '''Parses a semi-colon delimited list of headers.

        Example: foo=bar;baz=qux
        '''
        for (name, value) in _parse_keyvalue_list(headers):
            self.headers[name] = value

    def parse_query_params(self, cookies, **kwargs):
        '''Parses a semi-colon delimited list of query parameters.

        Example: foo=bar;baz=qux
        '''
        for (name, value) in _parse_keyvalue_list(cookies):
            self.params[name] = value

    def resolve_url(self, url):
        'Resolves any redirects and returns the final URL.'
        return self.get(url, stream=True).url

    def request(self, method, url, *args, **kwargs):
        acceptable_status = kwargs.pop('acceptable_status', [])
        exception = kwargs.pop('exception', PluginError)
        headers = kwargs.pop('headers', {})
        params = kwargs.pop('params', {})
        proxies = kwargs.pop('proxies', self.proxies)
        raise_for_status = kwargs.pop('raise_for_status', True)
        schema = kwargs.pop('schema', None)
        session = kwargs.pop('session', None)
        timeout = kwargs.pop('timeout', self.timeout)
        total_retries = kwargs.pop('retries', 0)
        retry_backoff = kwargs.pop('retry_backoff', 0.3)
        retry_max_backoff = kwargs.pop('retry_max_backoff', 10.0)
        retries = 1
        if session:
            headers.update(session.headers)
            params.update(session.params)
        while True:
            try:
                res = super().request(method, url, *args, headers=headers, params=params, timeout=timeout, proxies=proxies, **kwargs)
                if raise_for_status and res.status_code not in acceptable_status:
                    res.raise_for_status()
                break
            except KeyboardInterrupt:
                raise
            except Exception as rerr:
                if retries >= total_retries:
                    err = exception('Unable to open URL: {url} ({err})'.format(url=url, err=rerr))
                    err.err = rerr
                    raise err
                retries += 1
                delay = min(retry_max_backoff, retry_backoff*2**(retries - 1))
                time.sleep(delay)
        if schema:
            res = schema.validate(res.text, name='response text', exception=PluginError)
        return res

