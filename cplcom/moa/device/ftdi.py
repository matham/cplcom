
from pybarst.ftdi import FTDIChannel
from pybarst.ftdi.switch import SerializerSettings, PinSettings
from pybarst.ftdi.adc import ADCSettings

from kivy.properties import NumericProperty, DictProperty, StringProperty, \
    ListProperty, ObjectProperty, BooleanProperty

from moa.threads import ScheduledEventLoop
from moa.device.digital import ButtonViewPort
from moa.device.adc import ADCPort
from moa.logger import Logger
from moa.device import Device
from cplcom.moa.device import DeviceExceptionBehavior

__all__ = ('FTDIDevChannel', 'FTDISerializerDevice', 'FTDIPinDevice',
           'FTDIADCDevice')


class FTDIDevChannel(DeviceExceptionBehavior, Device, ScheduledEventLoop):
    '''FTDI channel device. This controls internally both the odor
    and ftdi pin devices.
    '''

    __settings_attrs__ = ('ftdi_serial', 'ftdi_desc')

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(FTDIDevChannel, self).activate(*largs, **kwargs):
            return False
        self.start_thread()
        self.chan = FTDIChannel(
            channels=[dev.settings for dev in self.devs],
            server=self.server.server, desc=self.ftdi_desc,
            serial=self.ftdi_serial)

        def finish_activate(*largs):
            self.activation = 'active'
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self):
        if self.restart:
            self.chan.open_channel(alloc=True)
            self.chan.close_channel_server()

        devs = self.chan.open_channel(alloc=True)
        for moadev, ftdev in zip(self.devs, devs):
            moadev.chan = ftdev

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(FTDIDevChannel, self).deactivate(*largs, **kwargs):
            return False

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self.chan.close_channel_server,
                              finish_deactivate)
        return True

    ftdi_serial = StringProperty('')
    '''The serial number if the FTDI hardware board. Can be empty.
    '''

    ftdi_desc = StringProperty('')
    '''The description of the FTDI hardware board.

    :attr:`ftdi_serial` or :attr:`ftdi_desc` are used to locate the correct
    board to open. An example is `'Alder Board'` for the Alder board.
    '''

    server = ObjectProperty(None, allownone=True)

    chan = ObjectProperty(None)

    devs = ListProperty([])

    restart = BooleanProperty(True)


class FTDISerializerDevice(DeviceExceptionBehavior, ButtonViewPort,
                           ScheduledEventLoop):

    __settings_attrs__ = (
        'clock_size', 'num_boards', 'clock_bit', 'data_bit', 'latch_bit')

    _read_event = None
    _write_event = None

    def __init__(self, **kwargs):
        super(FTDISerializerDevice, self).__init__(**kwargs)
        self.settings = SerializerSettings(
            clock_bit=self.clock_bit, data_bit=self.data_bit,
            latch_bit=self.latch_bit, num_boards=self.num_boards, output=True,
            clock_size=self.clock_size)

    def _write_callback(self, result, kw_in):
        high = kw_in['set_high']
        low = kw_in['set_low']
        dev_map = self.chan_dev_map
        self.timestamp = result

        for idx in high:
            setattr(self, dev_map[idx], True)
        for idx in low:
            setattr(self, dev_map[idx], False)
        self.dispatch('on_data_update', self)

    def _read_callback(self, result, **kwargs):
        t, val = result
        self.timestamp = t
        for idx, name in self.chan_dev_map.iteritems():
            setattr(self, name, val[idx])
        self.dispatch('on_data_update', self)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(FTDISerializerDevice, self).activate(*largs, **kwargs):
            return False
        self.start_thread()

        def finish_activate(*largs):
            self.activation = 'active'
            self._write_event = self.request_callback(
                self.chan.write, callback=self._write_callback, trigger=False,
                repeat=True)
            if 'i' in self.direction:
                self._read_event = self.request_callback(
                    self.chan.read, callback=self._read_callback, trigger=True,
                    repeat=True)
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self):
        odors = self.chan
        odors.open_channel()
        odors.set_state(True)
        odors.write(set_low=range(8 * self.num_boards))

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(FTDISerializerDevice, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request(self.chan.read, self._read_event)
        self.remove_request(self.chan.write, self._write_event)
        self._write_event = self._read_event = None

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._stop_channel, finish_deactivate)
        return True

    def _stop_channel(self, *largs, **kwargs):
        chan = self.chan
        chan.write(set_low=range(8 * self.num_boards))
        if self.settings.continuous:
            chan.cancel_read(flush=True)
        chan.set_state(False)
        chan.close_channel_client()

    def set_state(self, high=[], low=[], **kwargs):
        if 'o' not in self.direction:
            raise TypeError('Cannot write state for a input device')
        dev_map = self.dev_map
        self.request_callback(self.chan.write,
                              set_high=[dev_map[name] for name in high],
                              set_low=[dev_map[name] for name in low])

    clock_size = NumericProperty(20)

    num_boards = NumericProperty(1)
    '''The number of valve boards connected to the FTDI device.

    Each board controls 8 valves. Defaults to 2.
    '''

    clock_bit = NumericProperty(0)
    '''The pin on the FTDI board to which the valve's clock bit is connected.

    Defaults to zero.
    '''

    data_bit = NumericProperty(0)
    '''The pin on the FTDI board to which the valve's data bit is connected.

    Defaults to zero.
    '''

    latch_bit = NumericProperty(0)
    '''The pin on the FTDI board to which the valve's latch bit is connected.

    Defaults to zero.
    '''

    chan = ObjectProperty(None)

    settings = ObjectProperty(None)


