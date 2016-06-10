'''App
========

The app that starts an experiment.
'''

# TODO: fix restart

import moa
import os
import sys
import json
from os.path import dirname, join, isfile, expanduser, isdir
from os import environ
environ['MOA_CLOCK'] = '1'

from kivy.properties import (
    ObjectProperty, OptionProperty, ConfigParserProperty, StringProperty,
    BooleanProperty, NumericProperty, ListProperty)
from kivy import resources
from kivy.modules import inspector
from kivy.core.window import Window
from kivy.resources import resource_add_path
from kivy.factory import Factory
from kivy.uix.behaviors.knspace import knspace
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.base import ExceptionManager, ExceptionHandler
from kivy.lang import Builder

from moa.app import MoaApp
from moa.compat import unicode_type
from moa.config import ConfigParser
from moa.logger import Logger

import cplcom.graphics  # required to load kv
from cplcom.moa import config_name
from cplcom.moa.config import populate_config, apply_config, dump_config
from cplcom.utils import byteify

if not os.environ.get('KIVY_DOC_INCLUDE', None):
    from kivy.config import Config
    Config.set('kivy', 'exit_on_escape', 0)
    Config.set('kivy', 'multitouch_on_demand', 1)

__all__ = ('ExperimentApp', 'run_app', 'app_error')

Builder.load_file(join(dirname(__file__), 'graphics.kv'))


def app_error(app_error_func):
    '''A decorator which wraps the function in `try...except` and calls
    :meth:`ExperimentApp.handle_exception` when a exception is raised.

    E.g.::

        @app_error
        def do_something():
            do_something
    '''
    def safe_func(*largs, **kwargs):
        try:
            return app_error_func(*largs, **kwargs)
        except Exception as e:
            knspace.app.handle_exception(e, exc_info=sys.exc_info())

    return safe_func


