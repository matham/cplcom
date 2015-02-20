'''The main module that starts the experiment.
'''

__all__ = ('ExperimentApp', 'run_app')

# TODO: fix restart

import moa
import os
from os.path import dirname, join, isfile, expanduser
import traceback
if not os.environ.get('SPHINX_DOC_INCLUDE', None):
    from kivy.config import Config
    Config.set('kivy', 'exit_on_escape', 0)
    Config.set('kivy', 'multitouch_on_demand', 1)

from kivy.properties import (
    ObjectProperty, OptionProperty, ConfigParserProperty, StringProperty,
    BooleanProperty, NumericProperty, ListProperty)
from kivy import resources
from kivy.modules import inspector
from kivy.core.window import Window
from kivy.animation import Sequence, Animation
from kivy.resources import resource_add_path
from kivy.lang import Factory

from moa.app import MoaApp
from moa.compat import unicode_type
from moa.config import ConfigParser
from moa.logger import Logger

from cplcom import device_config_name, exp_config_name
from cplcom.graphics import ErrorPopup


class ExperimentApp(MoaApp):
    '''The app which runs the experiment.
    '''

    app_state = OptionProperty(
        'clear', options=('clear', 'exception', 'paused', 'running'))
    ''' The current app state. Can be one of `'clear'`, `'exception'`,
    `'paused'`, or `'running'`. The state controls which buttons are active.
    '''

    exception_value = StringProperty('')
    '''The text of the current/last exception.
    '''

    recovery_path = ConfigParserProperty('', 'App', 'recovery_path',
        device_config_name, val_type=unicode_type)
    '''The directory path to where the recovery files are saved.

    Defaults to `''`
    '''

    recovery_file = ConfigParserProperty('', 'App', 'recovery_file',
        device_config_name, val_type=unicode_type)
    '''The last recovery file written. Used to recover the experiment.

    Defaults to `''`
    '''

    dev_configparser = ObjectProperty(None)
    '''The :class:`ConfigParser` instance used for configuring the devices /
    system. The config file used with this instance is `'config.ini'`.
    '''

    experiment_configparser = ObjectProperty(None)
    '''The :class:`ConfigParser` instance used for configuring the experimental
    parameters. Changing the file will only have an effect on the parameters
    if changing while the experiment is stopped.
    '''

    exp_config_path = ConfigParserProperty('', 'Experiment',
        'exp_config_path', device_config_name, val_type=unicode_type)
    '''The path to the config file used with :attr:`experiment_configparser`.

    Defaults to `'experiment.ini'`. This ini file contains the configuration
    for the experiment, e.g. ITI times etc.
    '''

    simulate = BooleanProperty(False)
    '''If True, virtual devices will be used for the experiment. Otherwise
    actual Barst devices will be used. Useful for testing.
    '''

    err_popup = ObjectProperty(None)
    '''Contains the error popup object.
    '''

    popup_anim = None
    '''Contains the animation used to display that an error exists.
    '''

    base_stage = ObjectProperty(None, allownone=True, rebind=True)
    '''The instance of the :class:`RootStage`. This is the experiment's
    root stage.
    '''

    next_animal_btn = ObjectProperty(None, rebind=True)
    '''The button that is pressed when the we should do the next animal.
    '''

    simulation_devices = ObjectProperty(None)
    '''The base widget that contains all the buttons that simulate / display
    the device state.
    '''

    inspect = BooleanProperty(False)

    def __init__(self, **kw):
        super(ExperimentApp, self).__init__(**kw)
        self.recovery_directory = self.recovery_path
        resource_add_path(join(dirname(dirname(__file__)), 'media'))

    def build(self, root_cls=None):
        if root_cls is None:
            root = Factory.get('MainView')()
        else:
            root = root_cls()
        self.err_popup = ErrorPopup()
        self.popup_anim = Sequence(Animation(t='in_bounce', warn_alpha=1.),
                                   Animation(t='out_bounce', warn_alpha=0))
        self.popup_anim.repeat = True
        if root is not None and self.inspect:
            inspector.create_inspector(Window, root)
        return root

    def start_stage(self, root_cls=None, restart=False):
        '''Called to start the experiment. If restart is True, it'll try to
        recover the experiment using :attr:`recovery_file`.

        It creates and starts the :class:`RootStage`.
        '''
        self.exception_value = ''
        try:
            self.barst_stage = None
            self.app_state = 'running'
            self.base_stage = None

            old_exp_path = self.exp_config_path
            parser = self.dev_configparser
            config_path = resources.resource_find('config.ini')
            if parser is None:
                parser = self.dev_configparser = \
                    ConfigParser(name=device_config_name)

            data_directory = expanduser(self.data_directory)
            if not config_path:
                config_path = join(data_directory, 'config.ini')
                with open(config_path, 'w'):
                    pass
            parser.read(config_path)
            parser.write()
            if old_exp_path:
                self.exp_config_path = old_exp_path

            parser = self.experiment_configparser
            config_path = resources.resource_find(self.exp_config_path)
            if parser is None:
                parser = self.experiment_configparser = \
                    ConfigParser(name=exp_config_name)
            if not config_path:
                self.exp_config_path = config_path = join(
                    data_directory, 'experiment.ini')
                with open(config_path, 'w'):
                    pass
            parser.read(config_path)
            parser.write()

            if root_cls is None:
                root = self.base_stage = Factory.get('RootStage')()
            else:
                root = self.base_stage = root_cls()
        except Exception as e:
            self.exception_value = '{}\n\n\n{}'.format(e,
                                                       traceback.format_exc())
            Logger.exception(self.exception_value)
            self.app_state = 'clear'
            return

        if restart and isfile(self.recovery_file):
            self.load_attributes(self.recovery_file, stage=root)
        root.step_stage()

    def device_exception(self, exception, traceback=None, *largs):
        '''Called whenever an exception is caught in the experiment or devices.

        It stops the experiment and notifies of the exception. It also saves
        the current state for recovery.

        :parameters:

            `exception`: 2-tuple
                The first element is the caught exception, the second element
                is the traceback.
        '''
        if self.app_state == 'exception':
            return
        self.app_state = 'exception'
        self.exception_value = '{}\n\n\n{}'.format(exception, traceback)
        Logger.exception(self.exception_value)

        root = self.base_stage
        if root is not None and self.recovery_directory:
            self.recovery_file = self.dump_attributes(
                prefix='experiment_', stage=root)
        if root:
            root.stop()


def run_app(cls):
    '''Entrance method used to start the GUI. It creates and runs
    :class:`ExperimentApp`.
    '''
    app = cls()
    try:
        app.run()
    except Exception as e:
        app.device_exception((e, traceback.format_exc()))

    root = app.base_stage
    if root:
        root.stop()
