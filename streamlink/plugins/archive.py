import re
import logging
from urllib.parse import urljoin
from streamlink.utils import jsonLoads
from streamlink.plugin import Plugin
from streamlink.stream.http import HTTPStream
log = logging.getLogger(__name__)

class Archive(Plugin):
    _url_re = re.compile('(?x)https://archive.org/embed/*')
    _sources = re.compile('sources":\\s*(\\[[^\\]]+\\])')

    def _get_streams(self):
        streams = []
        r = self.session.http.get(self.url)
        m_sources = self._sources.search(r.text)
        if m_sources:
            sources = jsonLoads(m_sources.group(1))
            for source in sources:
                if source.get('type', '') == 'mp4':
                    file = source['file']
                    if not file.startswith('http'):
                        file = urljoin(self.url, file)
                    streams.append((source['label'], HTTPStream(self.session, file)))
        return streams

__plugin__ = Archive
