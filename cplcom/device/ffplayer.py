
import time
from threading import Thread, Event, RLock
from fractions import Fraction
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

from moa.device.digital import ButtonChannel
from moa.logger import Logger
from moa.base import MoaBase

from cplcom.device import DeviceStageInterface

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


class FFPyPlayerDevice(ButtonChannel, DeviceStageInterface):

    _ffplayer = None
    _ffread_event = None
    _thread = None
    _thread_event = None
    _needs_exit = False
    _frame_queue = None

    filename = StringProperty('')

    input_img_fmt = StringProperty(None, allownone=True)

    input_img_w = NumericProperty(None, allownone=True)

    input_img_h = NumericProperty(None, allownone=True)

    input_rate = NumericProperty(None, allownone=True)

    output_img_fmt = StringProperty(None, allownone=True)

    vid_fmt = StringProperty(None, allownone=True)

    codec = StringProperty(None, allownone=True)

    callback = ObjectProperty(None)

    rate = None

    size = None

    _paused = True

    _pause_lock = None

    def _player_callback(self, selector, value):
        if self._ffplayer is None:
            return
        if selector == 'quit':
            def close(*args):
                Logger.exception('ffpyplayer asked to quit.')
                self.deactivate(self, clear=True)
            Clock.schedule_once(close, 0)

    def _service_queue(self, dt):
        callback = self.callback
        frames = self._frame_queue[:]
        del self._frame_queue[:len(frames)]
        if callback is None:
            return
        for frame, pts in frames:
            callback(frame, pts)

    def _next_frame_run(self):
        ffplayer = self._ffplayer
        sleep = time.sleep
        event = self._thread_event
        clock = time.clock
        queue = self._frame_queue = []
        schedule = Clock.create_trigger_priority(self._service_queue)

        try:
            # wait until loaded or failed, shouldn't take long, but just to make
            # sure metadata is available.
            with self._pause_lock:
                if self.paused:
                    ffplayer.toggle_pause()
                    self.paused = False
            s = clock()
            while not self._needs_exit:
                if ffplayer.get_metadata()['src_vid_size'] != (0, 0):
                    break
                if clock() - s > 10.:
                    def close(*args):
                        Logger.exception("ffpyplayer couldn't read file metadata.")
                        self.deactivate(self, clear=True)
                    Clock.schedule_once(close, 0)
                    return
                sleep(0.005)
            with self._pause_lock:
                if not self.paused and not self.state:
                    ffplayer.toggle_pause()
                    self.paused = True

            self.size = ffplayer.get_metadata()['src_vid_size']
            self.rate = ffplayer.get_metadata()['frame_rate']

            while not self._needs_exit:
                event.wait()
                frame, val = ffplayer.get_frame()
                if val == 'eof':
                    Logger.warning("ffpyplayer reached end of file.")
                    event.clear()
                elif val != 'paused':
                    if frame is not None:
                        queue.append((frame[0], clock()))
                        schedule()
                    else:
                        val = val if val else (1 / 60.)
                    sleep(val)
        except Exception as e:
            self.handle_exception(e)

    def activate(self, *largs, **kwargs):
        if super(FFPyPlayerDevice, self).activate(*largs, **kwargs):
            name = resource_find(self.filename)

            self.paused = True
            self._needs_exit = False

            ff_opts = {'paused': True, 'loop': 0, 'an': True}
            if self.output_img_fmt is not None:
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
                    lib_opts['framerate'] = bytes(str(self.input_rate))

            self._ffplayer = MediaPlayer(
                name, callback=lambda: self._player_callback, ff_opts=ff_opts,
                lib_opts=lib_opts)
            self._pause_lock = RLock()
            self._thread_event = Event()
            self._thread = Thread(
                target=self._next_frame_run, name='Next frame')
            self._thread.daemon = True
            self._thread.start()
            if self.state:
                with self._pause_lock:
                    if self.paused:
                        self._ffplayer.toggle_pause()
                        self.paused = False
            return True
        return False

    def deactivate(self, *largs, **kwargs):
        if super(FFPyPlayerDevice, self).deactivate(*largs, **kwargs):
            self._needs_exit = True
            if self._thread_event is not None:
                self._thread_event.set()
            thread = self._thread
            if thread is not None:
                thread.join()
                self._thread = None
            return True
        return False

    def on_state(self, *largs):
        ffplayer = self._ffplayer
        if ffplayer is None:
            return
        if self.state:
            self._thread_event.set()
        else:
            self._thread_event.clear()
        with self._pause_lock:
            if self.paused != (not self.state):
                ffplayer.toggle_pause()
                self.paused = not self.state


class FFPyWriterDevice(MoaBase, DeviceStageInterface):

    _frame_queue = None
    _thread = None
    _writer = None

    def __init__(self, filename='', size=None, rate=1., ifmt='', ofmt=None,
                 **kwargs):
        super(FFPyWriterDevice, self).__init__(**kwargs)
        self._frame_queue = Queue()
        if ofmt is None:
            ofmt = 'gray' if ifmt == 'gray' else 'yuv420p'
        if isinstance(rate, (float, int)):
            rate = Fraction(rate)
        if isinstance(rate, Fraction):
            rate = rate.numerator, rate.denominator
        self._writer = MediaWriter(
            filename, [{
                'pix_fmt_in': ifmt, 'width_in': size[0], 'height_in': size[1],
                'codec':'rawvideo', 'frame_rate': rate, 'pix_fmt_out': ofmt}])
        self._thread = Thread(
            target=self._record_frames, name='Save frames')
        self._thread.start()

    def add_frame(self, frame=None, pts=0):
        if frame is None:
            self._frame_queue.put('eof', block=False)
        else:
            self._frame_queue.put((frame, pts), block=False)

    def _record_frames(self):
        queue = self._frame_queue
        writer = self._writer

        try:
            while True:
                frame = queue.get(block=True)
                if frame == 'eof':
                    self._writer = None
                    return
                img, pts = frame
                try:
                    writer.write_frame(img, pts, 0)
                except Exception as e:
                    Logger.warning('{}: {}'.format(e, pts))
        except Exception as e:
            self.handle_exception(e)
