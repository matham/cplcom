'''Utilities
=============
'''
from kivy.compat import PY2
from kivy.utils import get_color_from_hex
from kivy.properties import StringProperty
from kivy.factory import Factory
from kivy.event import EventDispatcher
import json
from io import StringIO
from ruamel.yaml import YAML

__all__ = ('pretty_time', 'pretty_space', 'byteify', 'json_dumps',
           'json_loads', 'ColorTheme', 'apply_args_post')


def pretty_time(seconds):
    '''Returns a nice representation of a time value.

    :Parameters:

        `seconds`: float, int
            The number, in seconds, to convert to a string.

    :returns:
        String representation of the time.

    For example::

        >>> pretty_time(36574)
        '10:9:34.0'
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
    '''Returns a nice string representation of a number representing either
    size, e.g. 10 MB, or rate, e.g. 10 MB/s.

    :Parameters:

        `space`: float, int
            The number to convert.
        `is_rate`: bool
            Whether the number represents size or rate. Defaults to False.

    :returns:
        String representation of the space.

    For example::

        >>> pretty_space(10003045065)
        '9.32 GB'
        >>> tools.pretty_space(10003045065, is_rate=True)
        '9.32 GB/s'
    '''
    t = '/s' if is_rate else ''
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if space < 1024.0:
            return "%3.2f %s%s" % (space, x, t)
        space /= 1024.0
    return "%3.2f %s%s" % (space, 'TB', t)


def byteify(val, py2_only=True):
    '''Returns a copy of the input with all string in the input converted to
    bytes.

    :Parameters:

        `val`: object
            The object to convert.
        `py2_only`: bool
            If the conversion should happen in Python 2.x only. If False,
            it's always converted. If True, the default, it's only converted to
            bytes when running in Python 2.

    For example in python 2::

        >>> obj = {u'cheese': u'crackers', 4: [u'four', u'apple', 5, \
'cheeses']}
        >>> obj
        {u'cheese': u'crackers', 4: [u'four', u'apple', 5, 'cheeses']}
        >>> byteify(obj)
        {'cheese': 'crackers', 4: ['four', 'apple', 5, 'cheeses']}
    '''
    if not PY2 and py2_only:
        return val

    if isinstance(val, dict):
        return {byteify(key): byteify(value)
                for key, value in val.items()}
    elif isinstance(val, list):
        return [byteify(element) for element in val]
    elif isinstance(val, unicode):
        return val.encode('utf-8')
    else:
        return val


def unicodify(val, py3_only=False):
    if PY2 and py3_only:
        return val

    if isinstance(val, dict):
        return {unicodify(key): unicodify(value)
                for key, value in val.items()}
    elif isinstance(val, list):
        return [unicodify(element) for element in val]
    elif isinstance(val, bytes):
        return val.decode('utf-8')
    else:
        return val


def json_dumps(value):
    return json.dumps(value, sort_keys=True, indent=4, separators=(',', ': '))


def json_loads(value):
    decoded = json.loads(value)
    return byteify(decoded, True)


def yaml_dumps(value):
    yaml = YAML()
    s = StringIO()
    yaml.preserve_quotes = True
    yaml.dump(value, s)
    return s.getvalue()


def yaml_loads(value):
    yaml = YAML(typ='safe')
    return yaml.load(value)


class ColorTheme(EventDispatcher):

    primary_dark = StringProperty(get_color_from_hex('00796BFF'))

    primary = StringProperty(get_color_from_hex('009688FF'))

    primary_light = StringProperty(get_color_from_hex('B2DFDBFF'))

    primary_text = StringProperty(get_color_from_hex('FFFFFFFF'))

    accent = StringProperty(get_color_from_hex('E040FBFF'))

    text_primary = StringProperty(get_color_from_hex('212121FF'))

    text_secondary = StringProperty(get_color_from_hex('757575FF'))

    divider = StringProperty(get_color_from_hex('BDBDBDFF'))


class KVBehavior(object):
    pass


def apply_args_post(cls, **keywordargs):
    def ret_func(*largs, **kwargs):
        o = cls(*largs, **kwargs)
        for key, value in keywordargs.items():
            setattr(o, key, value)
        return o
    return ret_func

Factory.register(classname='ColorTheme', cls=ColorTheme)
Factory.register(classname='KVBehavior', cls=KVBehavior)
