
__all__ = ('FTDISerializerDevice', 'FTDIPinDevice', 'FTDIADCDevice')

from pybarst.ftdi import FTDIChannel
from pybarst.ftdi.switch import SerializerSettings, PinSettings
from pybarst.ftdi.adc import ADCSettings

from kivy.properties import NumericProperty, DictProperty

from moa.threads import ScheduledEventLoop
from moa.device.digital import ButtonViewPort
from moa.device.adc import ADCPort
from moa.compat import bytes_type
from moa.logger import Logger
from moa.base import MoaBase
from moa.utils import ConfigPropertyList, to_bool

from cplcom.device import DeviceStageInterface
from cplcom import device_config_name


class FTDIDevChannel(MoaBase, DeviceStageInterface, ScheduledEventLoop):
    '''FTDI channel device. This controls internally both the odor
    and ftdi pin devices.
    '''

    def create_device(self, devs, server, *largs, **kwargs):
        '''See :meth:`DeviceStageInterface.create_device`.

        `dev_settings` is the list of device setting to be passed to the
        Barst ftdi channel. `server` is the Barst server.
        '''
        self.devs = devs[:]
        self.target = FTDIChannel(
            channels=[
                dev.get_settings() for dev in devs], server=server.target,
            desc=self.ftdi_desc[self.idx], serial=self.ftdi_serial[self.idx])

    def start_channel(self):
        self.target.open_channel(alloc=True)
        self.target.close_channel_server()
        devs = self.target.open_channel(alloc=True)
        for moadev, ftdev in zip(self.devs, devs):
            moadev.target = ftdev
            moadev.start_channel()

    def stop_channel(self, *largs, **kwargs):
        self.target.close_channel_server()

    ftdi_serial = ConfigPropertyList(
        b'', 'FTDI_chan', 'serial_number', device_config_name,
        val_type=bytes_type)
    '''The serial number if the FTDI hardware board. Can be empty.
    '''

    ftdi_desc = ConfigPropertyList(
        b'', 'FTDI_chan', 'description_id', device_config_name,
        val_type=bytes_type)
    '''The description of the FTDI hardware board.

    :attr:`ftdi_serial` or :attr:`ftdi_desc` are used to locate the correct
    board to open. An example is `'Alder Board'` for the Alder board.
    '''

    idx = NumericProperty(0)

    devs = []


