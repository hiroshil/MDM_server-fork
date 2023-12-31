import io
import json
import logging
log = logging.getLogger(__name__)

class Stream(object):
    __shortname__ = 'stream'

    def __init__(self, session):
        self.session = session
        self.total_bytes = 0
        self.meta = {}
        self.priority = 0

    def __repr__(self):
        return '<Stream()>'

    def __json__(self):
        return dict(type=type(self).shortname())

    def open(self):
        '''
        Attempts to open a connection to the stream.
        Returns a file-like object that can be used to read the stream data.

        Raises :exc:`StreamError` on failure.
        '''
        raise NotImplementedError

    def setPriority(self, prio):
        self.priority = prio
        return self

    @property
    def json(self):
        obj = self.__json__()
        return json.dumps(obj)

    @classmethod
    def shortname(cls):
        return cls.__shortname__

    def to_url(self):
        raise TypeError('{0} cannot be converted to a URL'.format(self.shortname()))

class StreamIO(io.IOBase):
    pass

__all__ = ['Stream', 'StreamIO']
