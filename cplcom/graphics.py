
__all__ = ('VirtualSwitch', )


import math

from kivy.uix.widget import Widget
from kivy.uix.gridlayout import GridLayout
from kivy.uix.behaviors import ToggleButtonBehavior
from kivy.lang import Factory
from kivy.properties import (
        ObjectProperty, StringProperty, NumericProperty, BooleanProperty)
from kivy.clock import Clock


class LabeledIcon(Widget):
    pass


class VirtualSwitch(object):
    '''Requires it be combined with class that has a state property.
    '''

    def __init__(self, **kw):
        super(VirtualSwitch, self).__init__(**kw)
        Clock.schedule_once(self._bind_button)

    def _bind_button(self, *largs):
        if (not self.read_only and not self.virtual):
            self.bind(state=self.update_from_button)

    dev = ObjectProperty(None, allownone=True)

    _dev = None

    chan_name = StringProperty('state')

    read_only = BooleanProperty(False)
    '''Whether pressing the button will change the device state (False) or
    if the device only updates the button.
    '''

    virtual = BooleanProperty(False)
    '''If it's backed up by a button. Similar to app.simulate, but even if
    that's false it could be kivy button backed.
    '''

    is_port = BooleanProperty(True)

    _last_chan_value = None

    def on_dev(self, *largs):
        if self._dev:
            self._dev.unbind(**{self.chan_name: self.update_from_channel})
        self._dev = self.dev
        if (self.dev and not self.virtual):
            self.dev.bind(**{self.chan_name: self.update_from_channel})

    def update_from_channel(self, *largs):
        '''A convenience method which takes the state of the simulated device
        (buttons) and the state of the actual device and returns if the
        simulated device should be `'down'` or `'normal'`.

        It is used to set the button state to match the actual device state,
        if not simulating.
        '''

        self._last_chan_value = state = getattr(self.dev, self.chan_name)
        self.state = 'down' if state else 'normal'
        self._last_chan_value = None

    def update_from_button(self, *largs):
        '''A convenience method which takes the state of the simulated device
        (buttons) and sets the state of the actual device to match it when not
        simulating.
        '''
        dev = self.dev
        if dev is not None:
            if self.state == 'down':
                if self._last_chan_value is not True:
                    self._last_chan_value = None
                    if self.is_port:
                        dev.set_state(high=[self.chan_name])
                    else:
                        dev.set_state(True)
            else:
                if self._last_chan_value is not False:
                    self._last_chan_value = None
                    if self.is_port:
                        dev.set_state(low=[self.chan_name])
                    else:
                        dev.set_state(False)


class ToggleSwitch(ToggleButtonBehavior, VirtualSwitch, LabeledIcon):
    pass


class PortSwitch(ToggleSwitch):
    pass


class DarkPortSwitch(PortSwitch):
    pass


class PortContainer(GridLayout):

    num_devs = NumericProperty(8)

    name_pat = StringProperty('p{}')

    def __init__(self, **kwargs):
        super(PortContainer, self).__init__(**kwargs)
        if '__no_builder' in kwargs:
            Clock.schedule_once(self.populate_devs)
        else:
            self.populate_devs()

    def populate_devs(self, *largs):
        classes = [PortSwitch, DarkPortSwitch] * int(
            math.ceil(self.num_devs / 2.))
        pat = self.name_pat
        for i, cls in enumerate(classes):
            self.add_widget(cls(chan_name=pat.format(i)))

Factory.register('VirtualSwitch', cls=VirtualSwitch)
