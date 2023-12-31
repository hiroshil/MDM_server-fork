from collections import OrderedDict
from streamlink.compat import urljoin, urlparse, urlunparse, parse_qsl, urlencode

def update_scheme(current, target):
    '''
    Take the scheme from the current URL and applies it to the
    target URL if the target URL startswith // or is missing a scheme
    :param current: current URL
    :param target: target URL
    :return: target URL with the current URLs scheme
    '''
    target_p = urlparse(target)
    if not target_p.scheme and target_p.netloc:
        return '{0}:{1}'.format(urlparse(current).scheme, urlunparse(target_p))
    elif not target_p.scheme and not target_p.netloc:
        return '{0}://{1}'.format(urlparse(current).scheme, urlunparse(target_p))
    else:
        return target

def url_equal(first, second, ignore_scheme=False, ignore_netloc=False, ignore_path=False, ignore_params=False, ignore_query=False, ignore_fragment=False):
    '''
    Compare two URLs and return True if they are equal, some parts of the URLs can be ignored
    :param first: URL
    :param second: URL
    :param ignore_scheme: ignore the scheme
    :param ignore_netloc: ignore the netloc
    :param ignore_path: ignore the path
    :param ignore_params: ignore the params
    :param ignore_query: ignore the query string
    :param ignore_fragment: ignore the fragment
    :return: result of comparison
    '''
    firstp = urlparse(first)
    secondp = urlparse(second)
    return (firstp.scheme == secondp.scheme or ignore_scheme) and ((firstp.netloc == secondp.netloc or ignore_netloc) and ((firstp.path == secondp.path or ignore_path) and ((firstp.params == secondp.params or ignore_params) and ((firstp.query == secondp.query or ignore_query) and (firstp.fragment == secondp.fragment or ignore_fragment)))))

def url_concat(base, *parts, **kwargs):
    '''
    Join extra paths to a URL, does not join absolute paths
    :param base: the base URL
    :param parts: a list of the parts to join
    :param allow_fragments: include url fragments
    :return: the joined URL
    '''
    allow_fragments = kwargs.get('allow_fragments', True)
    for part in parts:
        base = urljoin(base.rstrip('/') + '/', part.strip('/'), allow_fragments)
    return base

def update_qsd(url, qsd=None, remove=None):
    '''
    Update or remove keys from a query string in a URL

    :param url: URL to update
    :param qsd: dict of keys to update, a None value leaves it unchanged
    :param remove: list of keys to remove, or "*" to remove all
                   note: updated keys are never removed, even if unchanged
    :return: updated URL
    '''
    qsd = qsd or {}
    remove = remove or []
    parsed = urlparse(url)
    current_qsd = OrderedDict(parse_qsl(parsed.query))
    if remove == '*':
        remove = list(current_qsd.keys())
    for key in remove:
        if key not in qsd:
            del current_qsd[key]
    for (key, value) in qsd.items():
        if value:
            current_qsd[key] = value
    return parsed._replace(query=urlencode(current_qsd)).geturl()

