import re
from streamlink.plugin import Plugin
from streamlink.exceptions import PluginError

class ShortLink(Plugin):
    _url_re = re.compile('(?x)https://short.(?:ink|icu)/*')

    @classmethod
    def can_handle_url(cls, url):
        return cls._url_re.match(url) is not None

    def _get_streams(self):
        headers = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe'}
        r = self.session.http.get(self.url, headers=headers)
        if self.url != r.url:
            return self.streams_from_other_plugins(r.url)
        raise PluginError('ShortLink redirect failed')

__plugin__ = ShortLink
