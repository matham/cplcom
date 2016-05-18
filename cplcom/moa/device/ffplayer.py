'''FFPyPlayer Wrapper
========================
'''
import time
from fractions import Fraction
import traceback
try:
    from Queue import Queue
except ImportError:
    from queue import Queue

from ffpyplayer.player import MediaPlayer
from ffpyplayer.tools import set_log_callback, get_log_callback
from ffpyplayer.writer import MediaWriter

from kivy.properties import StringProperty, ObjectProperty, NumericProperty
from kivy.resources import resource_find
from kivy.clock import Clock

from moa.device import Device
from moa.logger import Logger
from moa.threads import ScheduledEventLoop
from cplcom.moa.device import DeviceExceptionBehavior

__all__ = ('FFPyPlayerDevice', 'FFPyWriterDevice')

_logger_func = {'quiet': Logger.critical, 'panic': Logger.critical,
                'fatal': Logger.critical, 'error': Logger.error,
                'warning': Logger.warning, 'info': Logger.info,
                'verbose': Logger.debug, 'debug': Logger.debug}


def _log_callback(message, level):
    message = message.strip()
    if message:
        _logger_func[level]('ffpyplayer: {}'.format(message))

if not get_log_callback():
    set_log_callback(_log_callback)


class FFPyPlayerDevice(DeviceExceptionBehavior, Device, ScheduledEventLoop):
    '''A :class:`moa.device.Device` wrapper around a
    :class:`ffpyplayer.player.MediaPlayer` instance which reads a video
    stream and forwards the images.
    '''

    __settings_attrs__ = ('filename', 'output_img_fmt')

    _needs_exit = False
    _frame_queue = None

    filename = StringProperty('Wildlife.mp4')
    '''The full filename to the video file or video stream.
    '''

    input_img_fmt = StringProperty(None, allownone=True)
    '''When e.g. a direct show or similar stream is used as the
    :attr:`filename`, it's the image pixel format from
    :attr:`ffpyplayer.tools.pix_fmts` that is to be used when opening and
    configuring the stream.
    '''

    input_img_w = NumericProperty(None, allownone=True)
    '''When e.g. a direct show or similar stream is used as the
    :attr:`filename`, it's the image width that is to be used when opening and
    configuring the stream. Defaults to None.
    '''

    input_img_h = NumericProperty(None, allownone=True)
    '''When e.g. a direct show or similar stream is used as the
    :attr:`filename`, it's the image height that is to be used when opening and
    configuring the stream. Defaults to None.
    '''

    input_rate = NumericProperty(None, allownone=True)
    '''When e.g. a direct show or similar stream is used as the
    :attr:`filename`, it's the video frame rate that is to be used when
    opening and configuring the stream. Defaults to None.
    '''

    output_img_fmt = StringProperty('', allownone=True)
    '''The image pixel format from :attr:`ffpyplayer.tools.pix_fmts` that is to
    be used for the images output to us by the player. Defaults to `''` and
    must be set.
    '''

    vid_fmt = StringProperty(None, allownone=True)
    '''The video file format of the input stream. This is used to open e.g.
    a webcam format, a actual file, or e.g. a Internet stream. When None,
    the default, it's a file. Defaults to None.
    '''

    codec = StringProperty(None, allownone=True)
    '''When e.g. a direct show or similar stream is used as the
    :attr:`filename`, it's the video codec that is to be used when opening and
    configuring the stream. Defaults to None.
    '''

    last_img = ObjectProperty(None)
    '''The last image received from the player. It's a 2-tuple of the timestamp
    and :class:`ffpyplayer.pic.Image` instance.

    By binding to the `on_data_update` event and then reading the value
    of :attr:`last_image` one gets each image as it's read.
    '''

    rate = None
    '''The output frame rate. It's read only and is automatically set when
    activated.
    '''

    size = None
    '''The output image size. It's read only and is automatically set when
    activated.
    '''

    display_img_fmt = ''
    '''The actual output image pixel format from
    :attr:`ffpyplayer.tools.pix_fmts`. It's read only and is automatically set
    when activated.
    '''

    def _player_callback(self, mode, value):
        if mode == 'display_sub':
            return
        if mode.endswith('error'):
            try:
                raise ValueError('FFmpeg callback: {}, {}'.format(mode, value))
            except Exception as e:
                self.handle_exception((e, traceback.format_exc()))

    def _service_queue(self, dt):
        dispatch = self.dispatch
        frames = self._frame_queue[:]
        del self._frame_queue[:len(frames)]
        for frame, pts in frames:
            self.last_img = pts, frame
            dispatch('on_data_update', self)

    def _next_frame_run(self):
        sleep = time.sleep
        clock = time.clock
        queue = self._frame_queue = []
        schedule = Clock.create_trigger_priority(self._service_queue)
        name = resource_find(self.filename)
        if name is None:
            raise ValueError('Could not find {}'.format(self.filename))

        ff_opts = {'paused': False, 'loop': 0, 'an': True}
        if self.output_img_fmt:
            ff_opts['out_fmt'] = self.output_img_fmt
        if self.vid_fmt is not None:
            ff_opts['f'] = self.vid_fmt
        if self.codec is not None:
            ff_opts['vcodec'] = self.codec

        lib_opts = {}
        if self.vid_fmt == 'dshow':
            if self.input_img_fmt is not None:
                lib_opts['pixel_format'] = self.input_img_fmt
            h, w = self.input_img_h, self.input_img_w
            if h is not None and w is not None:
                lib_opts['video_size'] = '{}x{}'.format(w, h)
            if self.input_rate is not None:
                lib_opts['framerate'] = str(self.input_rate)

        ffplayer = MediaPlayer(
            name, callback=self._player_callback, ff_opts=ff_opts,
            lib_opts=lib_opts)

        # wait until loaded or failed, shouldn't take long, but just to make
        # sure metadata is available.
        s = clock()
        while not self._needs_exit:
            if ffplayer.get_metadata()['src_vid_size'] != (0, 0):
                break
            if clock() - s > 10.:
                raise ValueError('Could not read video metadata')
            sleep(0.005)

        self.rate = ffplayer.get_metadata()['frame_rate']

        def finish_activate(*largs):
            self.activation = 'active'
        active = False

        while not self._needs_exit:
            frame, val = ffplayer.get_frame()
            if val == 'eof':
                raise ValueError('Reached video end of file')
            elif val == 'paused':
                sleep(.033)
            else:
                if frame is not None:
                    if not active:
                        active = True
                        self.display_img_fmt = frame[0].get_pixel_format()
                        self.size = frame[0].get_size()
                        Clock.schedule_once(finish_activate, 0)
                    queue.append((frame[0], clock()))
                    schedule()
                else:
                    val = val if val else (1 / 60.)
                sleep(val)

    def activate(self, *largs, **kwargs):
        kwargs['state'] = 'activating'
        if not super(FFPyPlayerDevice, self).activate(*largs, **kwargs):
            return False
        self._needs_exit = False
        self.start_thread()

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._next_frame_run, callback=finish_deactivate)
        return True

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if super(FFPyPlayerDevice, self).deactivate(*largs, **kwargs):
            self._needs_exit = True
            return True
        return False


