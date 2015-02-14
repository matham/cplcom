
from pybarst.rtv import RTVChannel

from kivy.properties import (
    StringProperty, ObjectProperty, NumericProperty, BooleanProperty)

from ffpyplayer.pic import Image

from moa.device.digital import ButtonChannel
from moa.threads import ScheduledEventLoop

from cplcom.device import DeviceStageInterface


class RTVChan(ButtonChannel, ScheduledEventLoop, DeviceStageInterface):
    '''Device used when using the barst ftdi odor devices.
    '''

    _read_event = None
    _state_event = None
    _state_event_off = None

    callback = ObjectProperty(None)

    output_img_fmt = StringProperty('gray')

    output_video_fmt = StringProperty('full_NTSC')

    port = NumericProperty(0)

    rate = None

    size = None

    def create_device(self, server, *largs, **kwargs):
        n = self.port
        frame_fmt = self.output_img_fmt
        video_fmt = self.output_video_fmt
        self.target = RTVChannel(
            chan=n, server=server.target, video_fmt=video_fmt,
            frame_fmt=frame_fmt, luma_filt=frame_fmt == 'gray', lossless=True)
        self.rate = (2997, 100)
        self.size = {
            'full_NTSC': (640, 480), 'full_PAL': (768, 576),
            'CIF_NTSC': (320, 240), 'CIF_PAL': (384, 288),
            'QCIF_NTSC': (160, 120),  'QCIF_PAL': (192, 144)}[video_fmt]

    def start_channel(self):
        self.target.open_channel()

    def stop_channel(self, *largs, **kwargs):
        self.target.close_channel_server()

    def _post_read(self, result):
        img = Image(
            plane_buffers=[result[1]], pix_fmt=self.output_img_fmt,
            size=self.size)
        self.callback(img, result[0])

    def _set_state(self, state):
        if not state:
            if self._state_event is not None or self._read_event is not None:
                try:
                    self.target.set_state(False, flush=True)
                except:
                    pass
                self.remove_request('read', self._read_event)
                self.remove_request('set_state', self._state_event)
                self._state_event = None
                self.target.set_state(True)
                self._read_event = self.request_callback(
                    'read', callback=self._post_read, repeat=True,
                    cls_method=False)
            else:
                self.target.set_state(False, flush=True)
            self._state_event_off = None
        else:
            try:
                self.target.set_state(False, flush=True)
            except:
                pass
            if self._state_event_off is not None:
                self.remove_request('read', self._read_event)
                self.remove_request('set_state', self._state_event_off)
                self._state_event_off = self._state_event = None
                self._read_event = None
            else:
                self._state_event = None
                self._read_event = self.request_callback(
                    'read', callback=self._post_read, repeat=True,
                    cls_method=False)

        self._state_event = None
        self.target.set_state(True)
        self._read_event = self.request_callback(
            'read', callback=self._post_read, repeat=True, cls_method=False)

    def set_state(self, state, **kwargs):
        if state == self.state:
            return
        if state:
            self.remove_request('set_state', self._state_event_off)
            self._state_event_off = None
            self._state_event = self.request_callback(
                '_set_state', cls_method=True, state=True)
        else:
            self.remove_request('read', self._read_event)
            self.remove_request('set_state', self._state_event)
            self._read_event = None
            self._state_event = None
            self._state_event_off = self.request_callback(
                '_set_state', cls_method=True, state=False)
        super(RTVChan, self).set_state(state, **kwargs)
