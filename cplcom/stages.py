from functools import partial

from kivy.app import App
from kivy.clock import Clock

from moa.stage import MoaStage
from moa.threads import ScheduledEventLoop


class InitStage(MoaStage, ScheduledEventLoop):

    # if a device is currently being initialized by the secondary thread.
    _finished_init = False
    # if while a device is initialized, stage should stop when finished.
    _should_stop = None

    exception_callback = None
    '''The partial function that has been scheduled to be called by the kivy
    thread when an exception occurs. This function must be unscheduled when
    stopping, in case there are waiting to be called after it already has been
    stopped.
    '''

    def __init__(self, **kw):
        super(InitStage, self).__init__(**kw)
        self.exclude_attrs = ['finished']

    def clear(self, *largs, **kwargs):
        self._finished_init = False
        self._should_stop = None
        return super(InitStage, self).clear(*largs, **kwargs)

    def unpause(self, *largs, **kwargs):
        # if simulating, we cannot be in pause state
        if super(InitStage, self).unpause(*largs, **kwargs):
            if self._finished_init:
                # when unpausing, just continue where we were
                self.finish_init()
            return True
        return False

    def stop(self, *largs, **kwargs):
        if self.started and not self._finished_init and not self.finished:
            self._should_stop = largs, kwargs
            return False
        return super(InitStage, self).stop(*largs, **kwargs)

    def step_stage(self, *largs, **kwargs):
        if not super(InitStage, self).step_stage(*largs, **kwargs):
            return False

        # if we simulate, create them and step immediately
        try:
            if App.get_running_app().simulate:
                self.start_init(sim=True)
                self.step_stage()
            else:
                self.start_init(sim=False)
                self.request_callback(
                    'init_threaded', callback=self.finish_init)
        except Exception as e:
            App.get_running_app().device_exception(e)

        return True

    def start_init(self, sim=True, devs=[]):
        if sim and devs:
            for dev in devs:
                if dev is not None:
                    dev.activate(self)

    def init_threaded(self, devs=[]):
        for dev in devs:
            if dev is not None:
                dev.start_channel()

    def finish_init(self, devs=[], *largs):
        self._finished_init = True
        should_stop = self._should_stop
        if should_stop is not None:
            super(InitStage, self).stop(*should_stop[0], **should_stop[1])
            return
        if self.paused:
            return

        for dev in devs:
            if dev is not None:
                dev.post_start_channel()
                dev.activate(self)
        self.step_stage()

    def handle_exception(self, exception, event):
        '''The overwritten method called by the devices when they encounter
        an exception.
        '''
        callback = self.exception_callback = partial(
            App.get_running_app().device_exception, exception, event)
        Clock.schedule_once(callback)

    def stop_devices(self, devs=[]):
        for dev in devs:
            if dev is not None:
                dev.deactivate(self)

        Clock.unschedule(self.exception_callback)
        self.clear_events()
        self.stop_thread(join=True)

        if App.get_running_app().simulate:
            self.clear_app()
            return

        for dev in devs:
            if dev is not None:
                dev.stop_device()

        self.start_thread()
        self.request_callback(
            'stop_devices_internal', callback=self.clear_app, cls_method=True,
            devs=devs)

    def clear_app(self, *l):
        App.get_running_app().app_state = 'clear'

    def stop_devices_internal(self, devs=[]):
        '''Called from :class:`InitBarstStage` internal thread. It stops
        and clears the states of all the devices.
        '''
        for dev in devs:
            try:
                if dev is not None:
                    dev.stop_channel()
            except:
                pass
        self.stop_thread()