class FFPyWriterDevice(DeviceExceptionBehavior, Device, ScheduledEventLoop):
    '''A :class:`moa.device.Device` wrapper around a
    :class:`ffpyplayer.writer.MediaWriter` instance which writes a video
    stream to a file.
    '''

    __settings_attrs__ = ('filename', 'ofmt')

    _frame_queue = None

    error_count = 0
    '''The number of frames that are skipped when writing to file. Often due
    to a bad timestamp that doesn't fit the frame rate. It is read only.
    '''

    filename = StringProperty('')
    '''The filename of the video to create.
    '''

    size = ObjectProperty(None)
    '''The image sizes that will be passed to the video. This must be
    set to match the image frames that are passed to :meth:`add_frame`.
    '''

    rate = ObjectProperty(1.)
    '''The frame rate at which the video frames will be written. It should
    match the timestamps that will be passed to :meth:`add_frame`.
    '''

    ifmt = StringProperty('')
    '''The pixel format from :attr:`ffpyplayer.tools.pix_fmts` in which the
    images passed to :meth:`add_frame` will be in. They must match.
    '''

    ofmt = StringProperty('')
    '''The pixel format from :attr:`ffpyplayer.tools.pix_fmts` in which
    the images will be written to disk. If not empty and different than
    :attr:`ifmt`, the input format, the images will be internally converted to
    this format before writing to disk.
    '''

    def activate(self, *largs, **kwargs):
        if not super(FFPyWriterDevice, self).activate(*largs, **kwargs):
            return False
        self._frame_queue = Queue()
        self.error_queue = []
        self.start_thread()

        def finish_deactivate(*largs):
            self.activation = 'inactive'
            self.stop_thread()
        self.request_callback(self._record_frames, callback=finish_deactivate)
        return True

    def deactivate(self, *largs, **kwargs):
        kwargs['state'] = 'deactivating'
        if super(FFPyWriterDevice, self).deactivate(*largs, **kwargs):
            self.add_frame(None, 0)
            return True
        return False

    def add_frame(self, frame, pts):
        '''Adds a frame to be written to disk.

        :Parameters:

            `frame`: A :class:`ffpyplayer.pic.Image` instance.
                The image to be written.
            `pts`: float
                The time stamp of the image.

        A frame of None is passed internally when the device is to be
        deactivated.
        '''
        if frame is None:
            self._frame_queue.put('eof', block=False)
        else:
            self._frame_queue.put((frame, pts), block=False)

    def _record_frames(self):
        queue = self._frame_queue

        ifmt = self.ifmt
        ofmt = self.ofmt
        rate = self.rate
        size = self.size
        if isinstance(rate, (float, int)):
            rate = Fraction(rate)
        if isinstance(rate, Fraction):
            rate = rate.numerator, rate.denominator

        writer = MediaWriter(
            self.filename, [{
                'pix_fmt_in': ifmt, 'width_in': size[0], 'height_in': size[1],
                'codec':'rawvideo', 'frame_rate': rate, 'pix_fmt_out': ofmt}])

        ts0 = None
        while True:
            frame = queue.get(block=True)
            if frame == 'eof':
                return
            img, pts = frame
            if ts0 is None:
                ts0 = pts
            try:
                writer.write_frame(img, pts - ts0, 0)
            except Exception as e:
                self.error_count += 1
                Logger.warning('{}: {} ({})'.format(e, pts - ts0, pts))
