import os
import re
import unicodedata
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET
is_win32 = os.name == 'nt'

def sanitizePath(path):
    (drive, path) = os.path.splitdrive(path)
    if drive:
        drive += os.sep
    parts = path.split(os.sep)
    for i in range(len(parts)):
        parts[i] = cleanName(parts[i])
    return os.path.join(drive, *parts)

def mkdirs(path, mode=511, exist_ok=True):
    try:
        os.makedirs(path, mode, exist_ok)
    except FileExistsError:
        pass

def createDirectory(base, new_dir):
    if is_win32:
        if new_dir.endswith('.'):
            new_dir = new_dir[:-1]
        new_dir = cleanName(new_dir)
        if not base.startswith('\\\\?\\'):
            base = '\\\\?\\' + base
    path_new_dir = os.path.join(base, new_dir)
    if not os.path.exists(path_new_dir):
        try:
            os.mkdir(path_new_dir)
        except FileExistsError:
            pass
    return path_new_dir

def longPath(path):
    if is_win32 and not path.startswith('\\\\?\\'):
        return '\\\\?\\' + path
    return path

def parse_xml(data, name='XML', ignore_ns=False, invalid_char_entities=False):
    '''Wrapper around ElementTree.fromstring with some extras.

    Provides these extra features:
     - Handles incorrectly encoded XML
     - Allows stripping namespace information
     - Wraps errors in custom exception with a snippet of the data in the message
    '''
    if isinstance(data, str):
        data = bytearray(data, 'utf8')
    if ignore_ns:
        data = re.sub(b'[\\t ]xmlns=\\"(.+?)\\"', b'', data)
    if invalid_char_entities:
        data = re.sub(b'&(?!(?:#(?:[0-9]+|[Xx][0-9A-Fa-f]+)|[A-Za-z0-9]+);)', b'&amp;', data)
    try:
        tree = ET.fromstring(data)
    except Exception as err:
        snippet = repr(data)
        if len(snippet) > 35:
            snippet = snippet[:35] + ' ...'
        raise Exception('Unable to parse {0}: {1} ({2})'.format(name, err, snippet))
    return tree

def removeControlCharacters(s):
    return ''.join(ch for ch in s if unicodedata.category(ch)[0] != 'C')

def cleanName(value, deletechars='<>:"/\\|?*\r\n'):
    value = str(value)
    value = filter(lambda x: x not in deletechars, value)
    return removeControlCharacters(value).strip()

def remove_file(path):
    if os.path.exists(path):
        os.remove(path)

def remove_emojis(data):
    emoj = re.compile('[😀-🙏🌀-🗿🚀-🛿🇠-🇿─-⯯✂-➰✂-➰Ⓜ-぀🤦-🤷𐀀-􏿿♀-♂☀-⭕‍⏏⏩⌚️〰]+', re.UNICODE)
    return re.sub(emoj, '', data)

