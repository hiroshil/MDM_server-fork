import re
import logging
import string
import binascii
import random
from urllib.parse import urlparse
from streamlink.plugin import Plugin
from streamlink.stream.hls import HLSStream
log = logging.getLogger(__name__)

class StreamSB(Plugin):
    _url_re = re.compile('(?x)https://(?:sbembed.com|sbembed1.com|sbplay.org|sbvideo.net|streamsb.net|sbplay.one|cloudemb.com|playersb.com|tubesb.com|sbplay1.com|embedsb.com|watchsb.com|sbplay2.com|japopav.tv|viewsb.com|sbplay2.xyz|sbfast.com|sbfull.com|javplaya.com)/(?:embed-|e/|play/|d/|sup/)?([0-9a-zA-Z]+)')

    @classmethod
    def can_handle_url(cls, url):
        return cls._url_re.match(url) is not None

    def get_embedurl(self, host, media_id):

        def makeid(length):
            t = string.ascii_letters + string.digits
            return ''.join([random.choice(t) for _ in range(length)])

        x = '{0}||{1}||{2}||streamsb'.format(makeid(12), media_id, makeid(12))
        c1 = binascii.hexlify(x.encode('utf8')).decode('utf8')
        x = '{0}||{1}||{2}||streamsb'.format(makeid(12), makeid(12), makeid(12))
        c2 = binascii.hexlify(x.encode('utf8')).decode('utf8')
        x = '{0}||{1}||{2}||streamsb'.format(makeid(12), c2, makeid(12))
        c3 = binascii.hexlify(x.encode('utf8')).decode('utf8')
        return 'https://{0}/sources50/{1}/{2}'.format(host, c1, c3)

    def _get_streams(self):
        u = urlparse(self.url)
        url = self.get_embedurl(u.netloc, self._url_re.match(self.url).group(1))
        r = self.session.http.get(url, headers={'Referer': self.url, 'watchsb': 'sbstream'})
        data = r.json().get('stream_data')
        hls = data.get('file') or data.get('backup')
        return HLSStream.parse_variant_playlist(self.session, hls)

__plugin__ = StreamSB
