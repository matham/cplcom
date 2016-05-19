'''Moa Device
==============

:mod:`cplcom.moa.device` serves as a :mod:`moa.device` wrapper for devices
commonly used in CPL.

All of the devices are wrapped such that CPU consuming activities occur on
separate threads and do not block the main thread.
'''

from functools import partial
import traceback

from kivy.app import App
from kivy.clock import Clock

from moa.threads import ScheduledEventLoop

__all__ = ('DeviceExceptionBehavior', )


class DeviceExceptionBehavior(object):
    ''' Base class for devices used in this project. It provides the callback
    on exception functionality which automatically calls
    :meth:`~cplcom.moa.app.ExperimentApp.handle_exception` when an exception
    occurs on the secondary thread if the class inherits from
    :class:`~moa.threads.ScheduledEventLoop`.
    '''

    def handle_exception(self, exception, event=None):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = partial(
            App.get_running_app().handle_exception, exception[0], exception[1],
            event, self)
        Clock.schedule_once(callback)
