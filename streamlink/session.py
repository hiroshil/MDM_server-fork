import sys
import logging
import traceback
import requests
from streamlink.logger import StreamlinkLogger
from streamlink.utils import update_scheme
from streamlink.utils.l10n import Localization
from . import __version__
from .compat import is_win32
from .exceptions import NoPluginError, PluginError
from .options import Options
from .plugin import api
from .plugins import ALL_PLUGINS
logging.setLoggerClass(StreamlinkLogger)
log = logging.getLogger(__name__)

def print_small_exception(start_after):
    (_type, value, traceback_) = sys.exc_info()
    tb = traceback.extract_tb(traceback_)
    index = 0
    for (i, trace) in enumerate(tb):
        if trace[2] == start_after:
            index = i + 1
            break
    lines = traceback.format_list(tb[index:])
    lines += traceback.format_exception_only(_type, value)
    for line in lines:
        sys.stderr.write(line)
    sys.stderr.write('\n')

class Streamlink(object):
    __doc__ = """A Streamlink session is used to keep track of plugins,
       options and log settings."""

    def __init__(self, options=None):
        self.http = api.HTTPSession()
        self.options = Options({'hds-live-edge': 10.0, 'hds-segment-attempts': 3, 'hds-segment-threads': 1, 'hds-segment-timeout': 10.0, 'hds-timeout': 60.0, 'hls-live-edge': 3, 'hls-segment-attempts': 3, 'hls-segment-threads': 1, 'hls-segment-timeout': 10.0, 'hls-timeout': 60.0, 'hls-playlist-reload-attempts': 3, 'hls-start-offset': 0, 'hls-duration': None, 'http-stream-timeout': 60.0, 'ringbuffer-size': 16777216, 'rtmp-timeout': 60.0, 'rtmp-rtmpdump': is_win32 and 'rtmpdump.exe' or 'rtmpdump', 'rtmp-proxy': None, 'stream-segment-attempts': 3, 'stream-segment-threads': 1, 'stream-segment-timeout': 10.0, 'stream-timeout': 60.0, 'subprocess-errorlog': False, 'subprocess-errorlog-path': None, 'ffmpeg-ffmpeg': None, 'ffmpeg-video-transcode': 'copy', 'ffmpeg-audio-transcode': 'copy', 'locale': None, 'user-input-requester': None})
        if options:
            self.options.update(options)
        self.plugins = ALL_PLUGINS

    def close(self):
        self.http.close()

    def set_option(self, key, value):
        '''Sets general options used by plugins and streams originating
        from this session object.

        :param key: key of the option
        :param value: value to set the option to


        **Available options**:

        ======================== =========================================
        hds-live-edge            ( float) Specify the time live HDS
                                 streams will start from the edge of
                                 stream, default: ``10.0``

        hds-segment-attempts     (int) How many attempts should be done
                                 to download each HDS segment, default: ``3``

        hds-segment-threads      (int) The size of the thread pool used
                                 to download segments, default: ``1``

        hds-segment-timeout      (float) HDS segment connect and read
                                 timeout, default: ``10.0``

        hds-timeout              (float) Timeout for reading data from
                                 HDS streams, default: ``60.0``

        hls-live-edge            (int) How many segments from the end
                                 to start live streams on, default: ``3``

        hls-segment-attempts     (int) How many attempts should be done
                                 to download each HLS segment, default: ``3``

        hls-segment-threads      (int) The size of the thread pool used
                                 to download segments, default: ``1``

        hls-segment-timeout      (float) HLS segment connect and read
                                 timeout, default: ``10.0``

        hls-timeout              (float) Timeout for reading data from
                                 HLS streams, default: ``60.0``

        http-proxy               (str) Specify a HTTP proxy to use for
                                 all HTTP requests

        https-proxy              (str) Specify a HTTPS proxy to use for
                                 all HTTPS requests

        http-cookies             (dict or str) A dict or a semi-colon (;)
                                 delimited str of cookies to add to each
                                 HTTP request, e.g. ``foo=bar;baz=qux``

        http-headers             (dict or str) A dict or semi-colon (;)
                                 delimited str of headers to add to each
                                 HTTP request, e.g. ``foo=bar;baz=qux``

        http-query-params        (dict or str) A dict or a ampersand (&)
                                 delimited string of query parameters to
                                 add to each HTTP request,
                                 e.g. ``foo=bar&baz=qux``

        http-trust-env           (bool) Trust HTTP settings set in the
                                 environment, such as environment
                                 variables (HTTP_PROXY, etc) and
                                 ~/.netrc authentication

        http-ssl-verify          (bool) Verify SSL certificates,
                                 default: ``True``

        http-ssl-cert            (str or tuple) SSL certificate to use,
                                 can be either a .pem file (str) or a
                                 .crt/.key pair (tuple)

        http-timeout             (float) General timeout used by all HTTP
                                 requests except the ones covered by
                                 other options, default: ``20.0``

        http-stream-timeout      (float) Timeout for reading data from
                                 HTTP streams, default: ``60.0``

        subprocess-errorlog      (bool) Log errors from subprocesses to
                                 a file located in the temp directory

        subprocess-errorlog-path (str) Log errors from subprocesses to
                                 a specific file

        ringbuffer-size          (int) The size of the internal ring
                                 buffer used by most stream types,
                                 default: ``16777216`` (16MB)

        rtmp-proxy               (str) Specify a proxy (SOCKS) that RTMP
                                 streams will use

        rtmp-rtmpdump            (str) Specify the location of the
                                 rtmpdump executable used by RTMP streams,
                                 e.g. ``/usr/local/bin/rtmpdump``

        rtmp-timeout             (float) Timeout for reading data from
                                 RTMP streams, default: ``60.0``

        ffmpeg-ffmpeg            (str) Specify the location of the
                                 ffmpeg executable use by Muxing streams
                                 e.g. ``/usr/local/bin/ffmpeg``

        ffmpeg-verbose           (bool) Log stderr from ffmpeg to the
                                 console

        ffmpeg-verbose-path      (str) Specify the location of the
                                 ffmpeg stderr log file

        ffmpeg-video-transcode   (str) The codec to use if transcoding
                                 video when muxing with ffmpeg
                                 e.g. ``h264``

        ffmpeg-audio-transcode   (str) The codec to use if transcoding
                                 audio when muxing with ffmpeg
                                 e.g. ``aac``

        stream-segment-attempts  (int) How many attempts should be done
                                 to download each segment, default: ``3``.
                                 General option used by streams not
                                 covered by other options.

        stream-segment-threads   (int) The size of the thread pool used
                                 to download segments, default: ``1``.
                                 General option used by streams not
                                 covered by other options.

        stream-segment-timeout   (float) Segment connect and read
                                 timeout, default: ``10.0``.
                                 General option used by streams not
                                 covered by other options.

        stream-timeout           (float) Timeout for reading data from
                                 stream, default: ``60.0``.
                                 General option used by streams not
                                 covered by other options.

        locale                   (str) Locale setting, in the RFC 1766 format
                                 eg. en_US or es_ES
                                 default: ``system locale``.

        user-input-requester     (UserInputRequester) instance of UserInputRequester
                                 to collect input from the user at runtime. Must be
                                 set before the plugins are loaded.
                                 default: ``UserInputRequester``.
        ======================== =========================================

        '''
        if key == 'rtmpdump':
            key = 'rtmp-rtmpdump'
        elif key == 'rtmpdump-proxy':
            key = 'rtmp-proxy'
        elif key == 'errorlog':
            key = 'subprocess-errorlog'
        elif key == 'errorlog-path':
            key = 'subprocess-errorlog-path'
        if key == 'http-proxy':
            self.http.proxies['http'] = update_scheme('http://', value)
        elif key == 'https-proxy':
            self.http.proxies['https'] = update_scheme('https://', value)
        elif key == 'http-cookies':
            if isinstance(value, dict):
                self.http.cookies.update(value)
            else:
                self.http.parse_cookies(value)
        elif key == 'http-headers':
            if isinstance(value, dict):
                self.http.headers.update(value)
            else:
                self.http.parse_headers(value)
        elif key == 'http-query-params':
            if isinstance(value, dict):
                self.http.params.update(value)
            else:
                self.http.parse_query_params(value)
        elif key == 'http-trust-env':
            self.http.trust_env = value
        elif key == 'http-ssl-verify':
            self.http.verify = value
        elif key == 'http-disable-dh':
            if value:
                try:
                    requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += ':!DH'
                    requests.packages.urllib3.contrib.pyopenssl.DEFAULT_SSL_CIPHER_LIST = requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS.encode('ascii')
                except AttributeError:
                    pass
        elif key == 'http-ssl-cert':
            self.http.cert = value
        elif key == 'http-timeout':
            self.http.timeout = value
        else:
            self.options.set(key, value)

    def get_option(self, key):
        '''Returns current value of specified option.

        :param key: key of the option

        '''
        if key == 'rtmpdump':
            key = 'rtmp-rtmpdump'
        elif key == 'rtmpdump-proxy':
            key = 'rtmp-proxy'
        elif key == 'errorlog':
            key = 'subprocess-errorlog'
        if key == 'http-proxy':
            return self.http.proxies.get('http')
        if key == 'https-proxy':
            return self.http.proxies.get('https')
        if key == 'http-cookies':
            return self.http.cookies
        if key == 'http-headers':
            return self.http.headers
        if key == 'http-query-params':
            return self.http.params
        if key == 'http-trust-env':
            return self.http.trust_env
        if key == 'http-ssl-verify':
            return self.http.verify
        if key == 'http-ssl-cert':
            return self.http.cert
        if key == 'http-timeout':
            return self.http.timeout
        return self.options.get(key)

    def set_plugin_option(self, plugin, key, value):
        '''Sets plugin specific options used by plugins originating
        from this session object.

        :param plugin: name of the plugin
        :param key: key of the option
        :param value: value to set the option to

        '''
        if plugin in self.plugins:
            plugin = self.plugins[plugin]
            plugin.set_option(key, value)

    def get_plugin_option(self, plugin, key):
        '''Returns current value of plugin specific option.

        :param plugin: name of the plugin
        :param key: key of the option

        '''
        if plugin in self.plugins:
            plugin = self.plugins[plugin]
            return plugin.get_option(key)

    def resolve_url(self, url, follow_redirect=True):
        '''Attempts to find a plugin that can use this URL.

        The default protocol (http) will be prefixed to the URL if
        not specified.

        Raises :exc:`NoPluginError` on failure.

        :param url: a URL to match against loaded plugins
        :param follow_redirect: follow redirects

        '''
        url = update_scheme('http://', url)
        available_plugins = []
        for plugin in self.plugins.values():
            if plugin.can_handle_url(url):
                available_plugins.append(plugin)
        available_plugins.sort(key=lambda x: x.priority(url), reverse=True)
        if available_plugins:
            return available_plugins[0](self, url)
        if follow_redirect:
            try:
                res = self.http.head(url, allow_redirects=True, acceptable_status=[501])
                if res.status_code == 501:
                    res = self.http.get(url, stream=True)
                if res.url != url:
                    return self.resolve_url(res.url, follow_redirect=follow_redirect)
            except PluginError:
                pass
        raise NoPluginError(url)

    def resolve_url_no_redirect(self, url):
        '''Attempts to find a plugin that can use this URL.

        The default protocol (http) will be prefixed to the URL if
        not specified.

        Raises :exc:`NoPluginError` on failure.

        :param url: a URL to match against loaded plugins

        '''
        return self.resolve_url(url, follow_redirect=False)

    def streams(self, url, **params):
        '''Attempts to find a plugin and extract streams from the *url*.

        *params* are passed to :func:`Plugin.streams`.

        Raises :exc:`NoPluginError` if no plugin is found.
        '''
        plugin = self.resolve_url(url)
        return plugin.streams(**params)

    def get_plugins(self):
        'Returns the loaded plugins for the session.'
        return self.plugins

    @property
    def version(self):
        return __version__

    @property
    def localization(self):
        return Localization(self.get_option('locale'))

__all__ = ['Streamlink']
