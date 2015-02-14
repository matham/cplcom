
from functools import partial
import traceback

from kivy.app import App
from kivy.clock import Clock

from moa.threads import ScheduledEventLoop


class DeviceStageInterface(object):
    ''' Base class for devices used in this project. It provides the callback
    on exception functionality which calls
    :meth:`ExperimentApp.device_exception` when an exception occurs.
    '''

    exception_callback = None
    '''The partial function that has been scheduled to be called by the kivy
    thread when an exception occurs. This function must be unscheduled when
    stopping, in case there are waiting to be called after it already has been
    stopped.
    '''

    def handle_exception(self, exception, event=None):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = self.exception_callback = partial(
            App.get_running_app().device_exception, exception,
            traceback.format_exc(), event)
        Clock.schedule_once(callback)

    def cancel_exception(self):
        '''Called to cancel the potentially scheduled exception, scheduled with
        :meth:`handle_exception`.
        '''
        Clock.unschedule(self.exception_callback)
        self.exception_callback = None

    def create_device(self, *largs, **kwargs):
        '''Called from the kivy thread to create the internal target of this
        device.
        '''
        pass

    def start_channel(self, *largs, **kwargs):
        '''Called from secondary thread to initialize the target device. This
        is typically called after :meth:`create_device` is called.
        This method typically opens e.g. the Barst channels on the server and
        sets them to their initial values.
        '''
        pass

    def stop_device(self, *largs, **kwargs):
        self.cancel_exception()
        if isinstance(self, ScheduledEventLoop):
            self.stop_thread(join=True)
            self.clear_events()

    def stop_channel(self, *largs, **kwargs):
        pass
