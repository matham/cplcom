from kivy.compat import PY2


def pretty_time(seconds):
    '''
    Returns a nice representation of a time value.

    >>> pretty_time(36574)
    '10:9:34.0'

    :param seconds: The number, in seconds, to convert to a string.
    '''
    seconds = int(seconds * 10)
    s, ms = divmod(seconds, 10)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return '{0:d}:{1:d}:{2:d}.{3:d}'.format(h, m, s, ms)
    elif m:
        return '{0:d}:{1:d}.{2:d}'.format(m, s, ms)
    else:
        return '{0:d}.{1:d}'.format(s, ms)


def pretty_space(space, is_rate=False):
    '''
    Returns a nice string representation of a number representing either size,
    e.g. 10 MB, or rate, e.g. 10 MB/s.

    >>> pretty_space(10003045065)
    '9.32 GB'
    >>> tools.pretty_space(10003045065, is_rate=True)
    '9.32 GB/s'

    :param space: The number to convert.
    :param is_rate:
        Whether the number represents size or rate. Defaults to False.
    '''
    t = '/s' if is_rate else ''
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if space < 1024.0:
            return "%3.2f %s%s" % (space, x, t)
        space /= 1024.0
    return "%3.2f %s%s" % (space, 'TB', t)


def byteify(val, py2_only=True):
    '''Returns a byte version of all the strings in the input.
    '''
    if not PY2 and py2_only:
        return val

    if isinstance(val, dict):
        return {byteify(key): byteify(value)
                for key, value in val.iteritems()}
    elif isinstance(val, list):
        return [byteify(element) for element in val]
    elif isinstance(val, unicode):
        return val.encode('utf-8')
    else:
        return val
