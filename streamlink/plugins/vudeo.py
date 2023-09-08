import re
import logging
from streamlink.stream.http import HTTPStream
from streamlink.plugin import Plugin
from streamlink.utils import jsonLoads
log = logging.getLogger(__name__)

class VudeoPlugin(Plugin):
    _url_re = re.compile('(?x)https://vudeo.net/embed*')
    _sources = re.compile('sources:\\s*(\\[[^\\]]+\\])')

    def _get_streams(self):
        streams = []
        html = self.session.http.get(self.url).text
        m = self._sources.search(html)
        if m:
            sources = jsonLoads(m.group(1))
            for source in sources:
                if source.endswith('mp4'):
                    streams.append(('720p', HTTPStream(self.session, source, headers={'Referer': 'https://vudeo.net/'})))
        return streams

__plugin__ = VudeoPlugin
