import re
import json
import logging
from time import time
from random import choice
from base64 import b64decode
from urllib.parse import urlsplit, urljoin, parse_qsl
from streamlink.stream.http import HTTPStream
from streamlink.plugin import Plugin, PluginError
from streamlink.stream.hydrax import run_nodejs, PATCH_JS, PATCH_SoTrymConfigDefault_JS
log = logging.getLogger(__name__)
USER_AGENTS = ['Mozilla/5.0 (Linux; U; Android 6.0.1; zh-CN; F5121 Build/34.0.A.1.247) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.5.1.944 Mobile Safari/537.36', 'Mozilla/5.0 (Linux; U; Android 4.4.2; zh-CN; HUAWEI MT7-TL00 Build/HuaweiMT7-TL00) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/40.0.2214.89 UCBrowser/11.3.8.909 Mobile Safari/537.36', 'Mozilla/5.0 (Linux; U; Android 4.4.2; en-US; HM NOTE 1W Build/KOT49H) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.0.5.850 U3/0.8.0 Mobile Safari/534.30', 'Mozilla/5.0 (X11; U; Linux i686; en-US) U2/1.0.0 UCBrowser/9.3.1.344', 'Mozilla/5.0 (Linux; U; Android 5.0.2; en-US; SM-A500F Build/LRX22G) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/10.9.0.731 U3/0.8.0 Mobile Safari/E7FBAF', 'Mozilla/5.0 (Linux; U; Android 6.0; ru-RU; SM-J320R4 Build/MMB29K) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/11.3.0.950 U3/0.8.0 Mobile Safari/E7FBAF', 'Mozilla/5.0 (Linux; U; Android 4.4.2; id; SM-G900 Build/KOT49H) AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 UCBrowser/9.9.2.467 U3/0.8.0 Mobile Safari/534.30', 'Mozilla/5.0 (S60V5; U; en-us; Nokia5250)/UC Browser8.2.0.132/50/355/UCWEB Mobile', 'Mozilla/5.0 (Windows; U; Windows NT 5.2; en-US) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/40.0.2214.89 Safari/537.36 UCBrowser/11.3.5.908', 'Mozilla/5.0 (Linux; U; Android 4.1.1; zh-CN; GT-N7100 Build/JRO03C) AppleWebKit/534.31 (KHTML, like Gecko) UCBrowser/9.3.0.321 U3/0.8.0 Mobile Safari/534.31', 'Mozilla/5.0 (Linux; U; Android 12; en-US; CPH2341 Build/SKQ1.211209.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.4.0.1306 Mobile Safari/537.36', 'Mozilla/5.0 (Linux; U; Android 11; zh-CN; M2104K10AC Build/RP1A.200720.011) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/15.1.8.1208 Mobile Safari/537.36', 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.155 UBrowser/5.4.4237.1032 Safari/537.36', 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/55.0.2883.87 UBrowser/6.2.4094.1 Safari/537.36', 'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 UBrowser/7.0.6.1042 Safari/537.36', 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/44.0.2403.157 UBrowser/5.5.7045.1004 Safari/537.36']

def fixScheme(url):
    offset = url.find('https:/')
    if offset > -1 and url[offset + 8] != '/':
        url = 'https://' + url[offset + 7:]
    return url

class HydraxDirect(Plugin):
    __doc__ = 'docstring for Hydrax'
    qualities = {'fullhd': '1080p', 'hd': '720p', 'mhd': '480p', 'sd': '360p'}
    qualities_map_url_tpl = {'fullhd': 'https://whw%s#timestamp=%s', 'hd': 'https://www%s#timestamp=%s', 'mhd': 'https://%s#timestamp=%s', 'sd': 'https://%s#timestamp=%s', 'origin': 'https://%s#timestamp=%s'}
    _url_re = re.compile('(?x)https://(?:geoip.redirect-ads.com|freeplayervideo.com|playhydrax.com|player-cdn.com|abysscdn.com)/\\?v=([^&]+)&?')
    re_filter_script = re.compile('<script src="([^=]+/js/[a-z\\d]+.js)"></script>')
    re_script_content = re.compile('<script>([\\s\\S]+)</script>')
    re_config = re.compile('PLAYER\\(atob\\(["]+([^"]+)["]+')
    re_SoTrymConfigDefault = re.compile('window.SoTrymConfigDefault\\s*=\\s*({.*?});')

    def getResultFromNode(self, input_data):
        NODE_JS = self.session.get_option('node-nodejs')
        result = None
        try:
            result = run_nodejs(NODE_JS, input_data.encode('utf8'))
            log.debug('result raw {}', result)
            result = json.loads(result)
        except Exception as err:
            log.debug('Falied load result from nodejs: ', err)
        return result

    def getConfigFromFileJs(self, base_url, scripts_src):
        scripts_src.reverse()
        u = urlsplit(base_url)
        headers = {'Referer': '%s://%s/' % (u.scheme, u.netloc), 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'no-cors', 'Sec-Fetch-Dest': 'script'}
        urls_loaded = []
        config_save = None
        for script_src in scripts_src:
            full_src = urljoin(base_url, script_src)
            js_code = self.session.http.get(full_src, headers=headers).text
            if 'detectAdBlock' in js_code:
                urls_loaded.append(full_src)
                config = self.getResultFromNode(PATCH_JS + js_code)
                if isinstance(config, dict):
                    if config.get('sources', False):
                        return config
                    config_save = config
                    break
        if config_save is not None:
            for script_src in scripts_src:
                full_src = urljoin(base_url, script_src)
                if full_src in urls_loaded:
                    continue
                js_code = self.session.http.get(full_src, headers=headers).text
                SoTrymConfigDefault = self.getResultFromNode(PATCH_SoTrymConfigDefault_JS + js_code)
                if isinstance(SoTrymConfigDefault, dict):
                    sources = list(SoTrymConfigDefault.keys())
                    sources.remove('pieceLength')
                    if sources:
                        config_save['sources'] = sources
                        return config_save
        raise PluginError('Cannot parse config data from js file')

    def getConfigFromScriptTagContent(self, content):
        m = self.re_config.search(content)
        if not m:
            raise PluginError('Cannot parse Player data')
        config = json.loads(b64decode(m.group(1)).decode('utf8'))
        if not isinstance(config, dict):
            raise PluginError('Player data not type dict')
        if config.get('sources', False):
            return config
        m = self.re_SoTrymConfigDefault.search(content)
        if not m:
            raise PluginError('Cannot parse SoTrymConfigDefault data')
        SoTrymConfigDefault = json.loads(m.group(1))
        if not isinstance(SoTrymConfigDefault, dict):
            raise PluginError('SoTrymConfigDefault data not type dict')
        sources = list(SoTrymConfigDefault.keys())
        sources.remove('pieceLength')
        if sources:
            config['sources'] = sources
            return config
        raise PluginError('Hydrax sources is not found')

    def getConfig(self, url):
        NODE_JS = self.session.get_option('node-nodejs')
        if not NODE_JS:
            raise PluginError('Node js not found')
        if self.session.http.headers.get('Referer', None):
            headers = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe'}
        else:
            headers = {}
        html = self.session.http.get(url, headers=headers).text
        scripts_src = self.re_filter_script.findall(html)
        if scripts_src:
            return self.getConfigFromFileJs(r.url, scripts_src)
        m = self.re_script_content.search(html)
        if m:
            return self.getConfigFromScriptTagContent(m.group(1))
        raise PluginError('Hydrax config is not found')

    def getSubTitle(self):
        u = urlsplit(self.url)
        query = dict(parse_qsl(u.query))
        if query.get('sub', None):
            self.subtitles_streams[query.get('lang', 'Vie')] = HTTPStream(self.session, fixScheme(query['sub']))

    def _get_streams(self):
        self.session.http.headers['User-Agent'] = choice(USER_AGENTS)
        self.session.http.headers.pop('Origin', None)
        self.getSubTitle()
        streams = []
        config = self.session.get_option('hydrax_config')
        if not config:
            config = self.getConfig(self.url)
        if not config:
            return streams
        config['domain_more'].insert(0, config['domain'])
        subdomains = []
        for domain in config['domain_more']:
            subdomain = '%s.%s' % (config['id'], domain)
            subdomains.append(subdomain)
        for subdomain in subdomains:
            for source in config['sources']:
                source = source.lower()
                source_type = self.qualities.get(source, source)
                url_tlp = self.qualities_map_url_tpl.get(source, None)
                if url_tlp is not None:
                    url = url_tlp % (subdomain, int(time()*1000))
                    stream = HTTPStream(self.session, url, headers={'Referer': 'https://player-cdn.com/', 'Range': 'bytes=0-'}, retries=3, retry_max_backoff=15)
                    stream.setPriority(-1000)
                    streams.append([source_type, stream])
        return streams

__plugin__ = HydraxDirect
