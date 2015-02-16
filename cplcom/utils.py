

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