class FTDISerializerDevice(
        ButtonViewPort, DeviceStageInterface, ScheduledEventLoop):

    _read_event = None
    ''' Because we cannot control the order in which the scheduling thread
    executes requests, during the time when a read cancel is scheduled we
    cannot add a new read request, in case the read is done before the
    scheduled cancel.
    '''

    clock_size = 20

    def __init__(self, **kwargs):
        super(FTDISerializerDevice, self).__init__(**kwargs)
        self.cls_method = False

        def write_callback(result, kw_in):
            high = kw_in['set_high']
            low = kw_in['set_low']
            dev_map = self.chan_dev_map
            self.timestamp = result

            for idx in high:
                setattr(self, dev_map[idx], True)
            for idx in low:
                setattr(self, dev_map[idx], False)
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='write', callback=write_callback, trigger=False, repeat=True)

        def read_callback(result, **kwargs):
            t, val = result
            self.timestamp = t
            for idx, name in self.chan_dev_map.iteritems():
                setattr(self, name, val[idx])
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='read', callback=read_callback, trigger=False, repeat=True)

    def get_settings(self):
        '''Returns the :class:`SerializerSettings` instance used to create the
        Barst FTDI odor device.
        '''
        return SerializerSettings(
            clock_bit=self.clock_bit[self.idx],
            data_bit=self.data_bit[self.idx],
            latch_bit=self.latch_bit[self.idx],
            num_boards=self.num_boards[self.idx], output=True,
            clock_size=self.clock_size)

    def start_channel(self):
        odors = self.target
        odors.open_channel()
        odors.set_state(True)
        odors.write(set_low=range(8 * self.num_boards[self.idx]))

    def stop_channel(self, *largs, **kwargs):
        self.target.write(set_low=range(8 * self.num_boards[self.idx]))

    def set_state(self, high=[], low=[], **kwargs):
        if self.activation != 'active':
            raise TypeError('Can only set state of an active device. Device '
                            'is currently "{}"'.format(self.activation))
        if 'o' not in self.direction:
            raise TypeError('Cannot write state for a input device')
        dev_map = self.dev_map
        self.request_callback('write',
                              set_high=[dev_map[name] for name in high],
                              set_low=[dev_map[name] for name in low])

    def activate(self, *largs, **kwargs):
        if self.activation == 'deactivating':
            raise TypeError('Cannot activate while deactivating')
        if not super(FTDISerializerDevice, self).activate(*largs, **kwargs):
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
        if not super(FTDISerializerDevice, self).deactivate(*largs, **kwargs):
            return False
        if 'i' not in self.direction:
            self.activation = 'inactive'
            return True

        self.remove_request('read', self._read_event)
        self._read_event = None
        if self.target.settings.continuous:
            def post_cancel(result, *largs):
                self.activation = 'inactive'
            self.request_callback(
                'cancel_read', callback=post_cancel, flush=True)
        else:
            self.activation = 'inactive'
        return True

    num_boards = ConfigPropertyList(
        1, 'FTDI_odor', 'num_boards', device_config_name, val_type=int)
    '''The number of valve boards connected to the FTDI device.

    Each board controls 8 valves. Defaults to 2.
    '''

    clock_bit = ConfigPropertyList(
        0, 'FTDI_odor', 'clock_bit', device_config_name, val_type=int)
    '''The pin on the FTDI board to which the valve's clock bit is connected.

    Defaults to zero.
    '''

    data_bit = ConfigPropertyList(
        0, 'FTDI_odor', 'data_bit', device_config_name, val_type=int)
    '''The pin on the FTDI board to which the valve's data bit is connected.

    Defaults to zero.
    '''

    latch_bit = ConfigPropertyList(
        0, 'FTDI_odor', 'latch_bit', device_config_name, val_type=int)
    '''The pin on the FTDI board to which the valve's latch bit is connected.

    Defaults to zero.
    '''

    idx = NumericProperty(0)


class FTDIPinDevice(ButtonViewPort, DeviceStageInterface, ScheduledEventLoop):

    _read_event = None

    def __init__(self, **kwargs):
        super(FTDIPinDevice, self).__init__(**kwargs)
        self.cls_method = False

        def write_callback(result, kw_in):
            _, value, mask = kw_in['data'][0]
            self.timestamp = result
            for idx, name in self.chan_dev_map.iteritems():
                if mask & (1 << idx):
                    setattr(self, name, bool(value & (1 << idx)))
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='write', callback=write_callback, trigger=False, repeat=True)

        def read_callback(result, **kwargs):
            t, (val, ) = result
            self.timestamp = t
            mask = self.target.settings.bitmask
            for idx, name in self.chan_dev_map.iteritems():
                if mask & (1 << idx):
                    setattr(self, name, bool(val & (1 << idx)))
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='read', callback=read_callback, trigger=False, repeat=True)

    def get_settings(self):
        '''Returns the :class:`SerializerSettings` instance used to create the
        Barst FTDI odor device.
        '''
        return PinSettings(**self.init_vals)

    def start_channel(self):
        pin = self.target
        pin.open_channel()
        pin.set_state(True)

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

        self.request_callback('write', data=[(1, val, mask)])

    def activate(self, *largs, **kwargs):
        if self.activation == 'deactivating':
            raise TypeError('Cannot activate while deactivating')
        if not super(FTDIPinDevice, self).activate(*largs, **kwargs):
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
        if not super(FTDIPinDevice, self).deactivate(*largs, **kwargs):
            return False
        if 'i' not in self.direction:
            self.activation = 'inactive'
            return True

        self.remove_request('read', self._read_event)
        self._read_event = None
        if self.target.settings.continuous:
            def post_cancel(result, *largs):
                self.activation = 'inactive'
            self.request_callback(
                'cancel_read', callback=post_cancel, flush=True)
        else:
            self.activation = 'inactive'
        return True

    init_vals = {
        'num_bytes': 1, 'bitmask': 0, 'init_val': 0, 'continuous': 0,
        'output': True}

    idx = NumericProperty(0)


