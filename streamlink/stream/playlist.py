from .flvconcat import FLVTagConcatIO
from .stream import Stream
from ..exceptions import StreamError
import logging
__all__ = ['Playlist', 'FLVPlaylist']
log = logging.getLogger(__name__)

class Playlist(Stream):
    __doc__ = 'Abstract base class for playlist type streams.'
    __shortname__ = 'playlist'

    def __init__(self, session, streams, duration=None):
        Stream.__init__(self, session)
        self.streams = streams
        self.duration = duration

    def open(self):
        raise NotImplementedError

    def __json__(self):
        return dict(streams=self.streams, duration=self.duration, **Stream.__json__(self))

class FLVPlaylistIO(FLVTagConcatIO):
    __log_name__ = 'stream.flv_playlist'

    def open(self, streams):

        def generator():
            for stream in streams:
                log.debug('Opening substream: {0}', stream)
                stream.buffered = False
                try:
                    fd = stream.open()
                except StreamError as err:
                    log.error('Failed to open stream: {0}', err)
                    continue
                yield fd

        return FLVTagConcatIO.open(self, generator())

class FLVPlaylist(Playlist):
    __shortname__ = 'flv_playlist'

    def __init__(self, session, streams, duration=None, tags=None, skip_header=None, **concater_params):
        Playlist.__init__(self, session, streams, duration)
        if not tags:
            tags = []
        self.tags = tags
        self.skip_header = skip_header
        self.concater_params = concater_params

    def open(self):
        fd = FLVPlaylistIO(self.session, tags=self.tags, duration=self.duration, skip_header=self.skip_header, **self.concater_params)
        fd.open(self.streams)
        return fd

