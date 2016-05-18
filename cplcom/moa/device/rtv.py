'''Barst RTV Wrapper
=======================
'''
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
    '''A :class:`moa.device.Device` wrapper around a
    :class:`pybarst.rtv.RTVChannel` instance.
    '''

    __settings_attrs__ = ('output_img_fmt', 'output_video_fmt', 'port')

    _read_event = None

    last_img = ObjectProperty(None)
    '''The last image received from the device. It's a 2-tuple of the timestamp
    and :class:`ffpyplayer.pic.Image` instance.

    By binding to the `on_data_update` event and then reading the value
    of :attr:`last_image` one gets each image as it's read.
    '''

    output_img_fmt = OptionProperty('gray', options=[
        'rgb16', 'gray', 'rgb15', 'rgb24', 'rgb32'])
    '''The desired output image format that the rtv device should send us.
    It can be one of `'rgb16', 'gray', 'rgb15', 'rgb24', 'rgb32'`.

    Defaults to `'gray'`.
    '''

    ff_output_img_fmt = ''
    '''The format of the output image from the ffpyplayer picture formats
    :attr:`ffpyplayer.tools.pix_fmts`, translated from :attr:`output_img_fmt`.

    Read only.
    '''

    output_video_fmt = OptionProperty('full_NTSC', options=[
        'full_NTSC', 'full_PAL', 'CIF_NTSC', 'CIF_PAL', 'QCIF_NTSC',
        'QCIF_PAL'])
    '''The desired output image size that the rtv device should send us.
    It can be one of
    `'full_NTSC', 'full_PAL', 'CIF_NTSC', 'CIF_PAL', 'QCIF_NTSC', 'QCIF_PAL'`
    and its corresponding size is listed in :attr:`img_sizes`.
    '''

    port = NumericProperty(0)
    '''The port number on the RTV card of camera to use.
    '''

    server = ObjectProperty(None)
    '''The internal barst :class:`pybarst.core.server.BarstServer`. It
    must be provided to the instance.
    '''

    rate = (2997, 100)
    '''The output frame rate. It's read only.
    '''

    size = None
    '''The actual output size of the images. Computed from
    :attr:`output_video_fmt`.
    '''

    chan = ObjectProperty(None)
    '''The internal :class:`pybarst.rtv.RTVChannel` instance.
    It is read only and is automatically created.
    '''

    ffmpeg_img_fmt_dict = {
        'rgb16': 'rgb565le', 'gray': 'gray', 'rgb15': 'rgb555le',
        'rgb24': 'rgb24', 'rgb32': 'rgba'}
    '''Conversion dict between the :attr:`output_img_fmt` to the
    :attr:`ff_output_img_fmt` format.
    '''

    img_sizes = {
        'full_NTSC': (640, 480), 'full_PAL': (768, 576),
        'CIF_NTSC': (320, 240), 'CIF_PAL': (384, 288),
        'QCIF_NTSC': (160, 120),  'QCIF_PAL': (192, 144)}
    '''Conversion dict between the :attr:`output_video_fmt` to the
    :attr:`size` of the images.
    '''

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