class FTDIPinDevice(DeviceExceptionBehavior, ButtonViewPort,
                    ScheduledEventLoop):

    _read_event = None
    _write_event = None

    def __init__(self, **kwargs):
        super(FTDIPinDevice, self).__init__(**kwargs)
        self.settings = PinSettings(
            num_bytes=self.num_bytes, bitmask=self.bitmask,
            init_val=self.init_val, continuous=self.continuous,
            output=self.output)

    def _write_callback(self, result, kw_in):
        _, value, mask = kw_in['data'][0]
        self.timestamp = result
        for idx, name in self.chan_dev_map.iteritems():
            if mask & (1 << idx):
                setattr(self, name, bool(value & (1 << idx)))
        self.dispatch('on_data_update', self)

    def _read_callback(self, result, **kwargs):
        t, (val, ) = result
        self.timestamp = t
        mask = self.bitmask
        for idx, name in self.chan_dev_map.iteritems():
            if mask & (1 << idx):
                setattr(self, name, bool(val & (1 << idx)))
        self.dispatch('on_data_update', self)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(FTDIPinDevice, self).activate(*largs, **kwargs):
            return False
        self.start_thread()

        def finish_activate(*largs):
            self.activation = 'active'
            self._write_event = self.request_callback(
                self.chan.write, callback=self._write_callback, trigger=False,
                repeat=True)
            if 'i' in self.direction:
                self._read_event = self.request_callback(
                    self.chan.read, callback=self._read_callback, trigger=True,
                    repeat=True)
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self):
        pin = self.chan
        pin.open_channel()
        pin.set_state(True)

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(FTDIPinDevice, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request(self.chan.read, self._read_event)
        self.remove_request(self.chan.write, self._write_event)
        self._write_event = self._read_event = None

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._stop_channel, finish_deactivate)
        return True

    def _stop_channel(self, *largs, **kwargs):
        chan = self.chan
        if self.settings.continuous:
            chan.cancel_read(flush=True)
        chan.set_state(False)
        chan.close_channel_client()

    def set_state(self, high=[], low=[], **kwargs):
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

        self.request_callback(self.chan.write, data=[(1, val, mask)])

    num_bytes = NumericProperty(1)

    bitmask = NumericProperty(0)

    init_val = NumericProperty(0)

    continuous = BooleanProperty(False)

    output = BooleanProperty(True)

    chan = ObjectProperty(None)

    settings = ObjectProperty(None)


class FTDIADCDevice(DeviceExceptionBehavior, ADCPort, ScheduledEventLoop):

    __settings_attrs__ = (
        'clock_bit', 'lowest_bit', 'num_bits', 'sampling_rate', 'data_width',
        'chan1_active', 'chan2_active')

    _read_event = None

    def __init__(self, **kwargs):
        super(FTDIADCDevice, self).__init__(**kwargs)
        self.bit_depth = self.data_width
        self.frequency = self.sampling_rate
        self.num_channels = 2
        self.active_channels = [self.chan1_active, self.chan2_active]
        self.raw_data = [None, None]
        self.data = [None, None]
        self.ts_idx = [0, 0]

        self.settings = ADCSettings(
            clock_bit=self.clock_bit, lowest_bit=self.lowest_bit,
            num_bits=self.num_bits, sampling_rate=self.sampling_rate,
            chan1=self.chan1_active, chan2=self.chan2_active,
            transfer_size=self.transfer_size, data_width=self.data_width)

    def _read_callback(self, result, **kwargs):
        self.timestamp = result.ts
        self.raw_data[0] = result.chan1_raw
        self.raw_data[1] = result.chan2_raw
        self.ts_idx[0] = result.chan1_ts_idx
        self.ts_idx[1] = result.chan2_ts_idx
        self.data[0] = result.chan1_data
        self.data[1] = result.chan2_data
        self.dispatch('on_data_update', self)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(FTDIADCDevice, self).activate(*largs, **kwargs):
            return False
        self.start_thread()

        def finish_activate(*largs):
            self.frequency = self.chan.settings.sampling_rate
            self.bit_depth, self.scale, self.offset = \
                self.chan.get_conversion_factors()
            self.activation = 'active'
            self._read_event = self.request_callback(
                self.chan.read, callback=self._read_callback, repeat=True)
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self):
        adc = self.chan
        adc.open_channel()
        adc.set_state(True)

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(FTDIADCDevice, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request(self.chan.read, self._read_event)
        self._read_event = None

        def finish_deactivate(*largs):
            try:
                self.chan.read()
                Logger.debug("I guess it didn't crash!")
            except:
                pass
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._stop_channel, finish_deactivate)
        return True

    def _stop_channel(self, *largs, **kwargs):
        chan = self.chan
        chan.set_state(False)
        chan.close_channel_client()

    clock_bit = NumericProperty(0)

    lowest_bit = NumericProperty(0)

    num_bits = NumericProperty(0)

    sampling_rate = NumericProperty(1000.)

    data_width = NumericProperty(24)

    chan1_active = BooleanProperty(True)

    chan2_active = BooleanProperty(False)

    transfer_size = NumericProperty(1000)

    chan = ObjectProperty(None)

    settings = ObjectProperty(None)
