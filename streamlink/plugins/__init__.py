'''
    New plugins should use streamlink.plugin.Plugin instead
    of this module, but this is kept here for backwards
    compatibility.
'''
from types import ModuleType
from streamlink.plugins import archive, dailymotion, dash, fembed, hds, hls, http, hydraxDirect, longvan, mixdrop, okru, onedrive, phimmoichilla, proxyimg, rtmp, shortlink, streame_cloud, StreamSB, streamtape, vimeo, vudeo, youtube
ALL_PLUGINS = {name: module.__plugin__ for (name, module) in globals().items() if isinstance(module, ModuleType) and 'streamlink.plugins.' in module.__name__}
