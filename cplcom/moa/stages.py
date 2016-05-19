'''Stages
=========
'''

from moa.stage import MoaStage


class ConfigStageBase(MoaStage):
    '''The base class for the root stage of experiments.

    Every experiment must have a :attr:`moa.app.MoaApp.root_stage`. This root
    stage should inherit from this :class:`ConfigStageBase` class and it should
    be named ``RootStage``.
    '''

    @classmethod
    def get_config_classes(cls):
        '''Method called by the :class:`cplcom.moa.app.ExperimentApp` to get
        all the classes that have configuration data. This should be
        overwritten by the dervied class.

        :returns:

            A dict whose keys are configuration names and whose values are
            a class, a class instance, or a string which when called as the
            attribute of the namespace
            :attr:`~kivy.uix.behaviors.knspace.knspace` e.g.
            ``getattr(knspace, name)``returns a class or instance.

            These classes all should have ``__settings_attrs__`` attributes
            that are inspected for configuration parameters.
        '''
        return {}
