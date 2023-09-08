from __future__ import unicode_literals
import copy
import logging
import datetime
import re
import time
from collections import defaultdict, namedtuple
from itertools import repeat, count
from struct import unpack
import math
from isodate import parse_datetime, parse_duration, Duration
from contextlib import contextmanager
from streamlink.compat import urlparse, urljoin, urlunparse, izip, urlsplit, urlunsplit
from streamlink.exceptions import StreamError
if hasattr(datetime, 'timezone'):
    utc = datetime.timezone.utc
else:

    class UTC(datetime.tzinfo):

        def utcoffset(self, dt):
            return datetime.timedelta(0)

        def tzname(self, dt):
            return 'UTC'

        def dst(self, dt):
            return datetime.timedelta(0)

    utc = UTC()
log = logging.getLogger(__name__)
epoch_start = datetime.datetime(1970, 1, 1, tzinfo=utc)

class DataView:

    def __init__(self, data):
        self.buffer = data

    def getInt8(self, pos):
        return unpack('b', self.buffer[pos:pos + 1])[0]

    def getUint8(self, pos):
        return int.from_bytes(unpack('c', self.buffer[pos:pos + 1])[0], byteorder='big')

    def getUint16(self, pos, littleEndian=False):
        if littleEndian:
            return int(unpack('<H', self.buffer[pos:pos + 2])[0])
        return int(unpack('>H', self.buffer[pos:pos + 2])[0])

    def getUint32(self, pos, littleEndian=False):
        if littleEndian:
            return int(unpack('<I', self.buffer[pos:pos + 4])[0])
        return int(unpack('>I', self.buffer[pos:pos + 4])[0])

def parseSidx(data, byte_offset=0):
    d = DataView(data)
    pos = 0
    box_type = ''
    offset = 0
    sidxEnd = 0
    i = 0
    ref_size = 0
    startRange = 0
    endRange = 0
    data_length = len(data)
    firstOffset = 0
    while box_type != 'sidx' and pos < data_length:
        size = d.getUint32(pos)
        pos += 4
        box_type = ''
        for _ in range(4):
            box_type += chr(d.getInt8(pos))
            pos += 1
        if box_type != 'moof' and box_type != 'traf' and box_type != 'sidx':
            pos += size - 8
        elif box_type == 'sidx':
            pos -= 8
    sidxEnd = d.getUint32(pos) + pos
    if sidxEnd > data_length:
        raise Exception('Not enough sidx')
    sidx_version = d.getUint8(pos + 8)
    pos += 12
    pos += 8
    if sidx_version == 0:
        firstOffset = d.getUint32(pos + 4)
        pos += 8
    else:
        firstOffset = (d.getUint32(pos + 8) << 32) + d.getUint32(pos + 12)
        pos += 16
    firstOffset += sidxEnd + byte_offset
    sidxRangeCount = d.getUint16(pos + 2)
    pos += 4
    sidx_ranges = []
    offset = firstOffset
    for i in range(sidxRangeCount):
        ref_size = d.getUint32(pos) & 2147483647
        endRange = offset + ref_size - 1
        startRange = offset
        sidx_ranges.append((startRange, ref_size))
        pos += 12
        offset += ref_size
    if pos != sidxEnd:
        raise Exception('final pos %d differs from SIDX end %d' % (pos, sidxEnd))
    return sidx_ranges

def fakeSidx(res, chunk_size=3145728):
    if res.status_code == 200:
        data_length = int(res.headers.get('Content-Length', -1))
        if data_length == -1:
            raise Exception('File size is unknow. Do not process this file')
    elif res.status_code == 206:
        range_info = res.headers.get('Content-Range').split(' ')[1]
        (bytes_range, size) = range_info.split('/')
        if bytes_range == '*':
            raise Exception('Range Not Satisfiable %s' % res.headers.get('Content-Range'))
        if size != '*':
            data_length = int(size)
        else:
            raise Exception('File size is unknow. Do not process this file')
    start = 0
    end = 0
    sidx_ranges = []
    while start < data_length:
        end = start + chunk_size - 1
        if end >= data_length:
            end = data_length - 1
        sidx_ranges.append((start, chunk_size))
        start = end + 1
    return sidx_ranges

class Segment(object):

    def __init__(self, url, duration, init=False, content=True, available_at=epoch_start, range=None):
        self.url = url
        self.duration = duration
        self.init = init
        self.content = content
        self.available_at = available_at
        self.range = range

