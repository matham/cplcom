

__all__ = ('MFC', )

import re

from kivy.properties import ObjectProperty, StringProperty, NumericProperty

from pybarst.serial import SerialChannel

from moa.threads import ScheduledEventLoop
from moa.device.analog import NumericPropertyViewChannel
from moa.utils import ConfigPropertyList

from cplcom.device import DeviceStageInterface
from cplcom import device_config_name


class MFC(
        DeviceStageInterface, NumericPropertyViewChannel, ScheduledEventLoop):

    port_name = ConfigPropertyList(
        '', 'MFC', 'port_name', device_config_name, val_type=str,
        autofill=False)
    '''The COM port name of the MFC, e.g. COM3.
    '''

    mfc_id = ConfigPropertyList(
        0, 'MFC', 'mfc_id', device_config_name, val_type=int,
        autofill=False)
    '''The MFC assigned number used to communicate with that MFC.
    '''

    idx = NumericProperty(0)

    mfc_timeout = 4000

    _mfc_id = 0

    _read_event = None
    _rate_pat = None

    def __init__(self, **kw):
        super(MFC, self).__init__(**kw)
        self.cls_method = False

    def create_device(self, server, *largs, **kwargs):
        self.target = SerialChannel(
            server=server, port_name=self.port_name[self.idx], max_write=96,
            max_read=96, baud_rate=9600, stop_bits=1, parity='none',
            byte_size=8)
        self._mfc_id = self.mfc_id[self.idx]
        self._rate_pat = re.compile(
            r'\!{:02X},([0-9\.]+)\r\n'.format(self._mfc_id))

    def start_channel(self, *largs, **kwargs):
        mfc = self.target
        n = self._mfc_id
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
        self.set_mfc_rate(0)

    def stop_channel(self, *largs, **kwargs):
        self.set_mfc_rate(0)

    def set_mfc_rate(self, val):
        mfc = self.target
        n = self._mfc_id
        to = self.mfc_timeout

        mfc.write('!{:02X},S,{:.3f}\r\n'.format(n, val), to)
        rate_out = '!{:02X},S{:.3f}\r\n'.format(n, val)
        _, val = mfc.read(len(rate_out), to)
        if val != rate_out:
            raise Exception('Failed setting MFC rate. '
                            'Expected "{}", got "{}"'.format(rate_out, val))

    def get_mfc_rate(self):
        mfc = self.target
        n = self._mfc_id
        to = self.mfc_timeout

        mfc.write('!{:02X},F\r\n'.format(n), to)
        t, val = mfc.read(24, stop_char='\n', timeout=to)
        m = re.match(self._rate_pat, val)
        if m is None:
            raise Exception('Failed getting MFC rate. '
                            'Got "{}"'.format(val))
        return t, float(m.group(1))

    def _set_state_from_mfc(self, res):
        self.timestamp = res[0]
        self.state = res[1]
        self.dispatch('on_data_update', self)

    def set_state(self, state, **kwargs):
        self.request_callback('set_mfc_rate', val=state)

    def activate(self, *largs, **kwargs):
        if not super(MFC, self).activate(*largs, **kwargs):
            return False

        self._read_event = self.request_callback(
            name='get_mfc_rate', callback=self._set_state_from_mfc,
            repeat=True)
        return True

    def deactivate(self, *largs, **kwargs):
        if not super(MFC, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request('get_mfc_rate', self._read_event)
        self._read_event = None
        return True
