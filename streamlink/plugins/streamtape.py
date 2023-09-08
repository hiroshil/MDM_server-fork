import re
import logging
from streamlink.stream.http import HTTPStream
from streamlink.utils import update_scheme
from streamlink.plugin import Plugin
log = logging.getLogger(__name__)

class StreamtapePlugin(Plugin):
    _url_re = re.compile('https://streamtape\\.com/(?:e|v)/([0-9a-zA-Z]+)')
    _find_src_video = re.compile('\\).innerHTML\\s*=\\s*([^;]+);')
    _replace_substring = re.compile('.substring\\((\\d+)\\)')

    def _get_streams(self):
        streams = []
        r = self.session.http.get(self.url)
        srcs = self._find_src_video.findall(r.text)
        for src in reversed(srcs):
            try:
                src = eval(self._replace_substring.sub('[\\1:]', src))
                url = src + '&stream=1'
                if url[0] == '/' and url[1] != '/':
                    url = 'https:/' + url
                else:
                    url = update_scheme('https://', url)
                streams.append(('720p', HTTPStream(self.session, url, headers={'Origin': 'https://streamtape.com', 'Referer': 'https://streamtape.com/'})))
                break
            except:
                continue
        return streams

__plugin__ = StreamtapePlugin