def datetime_to_seconds(dt):
    return (dt - epoch_start).total_seconds()

def count_dt(firstval=datetime.datetime.now(tz=utc), step=datetime.timedelta(seconds=1)):
    x = firstval
    while True:
        yield x
        x += step

@contextmanager
def freeze_timeline(mpd):
    timelines = copy.copy(mpd.timelines)
    yield None
    mpd.timelines = timelines

@contextmanager
def sleeper(duration):
    s = time.time()
    yield None
    time_to_sleep = duration - (time.time() - s)
    if time_to_sleep > 0:
        time.sleep(time_to_sleep)

def sleep_until(walltime):
    c = datetime.datetime.now(tz=utc)
    time_to_wait = (walltime - c).total_seconds()
    if time_to_wait > 0:
        time.sleep(time_to_wait)

class MPDParsers(object):

    @staticmethod
    def bool_str(v):
        return v.lower() == 'true'

    @staticmethod
    def type(type_):
        if type_ not in ('static', 'dynamic'):
            raise MPDParsingError('@type must be static or dynamic')
        return type_

    @staticmethod
    def duration(duration):
        return parse_duration(duration)

    @staticmethod
    def datetime(dt):
        return parse_datetime(dt).replace(tzinfo=utc)

    @staticmethod
    def segment_template(url_template):
        end = 0
        res = ''
        url_template = url_template.replace('{', '{{').replace('}', '}}')
        for m in re.compile('(.*?)\\$(\\w+)(?:%([\\w.]+))?\\$').finditer(url_template):
            (_, end) = m.span()
            res += '{0}{{{1}{2}}}'.format(m.group(1), m.group(2), ':' + m.group(3) if m.group(3) else '')
        return (res + url_template[end:]).format

    @staticmethod
    def frame_rate(frame_rate):
        if '/' in frame_rate:
            (a, b) = frame_rate.split('/')
            return float(a)/float(b)
        else:
            return float(frame_rate)

    @staticmethod
    def timedelta(timescale=1):

        def _timedelta(seconds):
            return datetime.timedelta(seconds=int(float(seconds)/float(timescale)))

        return _timedelta

    @staticmethod
    def range(range_spec):
        r = range_spec.split('-')
        if len(r) != 2:
            raise MPDParsingError('invalid byte-range-spec')
        start = int(r[0])
        end = r[1] and int(r[1]) or None
        return (start, end and end - start + 1)

class MPDParsingError(Exception):
    pass

class MPDNode(object):
    __tag__ = None

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        self.node = node
        self.root = root
        self.parent = parent
        self._base_url = kwargs.get('base_url')
        self.attributes = set([])
        if self.__tag__ and self.node.tag.lower() != self.__tag__.lower():
            raise MPDParsingError('root tag did not match the expected tag: {}'.format(self.__tag__))

    @property
    def attrib(self):
        return self.node.attrib

    @property
    def text(self):
        return self.node.text

    def __str__(self):
        return '<{tag} {attrs}>'.format(tag=self.__tag__, attrs=' '.join('@{}={}'.format(attr, getattr(self, attr)) for attr in self.attributes))

    def attr(self, key, default=None, parser=None, required=False, inherited=False):
        self.attributes.add(key)
        if key in self.attrib:
            value = self.attrib.get(key)
            if parser and callable(parser):
                return parser(value)
            return value
        elif inherited and self.parent and hasattr(self.parent, key) and getattr(self.parent, key):
            return getattr(self.parent, key)
        elif required:
            raise MPDParsingError('could not find required attribute {tag}@{attr} '.format(attr=key, tag=self.__tag__))
        else:
            return default
        if required:
            raise MPDParsingError('could not find required attribute {tag}@{attr} '.format(attr=key, tag=self.__tag__))
        else:
            return default

    def children(self, cls, minimum=0, maximum=None):
        children = self.node.findall(cls.__tag__)
        if len(children) < minimum or maximum and len(children) > maximum:
            raise MPDParsingError('expected to find {}/{} required [{}..{})'.format(self.__tag__, cls.__tag__, minimum, maximum or 'unbound'))
        return list(map(lambda x: cls(x[1], root=self.root, parent=self, i=x[0], base_url=self.base_url), enumerate(children)))

    def only_child(self, cls, minimum=0):
        children = self.children(cls, minimum=minimum, maximum=1)
        if len(children):
            return children[0]

    def walk_back(self, cls=None, f=lambda x: x):
        node = self.parent
        while node:
            if cls is None or cls.__tag__ == node.__tag__:
                yield f(node)
            node = node.parent

    def walk_back_get_attr(self, attr):
        parent_attrs = [getattr(n, attr) for n in self.walk_back() if hasattr(n, attr)]
        if len(parent_attrs):
            return parent_attrs[0]

    @property
    def base_url(self):
        base_url = self._base_url
        if hasattr(self, 'baseURLs') and len(self.baseURLs):
            base_url = BaseURL.join(base_url, self.baseURLs[0].url)
        return base_url

