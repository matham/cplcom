

__all__ = ('MCDAQDevice', )

from pybarst.mcdaq import MCDAQChannel

from kivy.properties import NumericProperty

from moa.threads import ScheduledEventLoop
from moa.device.digital import ButtonViewPort
from moa.utils import ConfigPropertyList

from cplcom.device import DeviceStageInterface
from cplcom import device_config_name


class MCDAQDevice(DeviceStageInterface, ButtonViewPort, ScheduledEventLoop):

    _read_event = None

    def __init__(self, **kwargs):
        super(MCDAQDevice, self).__init__(**kwargs)
        self.cls_method = False

        def write_callback(result, kw_in):
            value = kw_in['value']
            mask = kw_in['mask']
            self.timestamp = result
            for idx, name in self.chan_dev_map.iteritems():
                if mask & (1 << idx):
                    setattr(self, name, bool(value & (1 << idx)))
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='write', callback=write_callback, trigger=False, repeat=True)

        def read_callback(result, **kwargs):
            t, val = result
            self.timestamp = t
            for idx, name in self.chan_dev_map.iteritems():
                setattr(self, name, bool(val & (1 << idx)))
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='read', callback=read_callback, trigger=False, repeat=True)

    def create_device(self, server, *largs, **kwargs):
        self.target = MCDAQChannel(chan=self.SAS_chan[self.idx],
                                   server=server.target)

    def start_channel(self):
        target = self.target
        target.open_channel()
        target.close_channel_server()
        target.open_channel()
        if 'o' in self.direction:
            target.write(mask=0xFF, value=0)

    def stop_channel(self, *largs, **kwargs):
        if 'o' in self.direction:
            self.target.write(mask=0xFF, value=0)

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

        self.request_callback('write', mask=mask, value=val)

    def get_state(self):
        if self.activation != 'active':
            raise TypeError('Can only read state of an active device. Device '
                            'is currently "{}"'.format(self.activation))
        if 'i' in self.direction:
            return
        self._read_event = self.request_callback(name='read')

    def activate(self, *largs, **kwargs):
        if self.activation == 'deactivating':
            raise TypeError('Cannot activate while deactivating')
        if not super(MCDAQDevice, self).activate(*largs, **kwargs):
            return False

        if 'i' in self.direction:
            self._read_event = self.request_callback(name='read', repeat=True)
        return True

    def deactivate(self, *largs, **kwargs):
        '''This device may not deactivate immediately.
        '''
        if self.activation == 'activating':
            raise TypeError('Cannot deactivate while activating')
        kwargs['state'] = 'deactivating'
        if not super(MCDAQDevice, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request('read', self._read_event)
        self._read_event = None
        if 'i' in self.direction and self.target.continuous:
            def post_cancel(result, *largs):
                self.activation = 'inactive'
            self.request_callback('cancel_read', callback=post_cancel,
                                  flush=True)
        else:
            self.activation = 'inactive'
        return True

    SAS_chan = ConfigPropertyList(
        0, 'Switch_and_Sense_8_8', 'channel_number', device_config_name,
        val_type=int, autofill=False)
    '''`channel_number`, the channel number of the Switch & Sense 8/8 as
    configured in InstaCal.

    Defaults to zero.
    '''

    idx = NumericProperty(0)
