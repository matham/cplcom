'''Config
==========

Configuration used across Moa objects within CPL experiments.

Overview
---------

Configuration works as follows. Each class that has configuration attributes
must list these attributes in a list in the class ``__settings_attrs__``
attribute. Each of the properties listed there must be Kivy properties of
that class.

When generating docs, the documentation of these properties are dumped to
a json file using :func:`create_doc_listener` (and should be committed to the
repo manually).

Each experiment defines a application class based on
:class:`~cplcom.moa.app.ExperimentApp`. Using this classe's
:meth:`~cplcom.moa.app.ExperimentApp.get_config_classes` method we get a list
of all classes used in the current experiment that requires configuration
and :func:`write_config_attrs_rst` is used to combine all these docs
and display them in a single place in the generated html pages.

Similarly, when the app is run, a single json file is generated with all these
config values and is later read and is used to configure the experiment by the
user. :attr:`~cplcom.moa.app.ExperimentApp.app_settings` is where it's stored
after reading. Each class is responsible for reading its configuration
from there.

Usage
-----

When creating an experiment, ensure that the root stage called `RootStage`
inherited from :class:`~cplcom.moa.stages.ConfigStageBase` overwrites the
:meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes` method
returning all the classes that need configuration.

Then, in the sphinx conf.py file do::

    def setup(app):
        create_doc_listener(app, project_name)
        app.connect('build-finished', partial(write_config_attrs_rst, \
ProjectApp.get_config_classes(), project_name))

and run `make html` twice. This will create the ``config_attrs.json`` file
under project_name/data and the config.rst file under doc/source. This
config.rst should have been listed in the sphinx index so on the second run
this file will be converted to html containing all the config tokens.

The ``config_attrs.json`` files are read for all the projects on which
the experiment depends on, so they should exist in the repos.
'''

import operator
from inspect import isclass
from os.path import join, dirname
import re
from importlib import import_module
import json
from kivy.uix.behaviors.knspace import knspace
from kivy.compat import PY2, string_types
from cplcom.utils import byteify, yaml_loads, yaml_dumps

__all__ = ('populate_config', 'apply_config', 'dump_config',
           'populate_dump_config', 'create_doc_listener',
           'get_config_attrs_doc', 'write_config_attrs_rst')

config_list_pat = re.compile(
    '\\[\\s+([^",\\]\\s{}]+,\\s+)*[^",\\]\\s{}]+\\s+\\]')
config_whitesp_pat = re.compile('\\s')


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
        if '__settings_attrs__' not in c.__dict__:
                continue

        for attr in c.__settings_attrs__:
            if attr in attrs:
                continue
            if not hasattr(cls, attr):
                raise Exception('Missing attribute <{}> in <{}>'.
                                format(attr, cls.__name__))
            attrs.append(attr)
    return attrs


def _decode(s):
    return s.decode('utf8') if isinstance(s, bytes) else s


def _get_classses_settings_attrs(cls):
    attrs = {}
    for c in [cls] + list(_get_bases(cls)):
        if '__settings_attrs__' not in c.__dict__ or not c.__settings_attrs__:
                continue

        for attr in c.__settings_attrs__:
            if not hasattr(cls, attr):
                raise Exception('Missing attribute <{}> in <{}>'.
                                format(attr, cls.__name__))
        attrs[u'{}.{}'.format(c.__module__, c.__name__)] = {
            attr: [getattr(c, attr).defaultvalue, None]
            for attr in c.__settings_attrs__}
    return attrs


def _get_config_dict(name, cls, opts):
    if isinstance(cls, string_types):
        obj = getattr(knspace, cls)
    else:
        obj = cls

    opt = opts.get(name, {})
    new_vals = {}
    if isclass(obj):
        for attr in _get_settings_attrs(obj):
            new_vals[attr] = opt.get(
                attr, getattr(obj, attr).defaultvalue)
    else:
        if hasattr(obj, 'get_settings_attrs'):
            for k, v in obj.get_settings_attrs(
                    _get_settings_attrs(obj.__class__)).items():
                new_vals[k] = opt.get(k, v)
        else:
            for attr in _get_settings_attrs(obj.__class__):
                new_vals[attr] = opt.get(attr, getattr(obj, attr))
    return new_vals


def populate_config(filename, classes, from_file=True):
    '''Reads the config file and loads all the config data for the classes
    listed in `classes`.
    '''
    opts = {}
    if from_file:
        try:
            with open(filename) as fh:
                opts = yaml_loads(fh.read())
            if opts is None:
                opts = {}
        except IOError:
            pass

    new_opts = {}
    for name, cls in classes.items():
        if isinstance(cls, dict):
            new_opts[name] = {
                k: _get_config_dict(k, c, opts.get(name, {})) for
                k, c in cls.items()}
        elif isinstance(cls, (list, tuple)):
            new_opts[name] = [_get_config_dict(name, c, opts) for c in cls]
        else:
            new_opts[name] = _get_config_dict(name, cls, opts)
    return new_opts