class MPD(MPDNode):
    __doc__ = """
    Represents the MPD as a whole

    Should validate the XML input and provide methods to get segment URLs for each Period, AdaptationSet and
    Representation.

    """
    __tag__ = 'MPD'

    def __init__(self, node, root=None, parent=None, url=None, *args, **kwargs):
        super(MPD, self).__init__(node, *args, root=self, **kwargs)
        self.url = url
        self.http = kwargs.pop('http', None)
        self.timelines = defaultdict(lambda : -1)
        self.timelines.update(kwargs.pop('timelines', {}))
        self.id = self.attr('id')
        self.profiles = self.attr('profiles', required=True)
        self.type = self.attr('type', default='static', parser=MPDParsers.type)
        self.minimumUpdatePeriod = self.attr('minimumUpdatePeriod', parser=MPDParsers.duration, default=Duration())
        self.minBufferTime = self.attr('minBufferTime', default=60, parser=MPDParsers.duration, required=False)
        self.timeShiftBufferDepth = self.attr('timeShiftBufferDepth', parser=MPDParsers.duration)
        self.availabilityStartTime = self.attr('availabilityStartTime', parser=MPDParsers.datetime, default=datetime.datetime.fromtimestamp(0, utc), required=self.type == 'dynamic')
        self.publishTime = self.attr('publishTime', parser=MPDParsers.datetime, required=self.type == 'dynamic')
        self.availabilityEndTime = self.attr('availabilityEndTime', parser=MPDParsers.datetime)
        self.mediaPresentationDuration = self.attr('mediaPresentationDuration', parser=MPDParsers.duration)
        self.suggestedPresentationDelay = self.attr('suggestedPresentationDelay', parser=MPDParsers.duration)
        location = self.children(Location)
        self.location = location[0] if location else None
        if self.location:
            self.url = self.location.text
            urlp = list(urlparse(self.url))
            if urlp[2]:
                (urlp[2], _) = urlp[2].rsplit('/', 1)
            self._base_url = urlunparse(urlp)
        self.baseURLs = self.children(BaseURL)
        self.periods = self.children(Period, minimum=1)
        self.programInformation = self.children(ProgramInformation)

class ProgramInformation(MPDNode):
    __tag__ = 'ProgramInformation'

class BaseURL(MPDNode):
    __tag__ = 'BaseURL'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(BaseURL, self).__init__(node, root, parent, *args, **kwargs)
        self.url = self.node.text.strip()

    @property
    def is_absolute(self):
        return urlparse(self.url).scheme

    @staticmethod
    def join(url, other):
        if urlparse(other).scheme:
            return other
        elif url:
            parts = list(urlsplit(url))
            if not parts[2].endswith('/'):
                parts[2] += '/'
            url = urlunsplit(parts)
            return urljoin(url, other)
        else:
            return other

class Location(MPDNode):
    __tag__ = 'Location'

class Period(MPDNode):
    __tag__ = 'Period'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(Period, self).__init__(node, root, parent, *args, **kwargs)
        self.i = kwargs.get('i', 0)
        self.id = self.attr('id')
        self.bitstreamSwitching = self.attr('bitstreamSwitching', parser=MPDParsers.bool_str)
        self.duration = self.attr('duration', default=Duration(), parser=MPDParsers.duration)
        self.start = self.attr('start', default=Duration(), parser=MPDParsers.duration)
        if self.start is None and self.i == 0 and self.root.type == 'static':
            self.start = 0
        self.baseURLs = self.children(BaseURL)
        self.segmentBase = self.only_child(SegmentBase)
        self.adaptationSets = self.children(AdaptationSet, minimum=1)
        self.segmentList = self.only_child(SegmentList)
        self.segmentTemplate = self.only_child(SegmentTemplate)
        self.sssetIdentifier = self.only_child(AssetIdentifier)
        self.eventStream = self.children(EventStream)
        self.subset = self.children(Subset)

