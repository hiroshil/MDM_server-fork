
class StreamlinkError(Exception):
    __doc__ = """Any error caused by Streamlink will be caught
       with this exception."""

class PluginError(StreamlinkError):
    __doc__ = 'Plugin related error.'

class FatalPluginError(PluginError):
    __doc__ = """
    Plugin related error that cannot be recovered from

    Plugin's should use this Exception when errors that can
    never be recovered from are encountered. For example, when
    a user's input is required an none can be given.
    """

class NoStreamsError(StreamlinkError):

    def __init__(self, url):
        err = 'No streams found on this URL: {0}'.format(url)
        super().__init__(err)

class NoPluginError(PluginError):
    __doc__ = 'No relevant plugin has been loaded.'

    def __init__(self, url):
        err = 'No plugin can handle URL %s' % url
        super().__init__(err)

class StreamError(StreamlinkError):
    __doc__ = 'Stream related error.'

class TooManySegmentsError(StreamlinkError):

    def __init__(self):
        super().__init__('Too many segments error')

class TooManySegmentUnableHandle(StreamlinkError):

    def __init__(self):
        super().__init__('Too many segments unable handle')

__all__ = ['StreamlinkError', 'PluginError', 'NoPluginError', 'NoStreamsError', 'StreamError']
