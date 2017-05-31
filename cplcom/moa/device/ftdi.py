'''Barst FTDI Wrapper
=====================
'''
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
    '''A :class:`moa.device.Device` wrapper around a
    :class:`pybarst.ftdi.FTDIChannel` instance and controls the
    :class:`FTDISerializerDevice`, :class:`FTDIPinDevice`, and the
    :class:`FTDIADCDevice` instances.
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
    '''The serial number of the FTDI hardware board. Can be empty if
    :attr:`ftdi_desc` is provided.
    '''

    ftdi_desc = StringProperty('')
    '''The description of the FTDI hardware board. This a name written to the
    hardware device.

    :attr:`ftdi_serial` or :attr:`ftdi_desc` are used to locate the correct
    board to open. An example is `'Alder Board'` for the Alder board.
    '''

    server = ObjectProperty(None, allownone=True)
    '''The internal barst :class:`pybarst.core.server.BarstServer`. It
    must be provided to the instance.
    '''

    chan = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.FTDIChannel` instance.
    It is read only and is automatically created.
    '''

    devs = ListProperty([])
    '''A list of the :class:`FTDISerializerDevice`, :class:`FTDIPinDevice`, and
    the :class:`FTDIADCDevice` instances connected to this channel.
    '''

    restart = BooleanProperty(True)
    '''If True we will restart the channel if it already exists. Should be set
    to False if multiple users of the channel exist.

    Defaults to ``True``
    '''


