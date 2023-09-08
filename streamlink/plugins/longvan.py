import re
import logging
from urllib.parse import urlparse, parse_qsl
from streamlink.plugin import Plugin
from streamlink.stream.http import HTTPStream
from streamlink.stream.ProxyImgHls import ProxyImg_HLSStream
log = logging.getLogger(__name__)

class LongVan(Plugin):
    sub_lang_map = {'Tiếng Việt': 'VI', 'English': 'EN'}
    _url_re = re.compile('https://(?:loadbalance.manga123.net|jimmiepradeep.xyz|vod.bongngo.cloud|loading.bongngo.bar|vod.streamcherry.biz)/public/dist/|(?:index|hls|stream).html.*')
    _parse_sub_domain_re = re.compile('window.domainSub\\s?=\\s?"([^"]+)";')

    def get_subtitles(self, domain, vlsub):
        r = self.session.http.get('%s/getSubObj?name=%s' % (domain, vlsub))
        files = r.json()
        for file_info in files:
            self.subtitles_streams[file_info['label']] = HTTPStream(self.session, file_info['file'])

    def _get_streams(self):
        u_parse = urlparse(self.url)
        u_query = dict(parse_qsl(u_parse.query))
        r = self.session.http.get(self.url)
        m = self._parse_sub_domain_re.search(r.text)
        if u_query.get('vlsub') and m:
            self.get_subtitles(m.group(1), u_query['vlsub'])
        elif u_query.get('sub'):
            self.subtitles_streams['Tiếng Việt'] = HTTPStream(self.session, u_query['sub'])
        hls_id = u_query['id']
        url_hls = '%s://%s/playlist/%s/playlist.m3u8' % (u_parse.scheme, u_parse.netloc, hls_id)
        self.logger.debug('URL={0}', url_hls)
        self.session.http.headers.update({'Accept': '*/*', 'DNT': '1', 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe', 'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8'})
        streams = ProxyImg_HLSStream.parse_variant_playlist(self.session, url_hls, headers={'Origin': '%s://%s' % (u_parse.scheme, u_parse.netloc), 'Referer': ''})
        return streams

__plugin__ = LongVan
