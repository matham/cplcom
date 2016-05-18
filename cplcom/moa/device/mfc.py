'''Barst Serial AALBORG MFC Wrapper
======================================
'''
import re

from kivy.properties import ObjectProperty, StringProperty, NumericProperty

from pybarst.serial import SerialChannel

from moa.threads import ScheduledEventLoop
from moa.device.analog import NumericPropertyViewChannel
from cplcom.moa.device import DeviceExceptionBehavior

__all__ = ('MFC', )


class MFC(DeviceExceptionBehavior, NumericPropertyViewChannel,
          ScheduledEventLoop):
    '''A :class:`moa.device.analog.NumericPropertyViewChannel` wrapper around a
    :class:`pybarst.serial.SerialChannel` instance which controls a AALBORG
    MFC.
    '''

    __settings_attrs__ = ('port_name', 'mfc_id')

    port_name = StringProperty('')
    '''The COM port name of the MFC, e.g. COM3.
    '''

    mfc_id = NumericProperty(0)
    '''The MFC assigned decimal number used to communicate with that MFC.
    '''

    server = ObjectProperty(None, allownone=True)
    '''The internal barst :class:`pybarst.core.server.BarstServer`. It
    must be provided to the instance.
    '''

    mfc_timeout = NumericProperty(4000)
    '''How long to wait before the MFC times out. Defaults to 4000 ms.
    '''

    chan = ObjectProperty(None)
    '''The internal :class:`pybarst.serial.SerialChannel` instance.
    It is read only and is automatically created.
    '''

    _read_event = None
    _rate_pat = None

    def _set_mfc_rate(self, val=0):
        mfc = self.chan
        n = self.mfc_id
        to = self.mfc_timeout

        mfc.write('!{:02X},S,{:.3f}\r\n'.format(n, val), to)
        rate_out = '!{:02X},S{:.3f}\r\n'.format(n, val)
        _, val = mfc.read(len(rate_out), to)
        if val != rate_out:
            raise Exception('Failed setting MFC rate. '
                            'Expected "{}", got "{}"'.format(rate_out, val))

    def _get_mfc_rate(self):
        mfc = self.chan
        n = self.mfc_id
        to = self.mfc_timeout

        mfc.write('!{:02X},F\r\n'.format(n), to)
        t, val = mfc.read(24, stop_char='\n', timeout=to)
        m = re.match(self._rate_pat, val)
        if m is None:
            return t, -1.
        return t, float(m.group(1))

    def _set_state_from_mfc(self, res):
        self.timestamp = res[0]
        self.state = res[1]
        self.dispatch('on_data_update', self)

    def set_state(self, state, **kwargs):
        self.request_callback(self._set_mfc_rate, val=state)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(MFC, self).activate(*largs, **kwargs):
            return False

        self.start_thread()
        self.chan = SerialChannel(
            server=self.server.server, port_name=self.port_name,
            max_write=96, max_read=96, baud_rate=9600, stop_bits=1,
            parity='none', byte_size=8)
        self._rate_pat = re.compile(
            r'\!{:02X},([0-9\.]+)\r\n'.format(self.mfc_id))

        def finish_activate(*largs):
            self.activation = 'active'
            self._read_event = self.request_callback(
                self._get_mfc_rate, callback=self._set_state_from_mfc,
                repeat=True)
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self, *largs, **kwargs):
        mfc = self.chan
        n = self.mfc_id
        to = self.mfc_timeout
        mfc.open_channel()

        # set digital mode
        mfc.write('!{:02X},M,D\r\n'.format(n), to)
        dig_out = '!{:02X},MD\r\n'.format(n)
        _, val = mfc.read(len(dig_out), to)
        if val != dig_out:
            raise Exception('Failed setting MFC to digital mode. '
                            'Expected "{}", got "{}"'.format(dig_out, val))

        # set to standard LPM
        mfc.write('!{:02X},U,SLPM\r\n'.format(n), to)
        units_out = '!{:02X},USLPM\r\n'.format(n)
        _, val = mfc.read(len(units_out), to)
        if val != units_out:
            raise Exception('Failed setting MFC to use SLPM units. '
                            'Expected "{}", got "{}"'.format(units_out, val))
        self._set_mfc_rate(0)

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(MFC, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request(self._get_mfc_rate, self._read_event)
        self._read_event = None

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._set_mfc_rate, finish_deactivate)
        return True
