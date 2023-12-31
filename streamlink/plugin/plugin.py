import ast
import re
import logging
import operator
from functools import partial
from collections import OrderedDict
from streamlink.exceptions import PluginError, NoStreamsError, NoPluginError
from streamlink.options import Options
log = logging.getLogger(__name__)
BIT_RATE_WEIGHT_RATIO = 2.8
ALT_WEIGHT_MOD = 0.01
QUALITY_WEIGTHS_EXTRA = {'other': {'live': 1080}, 'tv': {'hd': 1080, 'sd': 576}, 'quality': {'ehq': 720, 'hq': 576, 'sq': 360}}
FILTER_OPERATORS = {'<': operator.lt, '<=': operator.le, '>': operator.gt, '>=': operator.ge}
PARAMS_REGEX = '(\\w+)=({.+?}|\\[.+?\\]|\\(.+?\\)|\'(?:[^\'\\\\]|\\\\\')*\'|\\"(?:[^\\"\\\\]|\\\\\\")*\\"|\\S+)'
STREAM_SYNONYMS = ['best', 'worst', 'best-unfiltered', 'worst-unfiltered']
HIGH_PRIORITY = 30
NORMAL_PRIORITY = 20
LOW_PRIORITY = 10
NO_PRIORITY = 0

def stream_weight(stream):
    for (group, weights) in QUALITY_WEIGTHS_EXTRA.items():
        if stream in weights:
            return (weights[stream], group)
    match = re.match('^(\\d+)(k|p)?(\\d+)?(\\+)?(?:[a_](\\d+)k)?(?:_(alt)(\\d)?)?$', stream)
    if match:
        weight = 0
        if match.group(6):
            if match.group(7):
                weight -= ALT_WEIGHT_MOD*int(match.group(7))
            else:
                weight -= ALT_WEIGHT_MOD
        name_type = match.group(2)
        if name_type == 'k':
            bitrate = int(match.group(1))
            weight += bitrate/BIT_RATE_WEIGHT_RATIO
            return (weight, 'bitrate')
        elif name_type == 'p':
            weight += int(match.group(1))
            if match.group(3):
                weight += int(match.group(3))
            if match.group(4) == '+':
                weight += 1
            if match.group(5):
                weight += int(match.group(5))/BIT_RATE_WEIGHT_RATIO
            return (weight, 'pixels')
    return (0, 'none')

def iterate_streams(streams):
    for (name, stream) in streams:
        if isinstance(stream, list):
            for sub_stream in stream:
                yield (name, sub_stream)
        else:
            yield (name, stream)

def stream_type_priority(stream_types, stream):
    stream_type = type(stream[1]).shortname()
    try:
        prio = stream_types.index(stream_type) - getattr(stream[1], 'priority', 0)
    except ValueError:
        try:
            prio = stream_types.index('*')
        except ValueError:
            prio = 99
    return prio

def stream_sorting_filter(expr, stream_weight):
    match = re.match('(?P<op><=|>=|<|>)?(?P<value>[\\w+]+)', expr)
    if not match:
        raise PluginError('Invalid filter expression: {0}'.format(expr))
    (op, value) = match.group('op', 'value')
    op = FILTER_OPERATORS.get(op, operator.eq)
    (filter_weight, filter_group) = stream_weight(value)

    def func(quality):
        (weight, group) = stream_weight(quality)
        if group == filter_group:
            return not op(weight, filter_weight)
        return True

    return func

def parse_url_params(url):
    split = url.split(' ', 1)
    url = split[0]
    params = split[1] if len(split) > 1 else ''
    return (url, parse_params(params))

def parse_params(params):
    rval = {}
    matches = re.findall(PARAMS_REGEX, params)
    for (key, value) in matches:
        try:
            value = ast.literal_eval(value)
        except Exception:
            pass
        rval[key] = value
    return rval