class FTDISerializerDevice(DeviceExceptionBehavior, ButtonViewPort,
                           ScheduledEventLoop):
    '''A :class:`moa.device.digital.ButtonViewPort` wrapper around a
    :class:`pybarst.ftdi.switch.FTDISerializerIn` or
    :class:`pybarst.ftdi.switch.FTDISerializerOut` instance
    (depending on the value of :attr:`output`).

    For this class, :class:`moa.device.digital.ButtonViewPort.dev_map` must be
    provided upon creation and it's a dict whose keys are the property names
    and whose values are the serial device's port numbers that the
    property controls.

    E.g. for a group of odors connected to channel 3-4 output port, define the
    class::

        class MyFTDISerializerDevice(FTDISerializerDevice):

            p3 = BooleanProperty(False)
            p4 = BooleanProperty(False)

        And then create the instance with::

            dev = FTDISerializerDevice(dev_map={'p3': 3, 'p4': 4})

        And then we can set the state by calling e.g.::

            dev.set_state(high=['p3'], low=['p4'])

    For an input serial devices it can defined similarly and the state of the
    property reflects the value of the port.
    '''

    __settings_attrs__ = (
        'clock_size', 'num_boards', 'clock_bit', 'data_bit', 'latch_bit',
        'output')

    _read_event = None
    _write_event = None

    def __init__(self, **kwargs):
        super(FTDISerializerDevice, self).__init__(**kwargs)
        self.direction = 'o' if self.output else 'i'
        self.settings = SerializerSettings(
            clock_bit=self.clock_bit, data_bit=self.data_bit,
            latch_bit=self.latch_bit, num_boards=self.num_boards,
            output=self.output, clock_size=self.clock_size)

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
        for idx, name in self.chan_dev_map.items():
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
        odors.write(set_low=list(range(8 * self.num_boards)))

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
        chan.write(set_low=list(range(8 * self.num_boards)))
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
    '''The hardware clock width used to clock out data. Defaults to 20.
    '''

    num_boards = NumericProperty(1)
    '''The number of serial boards connected in series to the FTDI device.

    Each board is a 8-channel port. Defaults to 1.
    '''

    clock_bit = NumericProperty(0)
    '''The pin on the FTDI board to which the serial device's clock bit is
    connected.

    Defaults to zero.
    '''

    data_bit = NumericProperty(0)
    '''The pin on the FTDI board to which the serial device's data bit is
    connected.

    Defaults to zero.
    '''

    latch_bit = NumericProperty(0)
    '''The pin on the FTDI board to which the serial device's latch bit is
    connected.

    Defaults to zero.
    '''

    output = BooleanProperty(True)
    '''Whether the serial device is a output or input device. If input a
    :class:`pybarst.ftdi.switch.FTDISerializerIn` will be used, otherwise a
    :class:`pybarst.ftdi.switch.FTDISerializerOut` will be used.
    '''

    chan = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.switch.FTDISerializerIn` or
    :class:`pybarst.ftdi.switch.FTDISerializerOut` instance.
    It is read only and is automatically created.
    '''

    settings = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.switch.SerializerSettings` instance.
    It is read only and is automatically created.
    '''


class FTDIPinDevice(DeviceExceptionBehavior, ButtonViewPort,
                    ScheduledEventLoop):
    '''A :class:`moa.device.digital.ButtonViewPort` wrapper around a
    :class:`pybarst.ftdi.switch.FTDIPinIn` or
    :class:`pybarst.ftdi.switch.FTDIPinOut` instance
    (depending on the value of :attr:`output`).

    For this class, :class:`moa.device.digital.ButtonViewPort.dev_map` must be
    provided upon creation and it's a dict whose keys are the property names
    and whose values are the pin device's port numbers that the
    property controls.

    E.g. for a light and feeder connected to channel 3-4 output port, define
    the class::

        class MyFTDIPinDevice(FTDIPinDevice):

            light = BooleanProperty(False)
            feeder = BooleanProperty(False)

        And then create the instance with::

            dev = MyFTDIPinDevice(dev_map={'light': 3, 'feeder': 4})

        And then we can set the state by calling e.g.::

            dev.set_state(high=['light'], low=['feeder'])

    For an input pin device it can defined similarly and the state of the
    property reflects the value of the port. If the device has both input
    and outputs two :class:`FTDIPinDevice` must be created each controlling
    only the inputs and outputs respectively.
    '''

    _read_event = None
    _write_event = None

    def __init__(self, **kwargs):
        super(FTDIPinDevice, self).__init__(**kwargs)
        self.direction = 'o' if self.output else 'i'
        self.settings = PinSettings(
            num_bytes=self.num_bytes, bitmask=self.bitmask,
            init_val=self.init_val, continuous=self.continuous,
            output=self.output)

    def _write_callback(self, result, kw_in):
        _, value, mask = kw_in['data'][0]
        self.timestamp = result
        for idx, name in self.chan_dev_map.items():
            if mask & (1 << idx):
                setattr(self, name, bool(value & (1 << idx)))
        self.dispatch('on_data_update', self)

    def _read_callback(self, result, **kwargs):
        t, (val, ) = result
        self.timestamp = t
        mask = self.bitmask
        for idx, name in self.chan_dev_map.items():
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
    '''The number of bytes that will be read from the USB bus for each read
    request. Defaults to 1.
    '''

    bitmask = NumericProperty(0)
    '''A bit-mask of the pins that are active for this device, either as input
    or output depending on the pin type. The high bits will be the active pins
    for this device. E.g. if it's ``0b01000100`` and this is a output device,
    it means that pins 2, and 6 are output pins and are controlled by this
    device. The other pins will not be under the device's control.

    Defaults to zero.
    '''

    init_val = NumericProperty(0)
    '''If this is an output device, it sets the initial values (high/low) of
    the device's active pins, otherwise it's ignored. For example if pins 1,
    and 5 are under control of the device, and the value is 0b01001011, then
    pin 1 will be initialized to high and pin 5 to low.

    Defaults to zero.
    '''

    continuous = BooleanProperty(False)
    '''Whether, when reading, we should continuously read data from the device.
    This is only used for a input device (:attr:`output` is False).
    '''

    output = BooleanProperty(True)
    '''Whether the serial device is a output or input device. If input a
    :class:`pybarst.ftdi.switch.FTDIPinIn` will be used, otherwise a
    :class:`pybarst.ftdi.switch.FTDIPinOut` will be used.
    '''

    chan = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.switch.FTDIPinIn` or
    :class:`pybarst.ftdi.switch.FTDIPinOut` instance.
    It is read only and is automatically created.
    '''

    settings = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.switch.PinSettings` instance.
    It is read only and is automatically created.
    '''


class FTDIADCDevice(DeviceExceptionBehavior, ADCPort, ScheduledEventLoop):
    '''A :class:`moa.device.adc.ADCPort` wrapper around a
    :class:`pybarst.ftdi.adc.FTDIADC`.
    '''

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
    '''The pin to which the clock line of the ADC device is connected at the
    FTDI channel. Typically between 0 - 7. Defaults to 0.
    '''

    lowest_bit = NumericProperty(0)
    '''Defines which pins on the FTDI USB bus are data pins. The data pins are
    connected to the FTDI bus starting from pin number :attr:`lowest_bit` until
    :attr:`lowest_bit` + :attr:`num_bits`. Defaults to 0.
    '''

    num_bits = NumericProperty(2)
    '''Indicates the number of pins on the FTDI bus that are connected to the
    ADC data port. Range is [2, 8]. See :attr:`lowest_bit`.
    Defaults to 2.
    '''

    sampling_rate = NumericProperty(1000.)
    '''The requested sampling rate used by the ADC device for each channel.
    The value controls both channels. The available sampling rates is a
    function of all the other device options.

    Initially one sets it to the desired value. Before becoming activated it's
    automatically updated to the actual sampling rate using the closest found
    rate.

    Defaults to 1000.
    '''

    data_width = NumericProperty(24)
    '''The bit depth of each data point read by the ADC device. Acceptable
    values are either 16, or 24. Defaults to 24.
    '''

    chan1_active = BooleanProperty(True)
    '''Indicates whether channel 1 should be active and read and send back
    data. Defaults to ``True``.
    '''

    chan2_active = BooleanProperty(False)
    '''Indicates whether channel 2 should be active and read and send back
    data. Defaults to ``False``.
    '''

    transfer_size = NumericProperty(1000)
    '''This parameter allows you to control over how often the ADC sends data
    read back. The server will wait until :attr:`transfer_size` data points for
    each channel (if two channels are active) has been accumulated and than
    sends :attr:`transfer_size` (for each channel) data points to the client.
    '''

    chan = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.adc.FTDIADC` instance.
    It is read only and is automatically created.
    '''

    settings = ObjectProperty(None)
    '''The internal :class:`pybarst.ftdi.adc.ADCSettings` instance.
    It is read only and is automatically created.
    '''