class ExperimentApp(MoaApp):
    '''The base app which runs the experiment.
    '''

    __settings_attrs__ = ('inspect', )

    recovery_path = ConfigParserProperty(
        '', 'App', 'recovery_path', config_name, val_type=unicode_type)
    '''The directory path to where the recovery files are saved. Its
    value is passed to :attr:`~moa.app.MoaApp.recovery_directory`.s

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
    '''The full path to the config file used for the experiment.

    Defaults to `'experiment.ini'`. This ini file contains the configuration
    for the experiment, e.g. trial times etc.
    '''

    app_settings = ObjectProperty({})
    '''A dict that contains the :mod:`cplcom.moa.config` settings for the
    experiment for all the configurable classes. See that module for details.

    The keys in the dict are configuration names for a class (similarly to what
    is returned by
    :meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes`) and its
    values are dicts whose keys are class attributes names and values are their
    values. These attributes are the ones listed in ``__settings_attrs__``. See
    :mod:`cplcom.moa.config` for how configuration works.
    '''

    error_indicator = ObjectProperty(None)
    '''The error indicator that gets the error reports. The experiment GUI
    should set :attr:`error_indicator` to the
    :class:`cplcom.graphics.ErrorIndicator` instance used in the experiment
    abd it will be used to diplay errors and warnings.
    '''

    inspect = BooleanProperty(False)
    '''Enables GUI inspection. If True, it is activated by hitting ctrl-e in
    the GUI.
    '''

    filebrowser = ObjectProperty(None)
    '''Stores a instance of :class:`PopupBrowser` that is automatically created
    by this app class. That class is described in ``cplcom/graphics.kv``.
    '''

    _close_popup = ObjectProperty(None)

    @classmethod
    def get_config_classes(cls):
        '''Similar to
        :meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes` it
        returns all the configurable classes of the experiment. It gets all
        the configurable classes using
        :meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes` as well
        as the current app class.
        '''
        d = {'app': cls}
        if cls != ExperimentApp and Factory.RootStage:
            d.update(Factory.RootStage.get_config_classes())
        return d

    def __init__(self, **kw):
        super(ExperimentApp, self).__init__(**kw)

        def update_recovery(*l):
            self.recovery_directory = self.recovery_path
            self.recovery_filename = self.recovery_file
        self.fbind('recovery_path', update_recovery)
        self.fbind('recovery_file', update_recovery)

        self.knsname = 'app'
        if isdir(self.data_directory):
            resource_add_path(self.data_directory)
        resource_add_path(join(dirname(dirname(dirname(__file__))), 'media'))
        self.filebrowser = Factory.PopupBrowser()
        self._close_popup = Popup(
            title='Cannot close',
            content=Label(text='Cannot close while experiment is running'),
            size_hint=(.8, .8))

        parser = self.configparser
        if parser is None:
            parser = self.configparser = ConfigParser(name=config_name)

        data_directory = self.data_directory
        config_path = resources.resource_find('config.ini')
        if not config_path:
            config_path = join(data_directory, 'config.ini')
            with open(config_path, 'w'):
                pass

        parser.read(config_path)
        parser.write()

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

    def _ask_close(self, *largs, **kwargs):
        if (self.root_stage and self.root_stage.started and
                not self.root_stage.finished):
            self._close_popup.open()
            return True
        return False

    def set_json_file(self, path, selection, filename):
        '''Sets the json config file when selected from the file browser.

        Signature matches the :class:`PopupBrowser` callback signature so it
        can be set as its callback.
        '''
        if not isdir(path) or not filename:
            return
        self.json_config_path = join(path, filename)

    def set_recovery(self, path, selection, filename):
        '''Sets the json config file when selected from the file browser.

        Signature matches the :class:`PopupBrowser` callback signature so it
        can be set as its callback.
        '''
        if not isdir(path) or not filename:
            return
        self.json_config_path = join(path, filename)

    @app_error
    def start_stage(self, root_cls=None, recover=False):
        '''Should be called by the app to start the experiment.

        :Parameters:

            `root_cls`: :class:`moa.stage.MoaStage` based class
                The root stage to be used in the experiment.
                If None, we will look for a class called `RootStage` in the
                kivy Factory.

                Defaults to None.
            `recover`: bool
                If we should recover the experiment using
                :attr:`recovery_file`. Defaults to False.
        '''
        self.root_stage = None

        settings = self.json_config_path
        if not isfile(settings):
            dump_config(settings, self.app_settings)

        if root_cls is None:
            root = self.root_stage = Factory.get('RootStage')()
        else:
            root = self.root_stage = root_cls()

        classes = self.get_config_classes()
        new_opts = populate_config(settings, classes)

        dump_config(settings, new_opts)
        self.app_settings = new_opts

        for k, v in new_opts['app'].items():
            setattr(self, k, v)

        if recover and isfile(self.recovery_file):
            self.load_recovery()
            self.recovery_file = self.recovery_filename = ''
        root.step_stage()

    def stop_experiment(self, stage=None, recovery=True):
        '''Can be called to stop the experiment and dump recovery information.

        :Parameters:

            `stage`: :class:`~moa.stage.MoaStage`
                The stage to stop. If None, the default,
                :attr:`~moa.app.MoaApp.root_stage` is stopped.
            `recovery`: bool
                Whether recovery info should be dumped to file. Defaults to
                True.
        '''
        root = self.root_stage
        if recovery and root is not None and root.started and \
                not root.finished and self.recovery_directory:
            self.recovery_file = self.dump_recovery(prefix='experiment_')

        if root and not root.finished:
            (stage or root).stop()
        else:
            self.clean_up_root_stage()

    def clean_up_root_stage(self):
        '''Class that is and should be called after the
        :attr:`~moa.app.MoaApp.root_stage` is stopped. It performs some
        cleanup.
        '''
        self.root_stage = None

    def handle_exception(self, exception, exc_info=None, event=None, obj=None,
                         *largs):
        '''Should be called whenever an exception is caught in the experiment
        or devices.

        It stops the experiment and notifies of the exception
        (using :attr:`error_indicator`). It also saves the current state for
        recovery.

        :parameters:

            `exception`: string
                The caught exception (i.e. the ``e`` in
                ``except Exception as e``)
            `exc_info`: stack trace
                If not None, the return value of ``sys.exc_info()``. It is used
                to log the stack trace.
            `event`: :class:`moa.threads.ScheduledEvent` instance
                If not None and the exception originated from within a
                :class:`moa.threads.ScheduledEventLoop`, it's the
                :class:`moa.threads.ScheduledEvent` that caused the execution.
            `obj`: object
                If not None, the object that caused the exception.
        '''
        if isinstance(exc_info, basestring):
            Logger.error(exception)
            Logger.error(exc_info)
        else:
            Logger.error(exception, exc_info=exc_info)
        if obj is None:
            err = exception
        else:
            err = '{} from {}'.format(exception, obj)
        self.error_indicator.add_item(str(err))
        self.stop_experiment()


class _CPLComHandler(ExceptionHandler):

    def handle_exception(self, inst):
        if getattr(knspace, 'app', None):
            knspace.app.handle_exception(inst, exc_info=sys.exc_info())
        return ExceptionManager.PASS


def run_app(cls):
    '''Entrance method used to start the experiment GUI. It creates and runs
    a :class:`ExperimentApp` type instance.
    '''
    handler = _CPLComHandler()
    ExceptionManager.add_handler(handler)

    app = cls()
    Window.fbind('on_request_close', app._ask_close)
    try:
        app.run()
    except Exception as e:
        app.handle_exception(e, exc_info=sys.exc_info())

    Window.funbind('on_request_close', app._ask_close)
    ExceptionManager.remove_handler(handler)
