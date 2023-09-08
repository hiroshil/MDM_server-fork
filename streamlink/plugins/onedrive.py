import logging
import re
from streamlink.plugin import Plugin
from streamlink.plugin.plugin import stream_weight
from streamlink.plugin.plugin import LOW_PRIORITY, NORMAL_PRIORITY, NO_PRIORITY
from streamlink.stream.dash import DASHStream
from streamlink.compat import urlparse
log = logging.getLogger(__name__)

class OneDrive(Plugin):
    _url_re = re.compile('https://[^\\/]+\\.svc\\.ms/transform/videomanifest/*')

    def _get_streams(self):
        return DASHStream.parse_manifest(self.session, self.url, retry_backoff=2.0, retry_max_backoff=30.0)

__plugin__ = OneDrive
