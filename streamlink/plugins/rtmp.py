import re
from streamlink.plugin import Plugin
from streamlink.plugin.plugin import parse_url_params
from streamlink.stream import RTMPStream

class RTMPPlugin(Plugin):
    _url_re = re.compile('rtmp(?:e|s|t|te)?://.+')

    def _get_streams(self):
        (url, params) = parse_url_params(self.url)
        params['rtmp'] = url
        for boolkey in ('live', 'realtime', 'quiet', 'verbose', 'debug'):
            if boolkey in params:
                params[boolkey] = bool(params[boolkey])
        self.logger.debug('params={0}', params)
        return {'live': RTMPStream(self.session, params)}

__plugin__ = RTMPPlugin
