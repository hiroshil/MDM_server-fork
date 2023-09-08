import logging
from threading import Lock
from streamlink.compat import is_py2
from streamlink.utils.encoding import maybe_encode
_config_lock = Lock()

class _LogRecord(logging.LogRecord):

    def getMessage(self):
        '''
        Return the message for this LogRecord.

        Return the message for this LogRecord after merging any user-supplied
        arguments with the message.
        '''
        msg = self.msg
        if self.args:
            msg = msg.format(*self.args)
        return maybe_encode(msg)

class StreamlinkLogger(logging.getLoggerClass(), object):

    def makeRecord(self, name, level, fn, lno, msg, args, exc_info, func=None, extra=None, sinfo=None):
        '''
        A factory method which can be overridden in subclasses to create
        specialized LogRecords.
        '''
        if name.startswith('streamlink'):
            return _LogRecord(name, level, fn, lno, msg, args, exc_info, func, sinfo)
        return super().makeRecord(name, level, fn, lno, msg, args, exc_info, func, extra, sinfo)

logging.setLoggerClass(StreamlinkLogger)
root = logging.getLogger('streamlink')

class StringFormatter(logging.Formatter):

    def __init__(self, fmt, datefmt=None, style='%', remove_base=None):
        if is_py2:
            super(StringFormatter, self).__init__(fmt, datefmt=datefmt)
        else:
            super().__init__(fmt, datefmt=datefmt, style=style)
        if style not in ('{', '%'):
            raise ValueError('Only {} and % formatting styles are supported')
        self.style = style
        self.fmt = fmt
        self.remove_base = remove_base or []

    def usesTime(self):
        return self.style == '%' and '%(asctime)' in self.fmt or self.style == '{' and '{asctime}' in self.fmt

    def formatMessage(self, record):
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)
        if self.style == '{':
            return self.fmt.format(**record.__dict__)
        else:
            return self.fmt % record.__dict__

    def format(self, record):
        for rbase in self.remove_base:
            record.name = record.name.replace(rbase + '.', '')
        record.levelname = record.levelname.lower()
        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)
        s = self.formatMessage(record)
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            s += '\n' if not s.endswith('\n') else '' + record.exc_text
        return s

BASIC_FORMAT = '[{name}][{levelname}] {message}'
FORMAT_STYLE = '{'
REMOVE_BASE = ['streamlink', 'streamlink_cli']

def basicConfig(**kwargs):
    with _config_lock:
        filename = kwargs.get('filename')
        if filename:
            mode = kwargs.get('filemode', 'a')
            handler = logging.FileHandler(filename, mode)
        else:
            stream = kwargs.get('stream')
            handler = logging.StreamHandler(stream)
        fs = kwargs.get('format', BASIC_FORMAT)
        style = kwargs.get('style', FORMAT_STYLE)
        dfs = kwargs.get('datefmt', None)
        remove_base = kwargs.get('remove_base', REMOVE_BASE)
        formatter = StringFormatter(fs, dfs, style=style, remove_base=remove_base)
        handler.setFormatter(formatter)
        root.addHandler(handler)
        level = kwargs.get('level')
        if level is not None:
            root.setLevel(level)

__all__ = ['StreamlinkLogger', 'basicConfig', 'root']