def apply_config(opts, classes):
    '''Takes the config data read with :func:`populate_config` and applys
    them to any existing class instances listed in classes.
    '''
    for name, cls in classes.items():
        if name not in opts:
            continue

        if isinstance(cls, string_types):
            obj = getattr(knspace, name)
        elif isclass(cls):
            continue
        else:
            obj = cls

        if not obj:
            continue

        if hasattr(obj, 'apply_settings'):
            obj.apply_settings(opts[name])
        else:
            if hasattr(obj, 'apply_settings_attrs'):
                obj.apply_settings_attrs(opts[name])
            else:
                for k, v in opts[name].items():
                    setattr(obj, k, v)


def _whitesp_sub(m):
    return re.sub(config_whitesp_pat, '', m.group(0))


def dump_config(filename, data):
    # s = json.dumps(data, sort_keys=True, indent=4, separators=(',', ': '))
    # s = re.sub(config_list_pat, _whitesp_sub, s)
    with open(filename, 'w') as fh:
        fh.write(yaml_dumps(data))


def populate_dump_config(filename, classes, from_file=True):
    opts = populate_config(filename, classes, from_file=from_file)
    dump_config(filename, opts)
    return opts


def create_doc_listener(
        sphinx_app, package, directory='data', filename='config_attrs.json'):
    '''Creates a listener for the ``__settings_attrs__`` attributes and dumps
    their docs to ``directory/filename`` for package.

    To us, in the sphinx conf.py file do::

        def setup(app):
            create_doc_listener(app, package)

    where ``package`` is the module for which the docs are generated.

    After docs generation the generated ``directory/filename`` must be
    committed manually to the repo.
    '''
    fname = join(package.__path__[0], directory, filename)
    try:
        with open(fname) as fh:
            data = json.load(fh)
    except IOError:
        data = {}

    def config_attrs_doc_listener(app, what, name, obj, options, lines):
        if not name.startswith(package.__name__):
            return

        if what == 'class':
            if hasattr(obj, '__settings_attrs__'):
                for c, attrs in _get_classses_settings_attrs(obj).items():
                    if not c.startswith(package.__name__):
                        continue
                    if name not in data:
                        data[name] = {n: [] for n in attrs}
                    else:
                        cls_data = data[name]
                        for n in attrs:
                            if n not in cls_data:
                                cls_data[n] = []
        elif what == 'attribute':
            parts = name.split('.')
            cls = '.'.join(parts[:-1])
            if cls in data and parts[-1] in data[cls]:
                data[cls][parts[-1]] = lines

    def dump_config_attrs_doc(app, exception):
        with open(fname, 'w') as fh:
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
    flat_clsses = {}
    for name, cls in classes.items():
        if isinstance(cls, (list, tuple)):
            for i, c in enumerate(cls):
                flat_clsses['{} - {}'.format(name, i)] = c
        elif isinstance(cls, dict):
            for k, c in cls.items():
                flat_clsses['{} - {}'.format(name, k)] = c
        else:
            flat_clsses[name] = cls

    for name, cls in flat_clsses.items():
        if isinstance(cls, string_types):
            cls = getattr(knspace, cls)
        if not isclass(cls):
            cls = cls.__class__
        if not _get_settings_attrs(cls):
            continue

        docs_used[name] = _get_classses_settings_attrs(cls)
        for c in docs_used[name]:
            mod = c.split('.')[0]
            packages[mod] = import_module(mod)

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
    '''Walks through all the configurable classes of this experiment
    (should be gotten from
    :meth:`~cplcom.moa.app.ExperimentApp.get_config_classes`) and loads the
    docs of those properties and generates a rst output file with all the
    tokens.

    For example in the sphinx conf.py file do::

        def setup(app):
            app.connect('build-finished', partial(write_config_attrs_rst, \
ProjectApp.get_config_classes(), project_name))

    where project_name is the project module and ProjectApp is the App
    that runs the experiment.
    '''
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
            while doc and not doc[-1].strip():
                del doc[-1]

            lines.extend([' ' + d for d in doc if d])
            lines.append('')
        lines.append('')

    lines = '\n'.join(lines)
    try:
        with open(rst_fname) as fh:
            if fh.read() == lines:
                return
    except IOError:
        pass

    with open(join(dirname(package.__path__[0]), rst_fname), 'w') as fh:
        fh.write(lines)
