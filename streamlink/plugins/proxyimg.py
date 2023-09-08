import re
import logging
from urllib.parse import urlparse, parse_qsl
from streamlink.plugin import Plugin
from streamlink.stream.http import HTTPStream
from streamlink.stream.ProxyImgHls import ProxyImg_HLSStream
log = logging.getLogger(__name__)

class ProxyImg(Plugin):
    sub_lang_map = {'Tiếng Việt': 'VI', 'English': 'EN'}
    subtitle_url = 'https://subtiles.0apis.xyz/getSubObj?name='
    _url_re = re.compile('https://oneonlinegamesnow.biz/public/index.html.*')

    def get_subtitles(self, oksub):
        r = self.session.http.get('%s%s' % (self.subtitle_url, oksub))
        files = r.json()
        for file_info in files:
            self.subtitles_streams[file_info['label']] = HTTPStream(self.session, file_info['file'])

    def _get_streams(self):
        u_parse = urlparse(self.url)
        u_query = dict(parse_qsl(u_parse.query))
        if u_query.get('oksub'):
            self.get_subtitles(u_query['oksub'])
        elif u_query.get('sub'):
            self.subtitles_streams['Tiếng Việt'] = HTTPStream(self.session, u_query['sub'])
        hls_id = u_query['id']
        url_hls = '%s://%s/playlist/%s/playlist.m3u8' % (u_parse.scheme, u_parse.netloc, hls_id)
        self.logger.debug('URL={0}', url_hls)
        self.session.http.headers.update({'Accept': '*/*', 'DNT': '1', 'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe', 'X-Requested-With': 'XMLHttpRequest', 'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8'})
        streams = ProxyImg_HLSStream.parse_variant_playlist(self.session, url_hls, headers={'Origin': '%s://%s' % (u_parse.scheme, u_parse.netloc), 'Referer': ''})
        return streams

__plugin__ = ProxyImg