class SegmentBase(MPDNode):
    __tag__ = 'SegmentBase'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indexRange = self.attr('indexRange', parser=MPDParsers.range)
        self.initialization = self.only_child(Initialization)
        self.http = self.root.http
        (start, length) = self.indexRange
        if length:
            end = start + length - 1
        else:
            end = ''
        resp = self.http.get(self.base_url, headers={'Range': 'bytes=%s-%s' % (start, end)}, exception=StreamError)
        self.segment_ranges = fakeSidx(resp)

    @property
    def segments(self):
        for segment_range in self.segment_ranges:
            yield Segment(self.base_url, 0, init=False, content=True, range=segment_range)

class AssetIdentifier(MPDNode):
    __tag__ = 'AssetIdentifier'

class Subset(MPDNode):
    __tag__ = 'Subset'

class EventStream(MPDNode):
    __tag__ = 'EventStream'

class Initialization(MPDNode):
    __tag__ = 'Initialization'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(Initialization, self).__init__(node, root, parent, *args, **kwargs)
        self.source_url = self.attr('sourceURL')
        self.range = self.attr('range', parser=MPDParsers.range)

class SegmentURL(MPDNode):
    __tag__ = 'SegmentURL'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(SegmentURL, self).__init__(node, root, parent, *args, **kwargs)
        self.media = self.attr('media')
        self.media_range = self.attr('mediaRange', parser=MPDParsers.range)

class SegmentList(MPDNode):
    __tag__ = 'SegmentList'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(SegmentList, self).__init__(node, root, parent, *args, **kwargs)
        self.presentation_time_offset = self.attr('presentationTimeOffset')
        self.timescale = self.attr('timescale', parser=int)
        self.duration = self.attr('duration', parser=int)
        self.start_number = self.attr('startNumber', parser=int, default=1)
        if self.duration:
            self.duration_seconds = self.duration/float(self.timescale)
        else:
            self.duration_seconds = None
        self.initialization = self.only_child(Initialization)
        self.segment_urls = self.children(SegmentURL, minimum=1)

    @property
    def segments(self):
        if self.initialization:
            yield Segment(self.make_url(self.initialization.source_url), 0, init=True, content=False)
        for (n, segment_url) in enumerate(self.segment_urls, self.start_number):
            yield Segment(self.make_url(segment_url.media), self.duration_seconds, range=segment_url.media_range)

    def make_url(self, url):
        return BaseURL.join(self.base_url, url)

class AdaptationSet(MPDNode):
    __tag__ = 'AdaptationSet'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(AdaptationSet, self).__init__(node, root, parent, *args, **kwargs)
        self.id = self.attr('id')
        self.group = self.attr('group')
        self.mimeType = self.attr('mimeType')
        self.lang = self.attr('lang')
        self.contentType = self.attr('contentType')
        self.par = self.attr('par')
        self.minBandwidth = self.attr('minBandwidth')
        self.maxBandwidth = self.attr('maxBandwidth')
        self.minWidth = self.attr('minWidth', parser=int)
        self.maxWidth = self.attr('maxWidth', parser=int)
        self.minHeight = self.attr('minHeight', parser=int)
        self.maxHeight = self.attr('maxHeight', parser=int)
        self.minFrameRate = self.attr('minFrameRate', parser=MPDParsers.frame_rate)
        self.maxFrameRate = self.attr('maxFrameRate', parser=MPDParsers.frame_rate)
        self.segmentAlignment = self.attr('segmentAlignment', default=False, parser=MPDParsers.bool_str)
        self.bitstreamSwitching = self.attr('bitstreamSwitching', parser=MPDParsers.bool_str)
        self.subsegmentAlignment = self.attr('subsegmentAlignment', default=False, parser=MPDParsers.bool_str)
        self.subsegmentStartsWithSAP = self.attr('subsegmentStartsWithSAP', default=0, parser=int)
        self.baseURLs = self.children(BaseURL)
        self.segmentTemplate = self.only_child(SegmentTemplate)
        self.representations = self.children(Representation, minimum=1)
        self.contentProtection = self.children(ContentProtection)

