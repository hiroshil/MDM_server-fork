import os
import re
import sys
is_py2 = sys.version_info[0] == 2
is_py3 = sys.version_info[0] == 3
is_win32 = os.name == 'nt'
if is_py2:
    input = raw_input
    stdout = sys.stdout
    file = file
    _find_unsafe = re.compile('[^\\w@%+=:,./-]').search
    from backports.shutil_get_terminal_size import get_terminal_size
elif is_py3:
    input = input
    stdout = sys.stdout.buffer
    from io import IOBase as file
    from shutil import get_terminal_size
    from shlex import quote
    _find_unsafe = re.compile('[^\\w@%+=:,./-]', re.ASCII).search

def shlex_quote(s):
    '''Return a shell-escaped version of the string *s*.

    Backported from Python 3.3 standard library module shlex.
    '''
    if is_py3:
        return quote(s)
    if not s:
        return "''"
    if _find_unsafe(s) is None:
        return s
    return "'" + s.replace("'", '\'"\'"\'') + "'"

__all__ = ['is_py2', 'is_py3', 'is_win32', 'input', 'stdout', 'file', 'shlex_quote', 'get_terminal_size']
