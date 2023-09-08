import re
import logging
from streamlink.exceptions import PluginError
from streamlink.plugin import Plugin
from streamlink.stream import HTTPStream
from streamlink.utils import urlparse, parse_qsl
log = logging.getLogger(__name__)

class Fembed(Plugin):
    __doc__ = 'docstring for Fembed'
    _url_re = re.compile('https://(?:femax\\d+.com/v|fembed.anhdaubo.net/embedplay/|dutrag.com/v)')
    _parse_fembed_v_re = re.compile("fe\\s?=\\s?'([^']+)';")
    _parse_array_url = re.compile('var array\\s*=\\s*\\[([^\\[\\]]+)\\]')

    def get_streams_for_each_url(self, url):
        streams = {}
        r = self.session.http.get(url)
        new_url = r.url
        u_parse = urlparse(new_url)
        ID = u_parse.path.split('/v/').pop().split('/')[0]
        r = self.session.http.post('%s://%s/api/source/%s' % (u_parse.scheme, u_parse.hostname, ID), data={'r': url, 'd': u_parse.hostname})
        res = r.json()
        if not res.get('success', False):
            return streams
        for file_info in res.get('data', []):
            if file_info['type'] == 'mp4':
                streams[file_info['label']] = HTTPStream(self.session, file_info['file'])
        return streams

    def _get_streams(self):
        streams = []
        urls = []
        if 'embedplay' in self.url:
            r = self.session.http.get(self.url)
            m = self._parse_fembed_v_re.search(r.text)
            if m:
                urls.append(m.group(1))
            else:
                m = self._parse_array_url.search(r.text)
                if m:
                    for item in m.group(1).split('&#34;'):
                        if item.startswith('http'):
                            urls.append(item)
        else:
            urls.append(self.url)
        if not urls:
            raise PluginError('url embed not found')
        log.debug('urls %s' % urls)
        for url in urls:
            for (stream_name, stream) in self.get_streams_for_each_url(url).items():
                streams.append((stream_name, stream))
        return streams

__plugin__ = Fembed