class SegmentTemplate(MPDNode):
    __tag__ = 'SegmentTemplate'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(SegmentTemplate, self).__init__(node, root, parent, *args, **kwargs)
        self.defaultSegmentTemplate = self.walk_back_get_attr('segmentTemplate')
        self.initialization = self.attr('initialization', parser=MPDParsers.segment_template)
        self.media = self.attr('media', parser=MPDParsers.segment_template)
        self.duration = self.attr('duration', parser=int, default=self.defaultSegmentTemplate.duration if self.defaultSegmentTemplate else None)
        self.timescale = self.attr('timescale', parser=int, default=self.defaultSegmentTemplate.timescale if self.defaultSegmentTemplate else 1)
        self.startNumber = self.attr('startNumber', parser=int, default=self.defaultSegmentTemplate.startNumber if self.defaultSegmentTemplate else 1)
        self.presentationTimeOffset = self.attr('presentationTimeOffset', parser=MPDParsers.timedelta(self.timescale))
        if self.duration:
            self.duration_seconds = self.duration/float(self.timescale)
        else:
            self.duration_seconds = None
        self.period = list(self.walk_back(Period))[0]
        self.segmentTimeline = self.only_child(SegmentTimeline)

    def segments(self, **kwargs):
        if kwargs.pop('init', True):
            init_url = self.format_initialization(**kwargs)
            if init_url:
                yield Segment(init_url, 0, True, False)
        for (media_url, available_at) in self.format_media(**kwargs):
            yield Segment(media_url, self.duration_seconds, False, True, available_at)

    def make_url(self, url):
        '''
        Join the URL with the base URL, unless it's an absolute URL
        :param url: maybe relative URL
        :return: joined URL
        '''
        return BaseURL.join(self.base_url, url)

    def format_initialization(self, **kwargs):
        if self.initialization:
            return self.make_url(self.initialization(**kwargs))

    def segment_numbers(self):
        '''
        yield the segment number and when it will be available
        There are two cases for segment number generation, static and dynamic.

        In the case of static stream, the segment number starts at the startNumber and counts
        up to the number of segments that are represented by the periods duration.

        In the case of dynamic streams, the segments should appear at the specified time
        in the simplest case the segment number is based on the time since the availabilityStartTime
        :return:
        '''
        log.debug('Generating segment numbers for {0} playlist (id={1})'.format(self.root.type, self.parent.id))
        if self.root.type == 'static':
            available_iter = repeat(epoch_start)
            duration = self.period.duration.seconds or self.root.mediaPresentationDuration.seconds
            if duration:
                number_iter = range(self.startNumber, int(duration/self.duration_seconds) + 1)
            else:
                number_iter = count(self.startNumber)
        else:
            now = datetime.datetime.now(utc)
            if self.presentationTimeOffset:
                since_start = now - self.presentationTimeOffset - self.root.availabilityStartTime
                available_start_date = self.root.availabilityStartTime + self.presentationTimeOffset + since_start
                available_start = available_start_date
            else:
                since_start = now - self.root.availabilityStartTime
                available_start = now
            suggested_delay = datetime.timedelta(seconds=self.root.suggestedPresentationDelay.total_seconds() if self.root.suggestedPresentationDelay else 3)
            number_iter = count(self.startNumber + int((since_start - suggested_delay - self.root.minBufferTime).total_seconds()/self.duration_seconds))
            available_iter = count_dt(available_start, step=datetime.timedelta(seconds=self.duration_seconds))
        for (number, available_at) in izip(number_iter, available_iter):
            yield (number, available_at)

    def format_media(self, **kwargs):
        if self.segmentTimeline:
            if self.parent.id is None:
                self.parent.id = self.parent.mimeType
            log.debug('Generating segment timeline for {0} playlist (id={1}))'.format(self.root.type, self.parent.id))
            if self.root.type == 'dynamic':
                suggested_delay = datetime.timedelta(seconds=self.root.suggestedPresentationDelay.total_seconds() if self.root.suggestedPresentationDelay else 3)
                publish_time = self.root.publishTime or epoch_start
                timeline = []
                available_at = publish_time
                for (segment, n) in reversed(list(zip(self.segmentTimeline.segments, count(self.startNumber)))):
                    url = self.make_url(self.media(Time=segment.t, Number=n, **kwargs))
                    duration = datetime.timedelta(seconds=segment.d/self.timescale)
                    if self.root.timelines[self.parent.id] == -1 and publish_time - available_at >= suggested_delay:
                        break
                    timeline.append((url, available_at, segment.t))
                    available_at -= duration
                for (url, available_at, t) in reversed(timeline):
                    if t > self.root.timelines[self.parent.id]:
                        self.root.timelines[self.parent.id] = t
                        yield (url, available_at)
            for (segment, n) in zip(self.segmentTimeline.segments, count(self.startNumber)):
                yield (self.make_url(self.media(Time=segment.t, Number=n, **kwargs)), datetime.datetime.now(tz=utc))
        else:
            for (number, available_at) in self.segment_numbers():
                yield (self.make_url(self.media(Number=number, **kwargs)), available_at)

