import re
import logging
from streamlink.stream.http import HTTPStream
from streamlink.utils import jsunpack, update_scheme
from streamlink.plugin import Plugin
log = logging.getLogger(__name__)

class MixDropPlugin(Plugin):
    _url_re = re.compile('https://mixdrop.co/(?:f|e)/(\\w+)')
    _re_find_url_video = re.compile('MDCore\\.\\w+="([^"]+)')

    def _get_streams(self):
        streams = []
        headers = {'Referer': 'https://mixdrop.co/', 'Origin': 'https://mixdrop.co'}
        html = self.session.http.get(self.url, headers=headers).text
        jspack = jsunpack.extract(html)
        if jspack:
            jsplain = jsunpack.unpack(jspack)
            urls = self._re_find_url_video.findall(jsplain)
            for url in urls:
                if url.startswith('//') and not url.endswith('.jpg'):
                    url = update_scheme('https://', url)
                    log.debug('url {}', url)
                    streams.append(('720p', HTTPStream(self.session, url, headers=headers, max_workers=2)))
                    break
        return streams

__plugin__ = MixDropPlugin
