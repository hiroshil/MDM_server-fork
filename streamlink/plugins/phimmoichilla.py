import re
import logging
from urllib.parse import urljoin
from streamlink.stream.ProxyImgHls import ProxyImg_HLSStream
from streamlink.exceptions import PluginError
from streamlink.stream.http import HTTPStream
from streamlink.plugin import Plugin
log = logging.getLogger(__name__)
STREAM_SYNONYMS = ['best', 'worst', 'best-unfiltered', 'worst-unfiltered']

class PhimChill(Plugin):
    _api = 'https://phimmoichilla.net/chillsplayer.php'
    _url_re = re.compile('(?x)https://phimmoichilla.net/xem/.*')
    _episodeID = re.compile('chillplay\\("(\\d+)"\\);')
    _videoID = re.compile('iniPlayers\\("([\\d\\w]{32})"')
    _url_video = re.compile('initPlayer\\("(.*?)"\\)')
    _servers_video = re.compile('<a.*?data-index="(\\d+)"')
    _video_path_template = 'https://so-trym.topphimmoi.org/raw/%s/index.m3u8'
    _iframe_re = re.compile('<iframe.*?src="([^"]+)"')
    _location_href = re.compile('location.href="([^"]+)"')
    _Zembed_player_src = re.compile('playlist:\\s*\\[{.*?source.*?file":\\s*"([^"]+)"', re.DOTALL)
    recursive = False

    @classmethod
    def can_handle_url(cls, url):
        return cls._url_re.match(url) is not None

    def handleZembed(self, iframe_src):
        r = self.session.http.get(iframe_src)
        m = self._location_href.search(r.text)
        if m:
            location_href = m.group(1)
            r = self.session.http.get(location_href)
            m = self._Zembed_player_src.search(r.text)
            if m:
                file_src = m.group(1)
                if not file_src.startswith('http'):
                    file_src = urljoin(r.url, file_src)
                    r = self.session.http.head(file_src, allow_redirects=True, raise_for_status=False)
                    file_src = r.url
                if 'cdninstagram' in file_src:
                    return ('720p', HTTPStream(self.session, file_src, headers={'Range': 'bytes=0-', 'Referer': self.url}).setPriority(9999))

    def _get_streams(self):
        streams = []
        html = self.session.http.get(self.url).text
        m = self._episodeID.search(html)
        if not m:
            raise PluginError('EpisodeID not found')
        episodeID = m.group(1)
        servers_video = self._servers_video.findall(html)
        iframes_src = []
        url_videos = []
        for server_video in servers_video:
            html = self.session.http.post(self._api, data={'qcao': episodeID, 'sv': server_video}).text
            m = self._videoID.search(html)
            if m:
                url_hls = self._video_path_template % m.group(1)
                if url_hls in url_videos:
                    continue
                url_videos.append(url_hls)
                streams.append(('720p', ProxyImg_HLSStream(self.session, url_hls).setToMp4(False)))
            else:
                m = self._url_video.search(html)
                if m:
                    url_video = m.group(1)
                    if url_video in url_videos:
                        continue
                    url_videos.append(url_video)
                    if url_video.endswith('.m3u8'):
                        streams.append(('720p', ProxyImg_HLSStream(self.session, url_video).setToMp4(False)))
                    else:
                        m = self._iframe_re.search(html)
                        if m:
                            iframe_src = m.group(1)
                            if iframe_src in iframes_src:
                                continue
                            iframes_src.append(iframe_src)
                            log.debug('iframe_src %s' % iframe_src)
                            if 'zembed.net' in iframe_src:
                                _stream = self.handleZembed(iframe_src)
                                if _stream:
                                    streams.append(_stream)
                                    other_streams = self.streams_from_other_plugins(iframe_src)
                                    if other_streams:
                                        streams.extend(other_streams)
                            else:
                                other_streams = self.streams_from_other_plugins(iframe_src)
                                if other_streams:
                                    streams.extend(other_streams)
                else:
                    m = self._iframe_re.search(html)
                    if m:
                        iframe_src = m.group(1)
                        if iframe_src in iframes_src:
                            continue
                        iframes_src.append(iframe_src)
                        log.debug('iframe_src %s' % iframe_src)
                        if 'zembed.net' in iframe_src:
                            _stream = self.handleZembed(iframe_src)
                            if _stream:
                                streams.append(_stream)
                                other_streams = self.streams_from_other_plugins(iframe_src)
                                if other_streams:
                                    streams.extend(other_streams)
                        else:
                            other_streams = self.streams_from_other_plugins(iframe_src)
                            if other_streams:
                                streams.extend(other_streams)
        return streams

__plugin__ = PhimChill
