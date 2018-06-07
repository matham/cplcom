'''App
========

The base App class for cplcom.
'''

import os
import inspect
import sys
import json
from functools import wraps
from configparser import ConfigParser
from os.path import dirname, join, isdir


if not os.environ.get('KIVY_DOC_INCLUDE', None):
    from kivy.config import Config
    Config.set('kivy', 'exit_on_escape', 0)
    Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

from kivy.properties import ObjectProperty, StringProperty, BooleanProperty
from kivy import resources
from kivy.modules import inspector
from kivy.resources import resource_add_path
from kivy.factory import Factory
from kivy.uix.behaviors.knspace import knspace, KNSpaceBehavior
from kivy.base import ExceptionManager, ExceptionHandler
from kivy.app import App
from kivy.logger import Logger
from kivy.clock import Clock

import cplcom.graphics  # required to load kv
from cplcom.utils import ColorTheme
from cplcom.config import populate_dump_config, apply_config
if not os.environ.get('KIVY_DOC_INCLUDE', None):
    Clock.max_iteration = 20

__all__ = ('CPLComApp', 'run_app', 'app_error', 'app_error_async')


def app_error(app_error_func, error_indicator='', threaded=False):
    '''A decorator which wraps the function in `try...except` and calls
    :meth:`CPLComApp.handle_exception` when a exception is raised.

    E.g.::

        @app_error
        def do_something():
            do_something
    '''
    @wraps(app_error_func)
    def safe_func(*largs, **kwargs):
        try:
            return app_error_func(*largs, **kwargs)
        except Exception as e:
            def report_exception(*largs):
                knspace.app.handle_exception(
                    e, exc_info=sys.exc_info(),
                    error_indicator=error_indicator)

            if threaded:
                Clock.schedule_once(report_exception)
            else:
                report_exception()

    return safe_func


def app_error_async(app_error_func, error_indicator='', threaded=False):
    '''A decorator which wraps the async function in `try...except` and calls
    :meth:`CPLComApp.handle_exception` when a exception is raised.

    E.g.::

        @app_error
        async def do_something():
            do_something
    '''
    @wraps(app_error_func)
    async def safe_func(*largs, **kwargs):
        try:
            return await app_error_func(*largs, **kwargs)
        except Exception as e:
            def report_exception(*largs):
                knspace.app.handle_exception(
                    e, exc_info=sys.exc_info(),
                    error_indicator=error_indicator)

            if threaded:
                Clock.schedule_once(report_exception)
            else:
                report_exception()

    return safe_func


