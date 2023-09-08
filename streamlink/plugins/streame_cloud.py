import re
from streamlink.plugin import Plugin
from streamlink.stream.hls import HLSStream, MuxedHLSStream, HLSStreamWriter, HLSStreamReader
from streamlink.exceptions import PluginError, StreamError

class StreamCloudMuxedHLSStream(MuxedHLSStream):
    toMp4 = True

class StreamCloudWriter(HLSStreamWriter):
    __doc__ = 'docstring for Stream'
    http_headers = {'Origin': 'https://streame.cloud'}

    def create_request_params(self, sequence):
        request_params = super().create_request_params(sequence)
        request_params['headers'] = request_params['headers'].copy()
        request_params['headers'].update(self.http_headers)
        return request_params

class StreamCloudReader(HLSStreamReader):
    __doc__ = 'docstring for StreamCloudReader'
    __writer__ = StreamCloudWriter

class StreamCloudHLSSTream(HLSStream):
    __doc__ = 'docstring for StreamCloudHLSSTream'
    stream_reader = StreamCloudReader
    muxed_hls = StreamCloudMuxedHLSStream
    toMp4 = True

class StreamCloud(Plugin):
    _url_re = re.compile('https://streame.cloud/v1/video')
    _meta = re.compile('<meta name="([^"]+)" content="([^"]+)"')

    def _get_streams(self):
        html = self.session.http.get(self.url).text
        metas = self._meta.findall(html)
        if not metas:
            raise PluginError('meta tag not found')
        metas = dict(metas)
        if not metas.get('streamid'):
            raise PluginError('streamid not found')
        if not metas.get('playtoken'):
            raise PluginError('playtoken not found')
        hls = 'https://streame.cloud/v1/video/manifest/%s/' % metas['streamid']
        headers = {'Authorization': metas['playtoken']}
        self.session.http.headers.pop('Referer', None)
        return StreamCloudHLSSTream.parse_variant_playlist(self.session, hls, headers=headers)

__plugin__ = StreamCloud
