'''Config
==========

Configuration used across Moa objects.
'''

import operator
from inspect import isclass
from os.path import join, dirname
from collections import defaultdict
from importlib import import_module
import json
from kivy.uix.behaviors.knspace import knspace
from cplcom.utils import byteify


def _get_bases(cls):
    for base in cls.__bases__:
        if base.__name__ == 'object':
            break
        yield base
        for cbase in _get_bases(base):
            yield cbase


def _get_settings_attrs(cls):
    attrs = []
    for c in [cls] + list(_get_bases(cls)):
        if not hasattr(c, '__settings_attrs__'):
                continue

        for attr in c.__settings_attrs__:
            if attr in attrs:
                continue
            if not hasattr(cls, attr):
                raise Exception('Missing attribute <{}> in <{}>'.
                                format(attr, cls.__name__))
            attrs.append(attr)
    return attrs


def _get_classses_settings_attrs(cls):
    attrs = {}
    for c in [cls] + list(_get_bases(cls)):
        if '__settings_attrs__' not in c.__dict__ or not c.__settings_attrs__:
                continue

        for attr in c.__settings_attrs__:
            if not hasattr(cls, attr):
                raise Exception('Missing attribute <{}> in <{}>'.
                                format(attr, cls.__name__))
        attrs['{}.{}'.format(c.__module__, c.__name__)] = {
            attr: [getattr(c, attr).defaultvalue, None]
            for attr in c.__settings_attrs__}
    return attrs


def populate_config(json_filename, classes):
    with open(json_filename) as fh:
        opts = byteify(json.load(fh))

    new_opts = {}
    for name, cls in classes.items():
        if isinstance(cls, basestring):
            obj = getattr(knspace, cls)
        else:
            obj = cls

        is_cls = isclass(obj)
        opt = opts.get(name, {})
        new_vals = {}
        if is_cls:
            for attr in _get_settings_attrs(obj):
                new_vals[attr] = opt.get(
                    attr, getattr(obj, attr).defaultvalue)
        else:
            for attr in _get_settings_attrs(obj.__class__):
                new_vals[attr] = opt.get(attr, getattr(obj, attr))

        new_opts[name] = new_vals
    return new_opts


def apply_config(opts, classes):
    for name, cls in classes.items():
        if isinstance(cls, basestring):
            obj = getattr(knspace, name)
        elif isclass(cls):
            continue
        else:
            obj = cls
        if not obj:
            continue

        for k, v in opts[name].items():
            setattr(obj, k, v)


def create_doc_listener(
        sphinx_app, package, config_attrs_name='__settings_attrs__',
        directory='data', filename='config_attrs.json'):
    data = defaultdict(dict)

    def config_attrs_doc_listener(app, what, name, obj, options, lines):
        if not name.startswith(package.__name__):
            return

        if what == 'class':
            if hasattr(obj, config_attrs_name):
                if name not in data:
                    data[name] = {n: [] for n in obj.__settings_attrs__}
                else:
                    cls_data = data[name]
                    for n in obj.__settings_attrs__:
                        if n not in cls_data:
                            cls_data[n] = []
        elif what == 'attribute':
            parts = name.split('.')
            cls = '.'.join(parts[:-1])
            data[cls][parts[-1]] = lines

    def dump_config_attrs_doc(app, exception):
        with open(join(package.__path__[0], directory, filename), 'w') as fh:
            json.dump(data, fh, sort_keys=True, indent=4,
                      separators=(',', ': '))

    sphinx_app.connect('autodoc-process-docstring', config_attrs_doc_listener)
    sphinx_app.connect('build-finished', dump_config_attrs_doc)


def get_config_attrs_doc(
        classes, json_map={}, json_default=join('data', 'config_attrs.json')):
    '''Objects is a dict of object (class) paths and keys are the names of the
    config attributes of the class.
    '''
    docs = {}
    docs_used = {}
    packages = {}
    for name, cls in classes.items():
        if isinstance(cls, basestring):
            cls = getattr(knspace, cls)
        if not isclass(cls):
            cls = cls.__class__
        if not _get_settings_attrs(cls):
            continue

        mod = cls.__module__.split('.')[0]
        packages[mod] = import_module(mod)
        docs_used[name] = _get_classses_settings_attrs(cls)

    for mod_name, mod in packages.items():
        f = join(mod.__path__[0], json_map.get(mod_name, json_default))
        with open(f) as fh:
            docs.update(json.load(fh))

    docs_final = {}
    for name, classes_attrs in docs_used.items():
        docs_final[name] = {}
        for cls, attrs in classes_attrs.items():
            cls_docs = docs.get(cls, {})
            for attr in attrs:
                attrs[attr][1] = cls_docs.get(attr, [])
            docs_final[name].update(attrs)
    return docs_final


def write_config_attrs_rst(
        classes, package, app, exception, json_map={},
        json_default=join('data', 'config_attrs.json'),
        rst_fname=join('doc', 'source', 'config.rst')):
    docs = get_config_attrs_doc(classes, json_map, json_default)
    lines = ['{} Config'.format(package.__name__)]
    lines.append('=' * len(lines[0]))
    lines.append('')

    for name, attrs in sorted(docs.items(), key=operator.itemgetter(0)):
        lines.append(':{}:'.format(name))
        lines.append('')
        for attr, (default, doc) in sorted(attrs.items(),
                                           key=operator.itemgetter(0)):
            lines.append('`{}`: {}'.format(attr, default))
            lines.extend([' ' + d for d in doc])

    lines = '\n'.join(lines)
    try:
        with open(rst_fname) as fh:
            if fh.read() == lines:
                return
    except IOError:
        pass

    with open(join(dirname(package.__path__[0]), rst_fname), 'w') as fh:
        fh.write(lines)