class CPLComApp(KNSpaceBehavior, App):
    '''The base app.
    '''

    __settings_attrs__ = ('inspect', )

    json_config_path = StringProperty('config.yaml')
    '''The full path to the config file used for the experiment.

    Defaults to `'experiment.ini'`. This ini file contains the configuration
    for the experiment, e.g. trial times etc.
    '''

    app_settings = ObjectProperty({})
    '''A dict that contains the :mod:`cplcom.config` settings for the
    experiment for all the configurable classes. See that module for details.

    The keys in the dict are configuration names for a class (similarly to what
    is returned by
    :meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes`) and its
    values are dicts whose keys are class attributes names and values are their
    values. These attributes are the ones listed in ``__settings_attrs__``. See
    :mod:`cplcom.config` for how configuration works.
    '''

    inspect = BooleanProperty(False)
    '''Enables GUI inspection. If True, it is activated by hitting ctrl-e in
    the GUI.
    '''

    error_indicator = ObjectProperty(None)
    '''The error indicator that gets the error reports. The experiment GUI
    should set :attr:`error_indicator` to the
    :class:`cplcom.graphics.ErrorIndicatorBase` instance used in the experiment
    abd it will be used to diplay errors and warnings.
    '''

    filebrowser = ObjectProperty(None)
    '''Stores a instance of :class:`PopupBrowser` that is automatically created
    by this app class. That class is described in ``cplcom/graphics.kv``.
    '''

    yesno_prompt = ObjectProperty(None)
    '''Stores a instance of :class:`YesNoPrompt` that is automatically created
    by this app class. That class is described in ``cplcom/graphics.kv``.
    '''

    theme = ObjectProperty(ColorTheme(), rebind=True)

    _close_popup = ObjectProperty(None)

    _close_message = StringProperty('Cannot close currently')

    def on__close_message(self, *largs):
        self._close_popup.text = self._close_message

    @classmethod
    def get_config_classes(cls):
        '''Similar to
        :meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes` it
        returns all the configurable classes of the experiment. It gets all
        the configurable classes using
        :meth:`~cplcom.moa.stages.ConfigStageBase.get_config_classes` as well
        as the current app class.
        '''
        if App.get_running_app():
            return {'app': App.get_running_app()}
        return {'app': cls}

    def __init__(self, **kw):
        super(CPLComApp, self).__init__(**kw)
        self.knsname = 'app'
        resource_add_path(join(dirname(__file__), 'media'))
        resource_add_path(join(dirname(__file__), 'media', 'flat'))
        self.init_load()

    def init_load(self):
        '''Creates and reads config files. Initializes widgets. Add
        media to path etc.
        '''
        d = self.data_path
        if isdir(d):
            resource_add_path(d)

        self.filebrowser = Factory.PopupBrowser()
        p = self._close_popup = Factory.ClosePopup()
        p.text = self._close_message

        parser = ConfigParser()

        if not parser.has_section('Experiment'):
            parser.add_section('Experiment')
        if not parser.has_option('Experiment', 'json_config_path'):
            parser.set('Experiment', 'json_config_path', self.json_config_path)
        filename = self.ensure_config_file('config.ini')
        parser.read(filename)
        with open(filename, 'w') as fh:
            parser.write(fh)
        self.json_config_path = parser.get('Experiment', 'json_config_path')
        self.ensure_config_file(self.json_config_path)

    def ensure_config_file(self, filename):
        if not resources.resource_find(filename):
            with open(join(self.data_path, filename), 'w') as fh:
                if filename.endswith('json'):
                    json.dump({}, fh)
        return resources.resource_find(filename)

    @property
    def data_path(self):
        '''The install dependent path to the config data.
        '''
        if hasattr(sys, '_MEIPASS'):
            if isdir(join(sys._MEIPASS, 'data')):
                return join(sys._MEIPASS, 'data')
            return sys._MEIPASS
        return join(dirname(inspect.getfile(self.__class__)), 'data')

    def load_app_settings_from_file(self):
        classes = self.get_config_classes()
        self.app_settings = populate_dump_config(
            self.ensure_config_file(self.json_config_path), classes)

        apply_config({
            'app': self.app_settings['app']}, self.get_config_classes())

    def apply_app_settings(self):
        apply_config(self.app_settings, self.get_config_classes())

    def dump_app_settings_to_file(self):
        classes = self.get_config_classes()
        populate_dump_config(self.ensure_config_file(self.json_config_path),
                             classes, from_file=False)

    def build(self, root=None):
        if root is not None and self.inspect:
            from kivy.core.window import Window
            inspector.create_inspector(Window, root)
        return root

    def _ask_close(self, *largs, **kwargs):
        if not self.check_close():
            if self._close_message:
                self._close_popup.open()
            return True
        return False

    def check_close(self):
        '''Returns whether the app can close now. Otherwise, a message telling
        the user it cannot close now with message :attr:`_close_message` will
        be shown.
        '''
        return True

    def set_json_file(self, path, selection, filename):
        '''Sets the json config file when selected from the file browser.

        Signature matches the :class:`PopupBrowser` callback signature so it
        can be set as its callback.
        '''
        if not isdir(path) or not filename:
            return
        self.json_config_path = join(path, filename)

    def handle_exception(self, msg, exc_info=None, error_indicator='',
                         level='error', *largs):
        '''Should be called whenever an exception is caught in the app.

        :parameters:

            `exception`: string
                The caught exception (i.e. the ``e`` in
                ``except Exception as e``)
            `exc_info`: stack trace
                If not None, the return value of ``sys.exc_info()``. It is used
                to log the stack trace.
        '''
        if isinstance(exc_info, str):
            self.get_logger().error(msg)
            self.get_logger().error(exc_info)
        elif level in ('error', 'exception'):
            self.get_logger().error(msg, exc_info=exc_info)
        else:
            getattr(self.get_logger(), level)(msg)

        error_indicator = error_indicator or self.error_indicator
        if not error_indicator:
            return

        if isinstance(error_indicator, str):
            error_indicator = getattr(knspace, error_indicator, None)
        if error_indicator:
            error_indicator.add_item('{}'.format(msg))

    def get_logger(self):
        return Logger


class _CPLComHandler(ExceptionHandler):

    def handle_exception(self, inst):
        app = App.get_running_app()
        if app:
            app.handle_exception(inst, exc_info=sys.exc_info())
            return ExceptionManager.PASS
        return ExceptionManager.RAISE


def run_app(cls_or_app, cleanup=None):
    '''Entrance method used to start the experiment GUI. It creates and runs
    a :class:`CPLComApp` type instance.
    '''
    from kivy.core.window import Window
    handler = _CPLComHandler()
    ExceptionManager.add_handler(handler)

    app = cls_or_app() if inspect.isclass(cls_or_app) else cls_or_app
    Window.fbind('on_request_close', app._ask_close)
    try:
        app.run()
    except Exception as e:
        app.handle_exception(e, exc_info=sys.exc_info())

    if cleanup:
        try:
            cleanup(app)
        except Exception as e:
            app.handle_exception(e, exc_info=sys.exc_info())

    Window.funbind('on_request_close', app._ask_close)
    ExceptionManager.remove_handler(handler)


async def run_app_async(cls_or_app, cleanup=None):
    '''Entrance method used to start the experiment GUI. It creates and runs
    a :class:`CPLComApp` type instance.
    '''
    from kivy.core.window import Window
    handler = _CPLComHandler()
    ExceptionManager.add_handler(handler)

    app = cls_or_app() if inspect.isclass(cls_or_app) else cls_or_app
    Window.fbind('on_request_close', app._ask_close)
    try:
        await app.async_run()
    except Exception as e:
        app.handle_exception(e, exc_info=sys.exc_info())

    if cleanup:
        try:
            cleanup(app)
        except Exception as e:
            app.handle_exception(e, exc_info=sys.exc_info())

    Window.funbind('on_request_close', app._ask_close)
    ExceptionManager.remove_handler(handler)
