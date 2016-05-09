
from pybarst.rtv import RTVChannel

from kivy.properties import (
    StringProperty, ObjectProperty, NumericProperty, BooleanProperty,
    OptionProperty)

from ffpyplayer.pic import Image

from moa.device import Device
from moa.threads import ScheduledEventLoop
from cplcom.moa.device import DeviceExceptionBehavior

__all__ = ('RTVChan', )


class RTVChan(DeviceExceptionBehavior, Device, ScheduledEventLoop):

    __settings_attrs__ = ('output_img_fmt', 'output_video_fmt', 'port')

    _read_event = None

    last_img = ObjectProperty(None)

    output_img_fmt = OptionProperty('gray', options=[
        'rgb16', 'gray', 'rgb15', 'rgb24', 'rgb32'])

    ff_output_img_fmt = ''

    output_video_fmt = OptionProperty('full_NTSC', options=[
        'full_NTSC', 'full_PAL', 'CIF_NTSC', 'CIF_PAL', 'QCIF_NTSC',
        'QCIF_PAL'])

    port = NumericProperty(0)

    server = ObjectProperty(None)

    rate = None

    size = None

    chan = ObjectProperty(None)

    ffmpeg_img_fmt_dict = {
        'rgb16': 'rgb565le', 'gray': 'gray', 'rgb15': 'rgb555le',
        'rgb24': 'rgb24', 'rgb32': 'rgba'}

    img_sizes = {
        'full_NTSC': (640, 480), 'full_PAL': (768, 576),
        'CIF_NTSC': (320, 240), 'CIF_PAL': (384, 288),
        'QCIF_NTSC': (160, 120),  'QCIF_PAL': (192, 144)}

    def _post_read(self, result):
        img = Image(
            plane_buffers=[result[1]], pix_fmt=self.ff_output_img_fmt,
            size=self.size)
        self.last_img = result[0], img
        self.dispatch('on_data_update', self)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(RTVChan, self).activate(*largs, **kwargs):
            return False

        self.start_thread()
        n = self.port
        frame_fmt = self.output_img_fmt
        self.ff_output_img_fmt = self.ffmpeg_img_fmt_dict[frame_fmt]
        video_fmt = self.output_video_fmt
        self.chan = RTVChannel(
            chan=n, server=self.server.server, video_fmt=video_fmt,
            frame_fmt=frame_fmt, luma_filt=frame_fmt == 'gray',
            lossless=True)
        self.rate = (2997, 100)
        self.size = self.img_sizes[video_fmt]

        def finish_activate(*largs):
            self.activation = 'active'
            self._read_event = self.request_callback(
                self.chan.read, callback=self._post_read, repeat=True)
        self.request_callback(self._start_channel, finish_activate)
        return True

    def _start_channel(self):
        self.chan.open_channel()
        self.chan.set_state(True)

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if not super(RTVChan, self).deactivate(*largs, **kwargs):
            return False

        self.remove_request(self.chan.read, self._read_event)
        self._read_event = None

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._stop_channel, finish_deactivate)
        return True

    def _stop_channel(self):
        self.chan.set_state(False, flush=True)
        self.chan.close_channel_server()
