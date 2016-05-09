
import time
from threading import Thread
from fractions import Fraction
import traceback
try:
    from Queue import Queue
except:
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

logger_func = {'quiet': Logger.critical, 'panic': Logger.critical,
               'fatal': Logger.critical, 'error': Logger.error,
               'warning': Logger.warning, 'info': Logger.info,
               'verbose': Logger.debug, 'debug': Logger.debug}


def _log_callback(message, level):
    message = message.strip()
    if message:
        logger_func[level]('ffpyplayer: {}'.format(message))

if not get_log_callback():
    set_log_callback(_log_callback)


class FFPyPlayerDevice(DeviceExceptionBehavior, Device, ScheduledEventLoop):

    __settings_attrs__ = ('filename', 'output_img_fmt')

    _needs_exit = False
    _frame_queue = None

    filename = StringProperty('Wildlife.mp4')

    input_img_fmt = StringProperty(None, allownone=True)

    input_img_w = NumericProperty(None, allownone=True)

    input_img_h = NumericProperty(None, allownone=True)

    input_rate = NumericProperty(None, allownone=True)

    output_img_fmt = StringProperty('', allownone=True)

    vid_fmt = StringProperty(None, allownone=True)

    codec = StringProperty(None, allownone=True)

    last_img = ObjectProperty(None)

    rate = None

    size = None

    display_img_fmt = ''

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

    __settings_attrs__ = ('filename', 'ofmt')

    _frame_queue = None

    error_count = 0

    filename = StringProperty('')

    size = ObjectProperty(None)

    rate = ObjectProperty(1.)

    ifmt = StringProperty('')

    ofmt = StringProperty('')

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