class Plugin(object):
    __doc__ = """A plugin can retrieve stream information from the URL specified.

    :param url: URL that the plugin will operate on
    """
    options = Options()

    def __init__(self, session, url):
        self.session = session
        self.logger = logging.getLogger('streamlink.plugins.%s' % self.__class__.__name__)
        self.url = url
        self.subtitles_streams = {}

    def subtitles(self):
        return self.subtitles_streams

    @classmethod
    def can_handle_url(cls, url):
        if getattr(cls, '_url_re', False):
            return cls._url_re.match(url) is not None
        return False

    @classmethod
    def set_option(cls, key, value):
        cls.options.set(key, value)

    @classmethod
    def get_option(cls, key):
        return cls.options.get(key)

    @classmethod
    def stream_weight(cls, stream):
        return stream_weight(stream)

    @classmethod
    def default_stream_types(cls, streams):
        stream_types = ['rtmp', 'hls', 'hds', 'http']
        for (_, stream) in iterate_streams(streams):
            stream_type = type(stream).shortname()
            if stream_type not in stream_types:
                stream_types.append(stream_type)
        return stream_types

    @classmethod
    def priority(cls, url):
        '''
        Return the plugin priority for a given URL, by default it returns
        NORMAL priority.
        :return: priority level
        '''
        return NORMAL_PRIORITY

    def streams(self, stream_types=None, sorting_excludes=None):
        '''Attempts to extract available streams.

        Returns a :class:`dict` containing the streams, where the key is
        the name of the stream, most commonly the quality and the value
        is a :class:`Stream` object.

        The result can contain the synonyms **best** and **worst** which
        points to the streams which are likely to be of highest and
        lowest quality respectively.

        If multiple streams with the same name are found, the order of
        streams specified in *stream_types* will determine which stream
        gets to keep the name while the rest will be renamed to
        "<name>_<stream type>".

        The synonyms can be fine tuned with the *sorting_excludes*
        parameter. This can be either of these types:

            - A list of filter expressions in the format
              *[operator]<value>*. For example the filter ">480p" will
              exclude streams ranked higher than "480p" from the list
              used in the synonyms ranking. Valid operators are >, >=, <
              and <=. If no operator is specified then equality will be
              tested.

            - A function that is passed to filter() with a list of
              stream names as input.


        :param stream_types: A list of stream types to return.
        :param sorting_excludes: Specify which streams to exclude from
                                 the best/worst synonyms.

        '''
        try:
            ostreams = self._get_streams()
            if isinstance(ostreams, dict):
                ostreams = ostreams.items()
            if ostreams:
                ostreams = list(ostreams)
        except NoStreamsError:
            return {}
        except (IOError, OSError, ValueError) as err:
            raise PluginError(err)
        if not ostreams:
            return {}
        if stream_types is None:
            stream_types = self.default_stream_types(ostreams)
        sorted_streams = sorted(iterate_streams(ostreams), key=partial(stream_type_priority, stream_types))
        streams = {}
        for (name, stream) in sorted_streams:
            stream_type = type(stream).shortname()
            if '*' not in stream_types and stream_type not in stream_types:
                continue
            if name.endswith('_alt'):
                name = name[:-len('_alt')]
            existing = streams.get(name)
            if existing:
                existing_stream_type = type(existing).shortname()
                if existing_stream_type != stream_type:
                    name = '{0}_{1}'.format(name, stream_type)
                if name in streams:
                    name = '{0}_alt'.format(name)
                    num_alts = len(list(filter(lambda n: n.startswith(name), streams.keys())))
                    if num_alts > 0:
                        name = '{0}{1}'.format(name, num_alts + 1)
            match = re.match('([A-z0-9_+]+)', name)
            if match:
                name = match.group(1)
            else:
                self.logger.debug("The stream '{0}' has been ignored since it is badly named.", name)
            streams[name.lower()] = stream

        def stream_weight_only(s):
            return (self.stream_weight(s)[0] or len(streams) == 1 and 1) + getattr(streams[s], 'priority', 0)

        stream_names = filter(stream_weight_only, streams.keys())
        sorted_streams = sorted(stream_names, key=stream_weight_only)
        unfiltered_sorted_streams = sorted_streams
        if isinstance(sorting_excludes, list):
            for expr in sorting_excludes:
                filter_func = stream_sorting_filter(expr, self.stream_weight)
                sorted_streams = list(filter(filter_func, sorted_streams))
        elif callable(sorting_excludes):
            sorted_streams = list(filter(sorting_excludes, sorted_streams))
        final_sorted_streams = OrderedDict()
        for stream_name in sorted(streams, key=stream_weight_only):
            final_sorted_streams[stream_name] = streams[stream_name]
        if len(sorted_streams) > 0:
            best = sorted_streams[-1]
            worst = sorted_streams[0]
            final_sorted_streams['worst'] = streams[worst]
            final_sorted_streams['best'] = streams[best]
        elif len(unfiltered_sorted_streams) > 0:
            best = unfiltered_sorted_streams[-1]
            worst = unfiltered_sorted_streams[0]
            final_sorted_streams['worst-unfiltered'] = streams[worst]
            final_sorted_streams['best-unfiltered'] = streams[best]
        return final_sorted_streams

    def _get_streams(self):
        raise NotImplementedError

    def get_title(self):
        pass

    def get_author(self):
        pass

    def get_category(self):
        pass

    def streams_from_other_plugins(self, url):
        streams = []
        try:
            plugin = self.session.resolve_url(url)
            embed_streams = plugin.streams()
            for (stream_name, stream) in embed_streams.items():
                if stream_name in STREAM_SYNONYMS:
                    continue
                stream.meta['plugin'] = plugin
                streams.append((stream_name, stream))
        except NoPluginError as err:
            log.warning(err)
        except Exception as err:
            log.warning('Not handle url {0} err {1}', url, err, exc_info=log.isEnabledFor(logging.DEBUG))
        return streams

__all__ = ['Plugin']
