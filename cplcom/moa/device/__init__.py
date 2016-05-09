
from functools import partial
import traceback

from kivy.app import App
from kivy.clock import Clock

from moa.threads import ScheduledEventLoop

__all__ = ('DeviceExceptionBehavior', )


class DeviceExceptionBehavior(object):
    ''' Base class for devices used in this project. It provides the callback
    on exception functionality which calls
    :meth:`ExperimentApp.device_exception` when an exception occurs.

    It must ensure the exception is done by kivy thread when restarting app.
    '''

    def handle_exception(self, exception, event=None):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = partial(
            App.get_running_app().handle_exception, exception[0], exception[1],
            event, self)
        Clock.schedule_once(callback)