class FTDIADCDevice(DeviceStageInterface, ScheduledEventLoop, ADCPort):

    _read_event = None
    _state_event = None

    def __init__(self, **kwargs):
        super(FTDIADCDevice, self).__init__(**kwargs)
        self.cls_method = False
        i = self.idx
        self.bit_depth = self.data_width[i]
        self.frequency = self.sampling_rate[i]
        self.num_channels = 2
        self.active_channels = [self.chan1_active[i], self.chan2_active[i]]
        self.raw_data = [None, None]
        self.data = [None, None]
        self.ts_idx = [0, 0]

        def read_callback(result, **kwargs):
            self.timestamp = result.ts
            self.raw_data[0] = result.chan1_raw
            self.raw_data[1] = result.chan2_raw
            self.ts_idx[0] = result.chan1_ts_idx
            self.ts_idx[1] = result.chan2_ts_idx
            self.data[0] = result.chan1_data
            self.data[1] = result.chan2_data
            self.dispatch('on_data_update', self)
        self.request_callback(
            name='read', callback=read_callback, trigger=False, repeat=True)

    def get_settings(self):
        i = self.idx
        return ADCSettings(
            clock_bit=self.clock_bit[i], lowest_bit=self.lowest_bit[i],
            num_bits=self.num_bits[i], sampling_rate=self.sampling_rate[i],
            chan1=self.chan1_active[i], chan2=self.chan2_active[i],
            transfer_size=self.transfer_size[i], data_width=self.data_width[i])

    def start_channel(self, *largs, **kwargs):
        self.target.open_channel()

    def post_start_channel(self, *largs, **kwargs):
        adc = self.target
        self.frequency = adc.settings.sampling_rate
        self.bit_depth, self.scale, self.offset = adc.get_conversion_factors()
#         adc.set_state(True)
#         adc.read()
#         adc.set_state(False)
#         try:
#             adc.read()
#         except:
#             pass

    def stop_channel(self, *largs, **kwargs):
        pass

    def _set_state(self, *largs):
        # when active, start reading.
        self._read_event = self.request_callback(name='read', repeat=True)

    def activate(self, *largs, **kwargs):
        if self.activation == 'deactivating':
            raise TypeError('Cannot activate while deactivating')
        if not super(FTDIADCDevice, self).activate(*largs, **kwargs):
            return False

        # first set state to active
        self._state_event = self.request_callback(
            name='set_state', callback=self._set_state, state=True)
        return True

    def deactivate(self, *largs, **kwargs):
        '''This device will not deactivate immediately.
        '''
        if self.activation == 'activating':
            raise TypeError('Cannot deactivate while activating')
        kwargs['state'] = 'deactivating'
        if not super(FTDIADCDevice, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request('read', self._read_event)
        self.remove_request('set_state', self._state_event)
        self._read_event = None
        self._state_event = None

        def post_cancel(result, *largs):
            try:
                self.target.read()
                Logger.debug("I guess it didn't crash!")
            except:
                pass
            self.activation = 'inactive'
        self.request_callback('set_state', callback=post_cancel, state=False)
        return True

    clock_bit = ConfigPropertyList(
        0, 'FTDI_ADC', 'clock_bit', device_config_name, val_type=int)

    lowest_bit = ConfigPropertyList(
        0, 'FTDI_ADC', 'lowest_bit', device_config_name, val_type=int)

    num_bits = ConfigPropertyList(
        0, 'FTDI_ADC', 'num_bits', device_config_name, val_type=int)

    sampling_rate = ConfigPropertyList(
        1000, 'FTDI_ADC', 'sampling_rate', device_config_name, val_type=float)

    data_width = ConfigPropertyList(
        24, 'FTDI_ADC', 'data_width', device_config_name, val_type=int)

    chan1_active = ConfigPropertyList(
        True, 'FTDI_ADC', 'chan1_active', device_config_name, val_type=to_bool)

    chan2_active = ConfigPropertyList(
        False, 'FTDI_ADC', 'chan2_active', device_config_name,
        val_type=to_bool)

    transfer_size = ConfigPropertyList(
        1000, 'FTDI_ADC', 'transfer_size', device_config_name, val_type=int)

    idx = NumericProperty(0)