class Representation(MPDNode):
    __tag__ = 'Representation'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(Representation, self).__init__(node, root, parent, *args, **kwargs)
        self.id = self.attr('id', required=True)
        self.bandwidth = self.attr('bandwidth', parser=lambda b: float(b)/1000.0, required=True)
        self.mimeType = self.attr('mimeType', required=True, inherited=True)
        self.codecs = self.attr('codecs')
        self.startWithSAP = self.attr('startWithSAP')
        self.width = self.attr('width', parser=int)
        self.height = self.attr('height', parser=int)
        self.frameRate = self.attr('frameRate', parser=MPDParsers.frame_rate)
        self.audioSamplingRate = self.attr('audioSamplingRate', parser=int)
        self.numChannels = self.attr('numChannels', parser=int)
        self.lang = self.attr('lang', inherited=True)
        self.baseURLs = self.children(BaseURL)
        self.subRepresentation = self.children(SubRepresentation)
        self.segmentBase = self.only_child(SegmentBase)
        self.segmentList = self.children(SegmentList)
        self.segmentTemplate = self.only_child(SegmentTemplate)

    @property
    def bandwidth_rounded(self):
        return round(self.bandwidth, 1 - int(math.log10(self.bandwidth)))

    def segments(self, **kwargs):
        '''
        Segments are yielded when they are available

        Segments appear on a time line, for dynamic content they are only available at a certain time
        and sometimes for a limited time. For static content they are all available at the same time.

        :param kwargs: extra args to pass to the segment template
        :return: yields Segments
        '''
        segmentBase = self.segmentBase or self.walk_back_get_attr('segmentBase')
        segmentLists = self.segmentList or self.walk_back_get_attr('segmentList')
        segmentTemplate = self.segmentTemplate or self.walk_back_get_attr('segmentTemplate')
        if segmentTemplate:
            for segment in segmentTemplate.segments(RepresentationID=self.id, Bandwidth=int(self.bandwidth*1000), **kwargs):
                if segment.init:
                    yield segment
                else:
                    yield segment
        elif segmentLists:
            for segmentList in segmentLists:
                for segment in segmentList.segments:
                    yield segment
        elif segmentBase:
            for segment in segmentBase.segments:
                yield segment
        else:
            yield Segment(self.base_url, 0, True, True)

class SubRepresentation(MPDNode):
    __tag__ = 'SubRepresentation'

class SegmentTimeline(MPDNode):
    __tag__ = 'SegmentTimeline'
    TimelineSegment = namedtuple('TimelineSegment', 't d')

    def __init__(self, node, *args, **kwargs):
        super(SegmentTimeline, self).__init__(node, *args, **kwargs)
        self.timescale = self.walk_back_get_attr('timescale')
        self.timeline_segments = self.children(_TimelineSegment)

    @property
    def segments(self):
        t = 0
        for tsegment in self.timeline_segments:
            t = tsegment.t
            for repeated_i in range(tsegment.r + 1):
                yield self.TimelineSegment(t, tsegment.d)
                t += tsegment.d

class _TimelineSegment(MPDNode):
    __tag__ = 'S'

    def __init__(self, node, *args, **kwargs):
        super(_TimelineSegment, self).__init__(node, *args, **kwargs)
        self.t = self.attr('t', parser=int)
        self.d = self.attr('d', parser=int)
        self.r = self.attr('r', parser=int, default=0)

class ContentProtection(MPDNode):
    __tag__ = 'ContentProtection'

    def __init__(self, node, root=None, parent=None, *args, **kwargs):
        super(ContentProtection, self).__init__(node, root, parent, *args, **kwargs)
        self.schemeIdUri = self.attr('schemeIdUri')
        self.value = self.attr('value')
        self.default_KID = self.attr('default_KID')

