
from pybarst.mcdaq import MCDAQChannel

from kivy.properties import NumericProperty, ObjectProperty

from moa.threads import ScheduledEventLoop
from moa.device.digital import ButtonViewPort
from cplcom.moa.device import DeviceExceptionBehavior

__all__ = ('MCDAQDevice', )


class MCDAQDevice(DeviceExceptionBehavior, ButtonViewPort, ScheduledEventLoop):

    __settings_attrs__ = ('SAS_chan', )

    _read_event = None

    def _write_callback(self, result, kw_in):
        value = kw_in['value']
        mask = kw_in['mask']
        self.timestamp = result
        for idx, name in self.chan_dev_map.iteritems():
            if mask & (1 << idx):
                setattr(self, name, bool(value & (1 << idx)))
        self.dispatch('on_data_update', self)

    def _read_callback(self, result, **kwargs):
        t, val = result
        self.timestamp = t
        for idx, name in self.chan_dev_map.iteritems():
            setattr(self, name, bool(val & (1 << idx)))
        self.dispatch('on_data_update', self)

    def set_state(self, high=[], low=[], **kwargs):
        if self.activation != 'active':
            raise TypeError('Can only set state of an active device. Device '
                            'is currently "{}"'.format(self.activation))
        if 'o' not in self.direction:
            raise TypeError('Cannot write state for a input device')
        dev_map = self.dev_map
        mask = 0
        val = 0
        for name in high:
            idx = dev_map[name]
            val |= (1 << idx)
            mask |= (1 << idx)
        for name in low:
            mask |= (1 << dev_map[name])

        self.request_callback(self.chan.write, callback=self._write_callback,
                              mask=mask, value=val)

    def get_state(self):
        if self.activation != 'active':
            raise TypeError('Can only read state of an active device. Device '
                            'is currently "{}"'.format(self.activation))
        if 'i' in self.direction:  # happens anyway
            return
        self._read_event = self.request_callback(
            self.chan.read, callback=self._read_callback)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(MCDAQDevice, self).activate(*largs, **kwargs):
            return False
        self.start_thread()
        self.chan = MCDAQChannel(chan=self.SAS_chan, server=self.server.server)

        def finish_activate(*largs):
            self.activation = 'active'
            if 'i' in self.direction:
                self._read_event = self.request_callback(
                    self.chan.read, repeat=True, callback=self._read_callback)
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self):
        chan = self.chan
        chan.open_channel()
        if 'o' in self.direction:
            chan.write(mask=0xFF, value=0)

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(MCDAQDevice, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request(self.chan.read, self._read_event)
        self._read_event = None

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._stop_channel, finish_deactivate)
        return True

    def _stop_channel(self):
        if 'o' in self.direction:
            self.chan.write(mask=0xFF, value=0)
        if 'i' in self.direction and self.chan.continuous:
            self.chan.cancel_read(flush=True)

    chan = ObjectProperty(None)

    server = ObjectProperty(None, allownone=True)

    SAS_chan = NumericProperty(0)
    '''`channel_number`, the channel number of the Switch & Sense 8/8 as
    configured in InstaCal.

    Defaults to zero.
    '''
