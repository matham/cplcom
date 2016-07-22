'''Moa App
===========

The app that starts an experiment.
'''

# TODO: fix restart
import inspect
import moa
from cplcom.app import CPLComApp, app_error, run_app

from os.path import dirname, join, isfile, isdir
from kivy.properties import (
    ObjectProperty, OptionProperty, ConfigParserProperty, StringProperty,
    BooleanProperty, NumericProperty, ListProperty)
from kivy.factory import Factory
from kivy.resources import resource_add_path
from kivy.lang import Builder

from moa.compat import unicode_type
from moa.app import MoaApp
from moa.logger import Logger

from cplcom import config_name


__all__ = ('ExperimentApp', )

Builder.load_file(join(dirname(__file__), 'graphics.kv'))


class ExperimentApp(CPLComApp, MoaApp):
    '''The base app which runs the experiment.
    '''

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

    _close_massage = 'Cannot close while experiment is running'

    @classmethod
    def get_config_classes(cls):
        d = super(ExperimentApp, cls).get_config_classes()
        if cls != ExperimentApp and Factory.RootStage:
            d.update(Factory.RootStage.get_config_classes())
        return d

    def __init__(self, **kw):
        def update_recovery(*l):
            self.recovery_directory = self.recovery_path
            self.recovery_filename = self.recovery_file
        self.fbind('recovery_path', update_recovery)
        self.fbind('recovery_file', update_recovery)
        d = self.data_path
        if isdir(d):
            self.data_directory = d
            resource_add_path(self.data_directory)
        super(ExperimentApp, self).__init__(**kw)

    def check_close(self):
        return not (self.root_stage and self.root_stage.started and
                    not self.root_stage.finished)

    def set_recovery(self, path, selection, filename):
        '''Sets the json config file when selected from the file browser.

        Signature matches the :class:`PopupBrowser` callback signature so it
        can be set as its callback.
        '''
        if not isdir(path) or not filename:
            return
        self.recovery_file = join(path, filename)

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

        if root_cls is None:
            root = self.root_stage = Factory.get('RootStage')()
        else:
            root = self.root_stage = root_cls()

        self.load_json_config()

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
        '''Similar to its base class behavior.

        It also stops the experiment and saves the current state for recovery.
        '''
        super(ExperimentApp, self).handle_exception(
            exception, exc_info=exc_info, event=event, obj=obj, *largs)
        self.stop_experiment()

    def get_logger(self):
        return Logger
