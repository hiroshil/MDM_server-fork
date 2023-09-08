import os
from streamlink import __version__ as LIVESTREAMER_VERSION
from StreamDownloader.compat import is_win32
DEFAULT_PLAYER_ARGUMENTS = '{filename}'
DEFAULT_STREAM_METADATA = {'title': 'Unknown Title', 'author': 'Unknown Author', 'category': 'No Category', 'game': 'No Game/Category'}
SUPPORTED_PLAYERS = {'vlc': ['vlc', 'vlc.exe'], 'mpv': ['mpv', 'mpv.exe']}
if is_win32:
    APPDATA = os.path.abspath(__file__)
    for i in range(3):
        APPDATA = os.path.dirname(APPDATA)
        APPDATA = os.path.normpath(APPDATA)
    CUSTOM_APPDATA = os.path.join(APPDATA, 'CUSTOM_APPDATA')
    if os.path.isfile(CUSTOM_APPDATA):
        with open(CUSTOM_APPDATA, 'r') as CUSTOM_APPDATA_FILE:
            APPDATA = CUSTOM_APPDATA_FILE.read().replace('"', '')
            APPDATA = os.path.normpath(APPDATA)
    CONFIG_FILES = [os.path.join(APPDATA, 'streamlinkrc')]
    PLUGINS_DIR = os.path.join(APPDATA, 'plugins')
else:
    XDG_CONFIG_HOME = os.environ.get('XDG_CONFIG_HOME', '~/.config')
    CONFIG_FILES = [os.path.expanduser(XDG_CONFIG_HOME + '/streamlink/config'), os.path.expanduser('~/.streamlinkrc')]
    PLUGINS_DIR = os.path.expanduser(XDG_CONFIG_HOME + '/streamlink/plugins')
STREAM_SYNONYMS = ['best', 'worst', 'best-unfiltered', 'worst-unfiltered']
STREAM_PASSTHROUGH = ['hls', 'http', 'rtmp']
__all__ = ['CONFIG_FILES', 'DEFAULT_PLAYER_ARGUMENTS', 'LIVESTREAMER_VERSION', 'PLUGINS_DIR', 'STREAM_SYNONYMS', 'STREAM_PASSTHROUGH']
