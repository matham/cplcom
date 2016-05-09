'''The main module that starts the experiment.
'''

# TODO: fix restart

import moa
from inspect import isclass
import os
import sys
import json
from os.path import dirname, join, isfile, expanduser

from kivy.properties import (
    ObjectProperty, OptionProperty, ConfigParserProperty, StringProperty,
    BooleanProperty, NumericProperty, ListProperty)
from kivy import resources
from kivy.modules import inspector
from kivy.core.window import Window
from kivy.resources import resource_add_path
from kivy.factory import Factory
from kivy.uix.behaviors.knspace import knspace

from moa.app import MoaApp
from moa.compat import unicode_type
from moa.config import ConfigParser
from moa.logger import Logger

import cplcom.graphics  # required to load kv
from cplcom.moa import config_name
from cplcom.utils import byteify

if not os.environ.get('SPHINX_DOC_INCLUDE', None):
    from kivy.config import Config
    Config.set('kivy', 'exit_on_escape', 0)
    Config.set('kivy', 'multitouch_on_demand', 1)

__all__ = ('ExperimentApp', 'run_app')


def app_error(func):
    def safe_func(*largs, **kwargs):
        try:
            return func(*largs, **kwargs)
        except Exception as e:
            knspace.app.handle_exception(e, exc_info=sys.exc_info())

    return safe_func


class ExperimentApp(MoaApp):
    '''The app which runs the experiment.
    '''

    __settings_attrs__ = ('inspect', )

    recovery_path = ConfigParserProperty(
        '', 'App', 'recovery_path', config_name, val_type=unicode_type)
    '''The directory path to where the recovery files are saved.

    Defaults to `''`
    '''

    recovery_file = ConfigParserProperty(
        '', 'App', 'recovery_file', config_name, val_type=unicode_type)
    '''The last recovery file written. Used to recover the experiment.

    Defaults to `''`
    '''

    configparser = ObjectProperty(None)
    '''The :class:`ConfigParser` instance used for configuring the devices /
    system. The config file used with this instance is `'config.ini'`.
    '''

    json_config_path = ConfigParserProperty(
        'config.json', 'Experiment', 'json_config_path', config_name,
        val_type=unicode_type)
    '''The path to the config file used for the experiment.

    Defaults to `'experiment.ini'`. This ini file contains the configuration
    for the experiment, e.g. ITI times etc.
    '''

    kns_settings_names = {'app': 'app'}

    app_settings = ObjectProperty({})

    error_indicator = ObjectProperty(None)
    '''The error indicator that gets the error reports.
    '''

    inspect = BooleanProperty(False)

    filebrowser = ObjectProperty(None)

    def __init__(self, **kw):
        super(ExperimentApp, self).__init__(**kw)
        self.knsname = 'app'
        self.recovery_directory = self.recovery_path
        resource_add_path(join(dirname(dirname(dirname(__file__))), 'media'))
        self.filebrowser = Factory.PopupBrowser()

    def build(self, root_cls=None):
        if root_cls is None:
            root = Factory.get('MainView')
            if root is not None:
                root = root()
        else:
            root = root_cls()

        if root is not None and self.inspect:
            inspector.create_inspector(Window, root)
        return root

    @app_error
    def start_stage(self, root_cls=None, restart=False):
        '''Called to start the experiment. If restart is True, it'll try to
        recover the experiment using :attr:`recovery_file`.

        It creates and starts the :class:`RootStage`.
        '''
        self.root_stage = None

        parser = self.configparser
        if parser is None:
            parser = self.configparser = ConfigParser(name=config_name)

        data_directory = expanduser(self.data_directory)
        config_path = resources.resource_find('config.ini')
        if not config_path:
            config_path = join(data_directory, 'config.ini')
            with open(config_path, 'w'):
                pass

        parser.read(config_path)
        parser.write()

        settings = self.json_config_path
        if not isfile(settings):
            with open(settings, 'w') as fh:
                json.dump(self.app_settings, fh, sort_keys=True, indent=4,
                          separators=(',', ': '))

        if root_cls is None:
            root = self.root_stage = Factory.get('RootStage')()
        else:
            root = self.root_stage = root_cls()

        with open(settings) as fh:
            opts = byteify(json.load(fh))

        classes = root.get_config_classes()
        classes.update(self.kns_settings_names)
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
                for attr in obj.get_settings_attrs():
                    new_vals[attr] = opt.get(
                        attr, getattr(obj, attr).defaultvalue)
            else:
                for attr in obj.__class__.get_settings_attrs():
                    new_vals[attr] = opt.get(attr, getattr(obj, attr))

            new_opts[name] = new_vals

        with open(settings, 'w') as fh:
            json.dump(new_opts, fh, sort_keys=True, indent=4,
                      separators=(',', ': '))
        self.app_settings = new_opts

        for name, cls in classes.items():
            if isinstance(cls, basestring):
                obj = getattr(knspace, name)
            elif isclass(cls):
                continue
            else:
                obj = cls
            if not obj:
                continue

            for k, v in new_opts[name].items():
                setattr(obj, k, v)

        if restart and isfile(self.recovery_file):
            self.load_attributes(self.recovery_file, stage=root)
        root.step_stage()

    def handle_exception(self, exception, exc_info=None, event=None, obj=None,
                         *largs):
        '''Called whenever an exception is caught in the experiment or devices.

        It stops the experiment and notifies of the exception. It also saves
        the current state for recovery.

        :parameters:

            `exception`: 2-tuple
                The first element is the caught exception, the second element
                is the traceback.
        '''
        Logger.error(exception, exc_info=exc_info)
        if obj is None:
            err = exception
        else:
            err = '{} from {}'.format(exception, obj)
        self.error_indicator.queue.append(str(err))

        root = self.root_stage
        if root is not None and self.recovery_directory:
            self.recovery_file = self.dump_attributes(
                prefix='experiment_', stage=root)
        if root:
            root.stop()
            self.root_stage = None


def run_app(cls):
    '''Entrance method used to start the GUI. It creates and runs
    :class:`ExperimentApp`.
    '''
    app = cls()
    try:
        app.run()
    except Exception as e:
        app.handle_exception(e, exc_info=sys.exc_info())

    root = app.root_stage
    if root:
        root.stop()
