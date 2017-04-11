'''Player
===========

Module for playing and recording video.
'''

from os.path import isfile, join, abspath, expanduser, splitext
import logging
import sys
from threading import Thread, RLock
import time
from fractions import Fraction
from time import sleep
from functools import partial
from collections import namedtuple, defaultdict
import re
try:
    from Queue import Queue
except ImportError:
    from queue import Queue

import ffpyplayer
from ffpyplayer.player import MediaPlayer
from ffpyplayer.pic import get_image_size, Image, SWScale
from ffpyplayer.tools import list_dshow_devices, set_log_callback
from ffpyplayer.tools import get_supported_pixfmts, get_format_codec
from ffpyplayer.writer import MediaWriter

from pybarst.core.server import BarstServer
from pybarst.rtv import RTVChannel

from kivy.clock import Clock
from kivy.compat import clock
from kivy.uix.behaviors.knspace import knspace
from kivy.properties import (
    NumericProperty, ReferenceListProperty,
    ObjectProperty, ListProperty, StringProperty, BooleanProperty,
    DictProperty, AliasProperty, OptionProperty, ConfigParserProperty)
from kivy.event import EventDispatcher
from kivy.logger import Logger

try:
    from pyflycap2.interface import GUI, Camera, CameraContext
except ImportError as e:
    GUI = Camera = CameraContext = None
    Logger.error(e, exc_info=sys.exc_info())

from cplcom.app import app_error


__all__ = ('Player', 'FFmpegPlayer', 'RTVPlayer', 'PTGrayPlayer',
           'VideoMetadata')

set_log_callback(logger=Logger, default_only=True)
logging.info('Filers: Using ffpyplayer {}'.format(ffpyplayer.__version__))

VideoMetadata = namedtuple('VideoMetadata', ['fmt', 'w', 'h', 'rate'])
'''namedtuple describing a video stream.
'''


def eat_first(f, val, *largs, **kwargs):
    f(*largs, **kwargs)


class Player(EventDispatcher):
    '''Base class for every player.
    '''

    __settings_attrs__ = (
        'record_directory', 'record_fname', 'record_fname_count',
        'metadata_play', 'metadata_play_used', 'metadata_record', 'cls')

    cls = StringProperty('')
    '''(internal) The string associated with the player source used.

    It is one of ``FFMpeg``, ``RTV``, or ``PTGray`` indicating the camera
    being used.
    '''

    err_trigger = None

    play_thread = None

    play_state = StringProperty('none')
    '''Can be one of none, starting, playing, stopping.
    '''

    play_lock = None

    play_callback = None
    '''Shared between the event that sets the state to stop and the event that
    sets the state to playing.
    '''

    play_paused = False
    '''When playing, whether we're paused.
    '''

    record_thread = None

    record_state = StringProperty('none')
    '''Can be one of none, starting, recording, stopping.
    '''

    record_lock = None

    record_callback = None
    '''Shared between the event that sets the state to stop and the event that
    sets the state to recording.
    '''

    record_directory = StringProperty(expanduser('~'))
    '''The directory into which videos should be saved.
    '''

    record_fname = StringProperty('video{}.avi')
    '''The filename to be used to record the next video.

    If ``{}`` is present in the filename, it'll be replaced with the value of
    :attr:`record_fname_count` which auto increments after every video, when
    used.
    '''

    record_fname_count = StringProperty('0')
    '''A counter that auto increments by one after every recorded video.

    Used to give unique filenames for each video file.
    '''

    record_filename = ''

    config_active = BooleanProperty(False)

    display_trigger = None

    last_image = None

    image_queue = None

    use_real_time = False

    metadata_play = ObjectProperty(None)
    '''(internal) Describes the video metadata of the video player.
    '''

    metadata_play_used = ObjectProperty(None)
    '''(internal) Describes the video metadata of the video player that is
    actually used by the player.
    '''

    metadata_record = ObjectProperty(None)
    '''(internal) Describes the video metadata of the video recorder.
    '''

    real_rate = 0

    frames_played = 0

    frames_recorded = 0

    frames_skipped = 0

    size_recorded = 0

    ts_play = 0

    ts_record = 0

    player_summery = StringProperty('')

    record_stats = StringProperty('')

    def __init__(self, **kwargs):
        self.metadata_play = VideoMetadata(
            *kwargs.pop('metadata_play', ('', 0, 0, 0)))
        self.metadata_play_used = VideoMetadata(
            *kwargs.pop('metadata_play_used', ('', 0, 0, 0)))
        self.metadata_record = VideoMetadata(
            *kwargs.pop('metadata_record', ('', 0, 0, 0)))
        name = self.__class__.__name__
        if name.startswith('FF'):
            self.cls = 'FFmpeg'
        elif name.startswith('RTV'):
            self.cls = 'RTV'
        elif name.startswith('PTGray'):
            self.cls = 'PTGray'
        super(Player, self).__init__(**kwargs)
        self.play_lock = RLock()
        self.record_lock = RLock()
        self.display_trigger = Clock.create_trigger(self.display_frame, 0)

    def err_callback(self, *largs, **kwargs):
        self.stop()
        msg = kwargs.get('msg', '')
        e = kwargs.get('e', None)
        if e and msg:
            e.args = e.args + (msg, ) if e.args else (msg, )
        elif not e:
            e = Exception(msg)
        knspace.app.handle_exception(e, exc_info=kwargs.get('exc_info', None))

    def display_frame(self, *largs):
        pass

    @app_error
    def save_screenshot(self, path, selection, filename, codec='bmp',
                        pix_fmt='bgr24'):
        fname = join(abspath(path), filename)
        if self.last_image is None:
            raise ValueError('No image acquired')

        img, _ = self.last_image
        self.save_image(fname, img, codec, pix_fmt)

    @staticmethod
    def save_image(fname, img, codec='bmp', pix_fmt='bgr24'):
        fmt = img.get_pixel_format()
        w, h = img.get_size()

        if not codec:
            codec = get_format_codec(fname)
            ofmt = get_supported_pixfmts(codec, fmt)[0]
        else:
            ofmt = get_supported_pixfmts(codec, pix_fmt or fmt)[0]
        if ofmt != fmt:
            sws = SWScale(w, h, fmt, ofmt=ofmt)
            img = sws.scale(img)
            fmt = ofmt

        out_opts = {'pix_fmt_in': fmt, 'width_in': w, 'height_in': h,
                    'frame_rate': (30, 1), 'codec': codec}
        writer = MediaWriter(fname, [out_opts])
        writer.write_frame(img=img, pts=0, stream=0)
        writer.close()

    def compute_recording_opts(self, ifmt=None, iw=None, ih=None, irate=None):
        play_used = self.metadata_play_used
        ifmt = ifmt or play_used.fmt
        iw = iw or play_used.w
        ih = ih or play_used.h
        irate = irate or play_used.rate
        ofmt, ow, oh, orate = self.metadata_record
        ifmt = ifmt or 'yuv420p'
        iw = iw or 640
        ih = ih or 480
        irate = irate or 30.
        ofmt = ofmt or ifmt
        ow = ow or iw
        oh = oh or ih
        orate = orate or irate
        return (ifmt, iw, ih, irate), (ofmt, ow, oh, orate)

    def play(self):
        '''Called from main thread only, starts playing and sets play state to
        `starting`. Only called when :attr:`play_state` is `none`.
        '''
        if self.play_state != 'none':
            Logger.warn(
                '%s: Asked to play while {}'.format(self.play_state), self)
            return

        self.play_state = 'starting'
        self.play_paused = False
        thread = self.play_thread = Thread(
            target=self.play_thread_run, name='Play thread')
        thread.start()

    def set_pause(self, state):
        raise NotImplementedError

    def record(self):
        '''Called from main thread only, starts recording and sets record state
        to `starting`. Only called when :attr:`record_state` is `none`.
        '''
        if self.record_state != 'none':
            Logger.warn(
                '%s: Asked to record while {}'.format(self.record_state), self)
            return

        self.record_state = 'starting'
        self.image_queue = Queue()
        self.record_filename = filename = join(
            self.record_directory,
            self.record_fname.replace('{}', self.record_fname_count))
        thread = self.record_thread = Thread(
            target=self.record_thread_run, name='Record thread',
            args=(filename, ))
        thread.start()

    def stop_recording(self, *largs):
        if self.record_state == 'none':
            return False

        with self.record_lock:
            if self.record_state == 'stopping':
                return False

            if self.record_callback is not None:
                self.record_callback.cancel()
                self.record_callback = None
            self.image_queue.put_nowait('eof')
            self.image_queue = None
            self.record_state = 'stopping'
        return True

    def stop(self, *largs):
        self.stop_recording()
        if self.play_state == 'none':
            return False

        with self.play_lock:
            if self.play_state == 'stopping':
                return False

            if self.play_callback is not None:
                self.play_callback.cancel()
                self.play_callback = None
            self.play_state = 'stopping'
        return True

    def stop_all(self, join=False):
        self.stop()
        if join:
            if self.record_thread:
                self.record_thread.join()
            if self.play_thread:
                self.play_thread.join()

    def change_status(self, thread='play', start=True, e=None):
        '''Called from the play or record secondary thread to change the
        play/record state to playing/recording or none.
        '''
        if start:
            with getattr(self, thread + '_lock'):
                state = getattr(self, thread + '_state')
                if state not in ('starting', 'stopping'):
                    Logger.warn(
                        '%s: Asked to continue {}ing while {}'.
                        format(thread, state), self)
                    return
                if state == 'stopping':
                    return

                ev = Clock.schedule_once(
                    partial(self._complete_start, thread), 0)
                setattr(self, thread + '_callback', ev)
            while getattr(self, thread + '_state') == 'starting':
                sleep(.01)
        else:
            if e and getattr(self, thread + '_state') in (
                    thread + 'ing', 'starting', 'stopping'):
                src = '{}er'.format(thread.capitalize())
                Clock.schedule_once(partial(
                    self.err_callback, msg='%s: %s' % (self, src),
                    exc_info=sys.exc_info(), e=e), 0)
            self._request_stop(thread)
            while getattr(self, thread + '_state') != 'stopping':
                sleep(.01)
            Clock.schedule_once(partial(self._complete_stop, thread), 0)

    def update_metadata(self, fmt=None, w=None, h=None, rate=None):
        ifmt, iw, ih, irate = self.metadata_play_used
        if fmt is not None:
            ifmt = fmt
        if w is not None:
            iw = w
        if h is not None:
            ih = h
        if rate is not None:
            irate = rate
        self.metadata_play_used = VideoMetadata(ifmt, iw, ih, irate)

    def _request_stop(self, thread):
        with getattr(self, thread + '_lock'):
            callback = getattr(self, thread + '_callback')
            if callback is not None:
                callback.cancel()

            if getattr(self, thread + '_state') != 'stopping':
                if thread == 'play':
                    ev = Clock.schedule_once(self.stop, 0)
                else:
                    ev = Clock.schedule_once(self.stop_recording, 0)
                setattr(self, thread + '_callback', ev)
            else:
                setattr(self, thread + '_callback', None)

    def _complete_start(self, thread, *largs):
        with getattr(self, thread + '_lock'):
            if getattr(self, thread + '_state') == 'starting':
                setattr(self, thread + '_state', thread + 'ing')

    def _complete_stop(self, thread, *largs):
        if thread == 'play':
            self.play_thread = None
        else:
            self.record_thread = None
        setattr(self, thread + '_state', 'none')

    def play_thread_run(self):
        pass

    def record_thread_run(self, filename):
        queue = self.image_queue
        recorder = None
        irate = None
        t0 = None
        self.size_recorded = self.frames_skipped = self.frames_recorded = 0
        while self.record_state != 'stopping':
            item = queue.get()
            if item == 'eof':
                break
            img, t = item

            if img == 'rate':
                assert recorder is None
                irate = t
                continue

            if recorder is None:
                self.ts_record = clock()
                t0 = t
                iw, ih = img.get_size()
                ipix_fmt = img.get_pixel_format()

                _, (opix_fmt, ow, oh, orate) = self.compute_recording_opts(
                    ipix_fmt, iw, ih, irate)

                orate = Fraction(orate)
                if orate >= 1.:
                    orate = Fraction(orate.denominator, orate.numerator)
                    orate = orate.limit_denominator(2 ** 30 - 1)
                    orate = (orate.denominator, orate.numerator)
                else:
                    orate = orate.limit_denominator(2 ** 30 - 1)
                    orate = (orate.numerator, orate.denominator)

                stream = {
                    'pix_fmt_in': ipix_fmt, 'pix_fmt_out': opix_fmt,
                    'width_in': iw, 'height_in': ih, 'width_out': ow,
                    'height_out': oh, 'codec': 'rawvideo', 'frame_rate': orate}

                try:
                    recorder = MediaWriter(filename, [stream])
                except Exception as e:
                    self.change_status('record', False, e)
                    return
                self.change_status('record', True)

            try:
                self.size_recorded = recorder.write_frame(img, t - t0)
                self.frames_recorded += 1
            except Exception as e:
                self.frames_skipped += 1
                Logger.warn('{}: Recorder error writing frame: {}'
                            .format(self, e))

        self.change_status('record', False)


class FFmpegPlayer(Player):
    '''Wrapper for ffmapeg based player.
    '''

    __settings_attrs__ = ('play_filename', 'file_fmt', 'icodec',
                          'dshow_true_filename', 'dshow_opt')

    play_filename = StringProperty('')
    '''The filename of the media being played. Can be e.g. a url etc.
    '''

    file_fmt = StringProperty('dshow')
    '''The format used to play the video. Can be empty or a format e.g.
    ``dshow`` for webcams.
    '''

    icodec = StringProperty('')
    '''The codec used to open the video stream with.
    '''

    dshow_true_filename = StringProperty('')
    '''The real and complete filename of the direct show (webcam) device.
    '''

    dshow_opt = StringProperty('')
    '''The camera options associated with :attr:`dshow_true_filename` when
    dshow is used.
    '''

    dshow_names = {}

    dshow_opts = {}

    dshow_opt_pat = re.compile(
        '([0-9]+)X([0-9]+) (.+), ([0-9\\.]+)(?: - ([0-9\\.]+))? fps')

    def __init__(self, **kw):
        play_filename = kw.get('play_filename')
        file_fmt = kw.get('file_fmt')
        dshow_true_filename = kw.get('dshow_true_filename')
        dshow_opt = kw.get('dshow_opt')

        if (file_fmt == 'dshow' and play_filename and dshow_true_filename and
                dshow_opt):
            self.dshow_names = {play_filename: dshow_true_filename}
            self.dshow_opts = {play_filename:
                               {dshow_opt: self.parse_dshow_opt(dshow_opt)}}
        super(FFmpegPlayer, self).__init__(**kw)
        self._update_summary()

    def on_play_filename(self, *largs):
        self._update_summary()

    def on_file_fmt(self, *largs):
        self._update_summary()

    def _update_summary(self):
        fname = self.play_filename
        if not self.file_fmt:
            fname = splitext(fname)[0]

        if len(fname) > 8:
            name = fname[:4] + '...' + fname[-4:]
        else:
            name = fname
        self.player_summery = 'FFMpeg-{}'.format(name)

    def refresh_dshow(self):
        counts = defaultdict(int)
        video, _, names = list_dshow_devices()
        video2 = {}
        names2 = {}

        # rename to have pretty unique names
        for true_name, name in names.items():
            if true_name not in video:
                continue

            count = counts[name]
            name2 = '{}-{}'.format(name, count) if count else name
            counts[name] = count + 1

            # filter and clean cam opts
            names2[name2] = true_name
            opts = video2[name2] = {}

            for fmt, _, (w, h), (rmin, rmax) in video[true_name]:
                if not fmt:
                    continue
                if rmin != rmax:
                    key = '{}X{} {}, {} - {} fps'.format(w, h, fmt, rmin, rmax)
                else:
                    key = '{}X{} {}, {} fps'.format(w, h, fmt, rmin)
                if key not in opts:
                    opts[key] = (fmt, (w, h), (rmin, rmax))

        self.dshow_opts = video2
        self.dshow_names = names2

    def parse_dshow_opt(self, opt):
        m = re.match(self.dshow_opt_pat, opt)
        if m is None:
            raise ValueError('{} not a valid option'.format(opt))

        w, h, fmt, rmin, rmax = m.groups()
        if rmax is None:
            rmax = rmin

        w, h, rmin, rmax = int(w), int(h), float(rmin), float(rmax)
        return fmt, (w, h), (rmin, rmax)

    def get_opt_image_size(self, opt):
        fmt, (w, h), _ = self.parse_dshow_opt(opt)
        return w * h, sum(get_image_size(fmt, w, h))

    def player_callback(self, mode, value):
        if mode == 'display_sub':
            return
        if mode.endswith('error'):
            try:
                raise Exception('Player: {}, {}'.format(mode, value))
            except Exception as e:
                Clock.schedule_once(partial(
                    self.err_callback,
                    msg='Player: {}, {}'.format(mode, value),
                    exc_info=sys.exc_info(), e=e),
                    0)

        if not mode == 'eof':
            self._request_stop('play')

    def set_pause(self, state):
        if self.play_state != 'playing' or self.play_paused == state:
            return
        self.play_paused = state

    def play_thread_run(self):
        self.frames_played = 0
        self.ts_play = self.real_rate = 0.
        ff_opts = {'sync': 'video', 'an': True, 'sn': True, 'paused': True}
        ifmt, icodec = self.file_fmt, self.icodec
        if ifmt:
            ff_opts['f'] = ifmt
        if icodec:
            ff_opts['vcodec'] = icodec
        ipix_fmt, iw, ih, _ = self.metadata_play
        ff_opts['x'] = iw
        ff_opts['y'] = ih

        lib_opts = {}
        if ifmt == 'dshow':
            rate = self.metadata_record.rate
            if self.dshow_opt:
                fmt, size, (rmin, rmax) = self.parse_dshow_opt(self.dshow_opt)
                lib_opts['pixel_format'] = fmt
                lib_opts['video_size'] = '{}x{}'.format(*size)
                if rate:
                    rate = min(max(rate, rmin), rmax)
                    lib_opts['framerate'] = '{}'.format(rate)
            elif rate:
                lib_opts['framerate'] = '{}'.format(rate)

        fname = self.play_filename
        if ifmt == 'dshow':
            fname = 'video={}'.format(self.dshow_true_filename)

        try:
            ffplayer = MediaPlayer(
                fname, callback=self.player_callback, ff_opts=ff_opts,
                lib_opts=lib_opts)
        except Exception as e:
            self.change_status('play', False, e)
            return

        src_fmt = ''
        s = clock()
        while self.play_state == 'starting' and clock() - s < 30.:
            src_fmt = ffplayer.get_metadata().get('src_pix_fmt')
            if src_fmt:
                break
            time.sleep(0.01)
        if not src_fmt:
            try:
                raise ValueError("Player failed, couldn't get pixel type")
            except Exception as e:
                self.change_status('play', False, e)
                return

        if ipix_fmt:
            src_fmt = ipix_fmt
        fmt = {'gray': 'gray', 'rgb24': 'rgb24', 'bgr24': 'rgb24',
               'rgba': 'rgba', 'bgra': 'rgba'}.get(src_fmt, 'yuv420p')
        ffplayer.set_output_pix_fmt(fmt)

        ffplayer.toggle_pause()
        logging.info('Player: input, output formats are: {}, {}'
                     .format(src_fmt, fmt))

        img = None
        s = clock()
        while self.play_state == 'starting' and clock() - s < 30.:
            img, val = ffplayer.get_frame()
            if val == 'eof':
                try:
                    raise ValueError("Player failed, reached eof")
                except Exception as e:
                    self.change_status('play', False, e)
                    return

            if img:
                ivl_start = clock()
                break
            time.sleep(0.01)

        rate = ffplayer.get_metadata().get('frame_rate')
        if rate == (0, 0):
            try:
                raise ValueError("Player failed, couldn't read frame rate")
            except Exception as e:
                self.change_status('play', False, e)
                return

        if not img:
            try:
                raise ValueError("Player failed, couldn't read frame")
            except Exception as e:
                self.change_status('play', False, e)
                return

        rate = rate[0] / float(rate[1])
        w, h = img[0].get_size()
        fmt = img[0].get_pixel_format()
        last_queue = self.image_queue
        put = None
        trigger = self.display_trigger
        use_rt = self.use_real_time

        Clock.schedule_once(
            partial(eat_first, self.update_metadata, rate=rate, w=w, h=h,
                    fmt=fmt), 0)
        self.change_status('play', True)
        self.last_image = img[0], ivl_start if use_rt else img[1]
        if last_queue is not None:
            put = last_queue.put
            put(('rate', rate))
            put((img[0], ivl_start if use_rt else img[1]))
        trigger()

        tdiff = 1 / (rate * 2.)
        self.ts_play = ivl_start
        count = 1
        time_excess = 0
        self.frames_played = 1

        try:
            while self.play_state != 'stopping':
                if self.play_paused:
                    ts = clock()
                    ffplayer.set_pause(True)

                    while self.play_paused and self.play_state != 'stopping':
                        time.sleep(.1)
                    if not self.play_paused:
                        ffplayer.set_pause(False)

                    time_excess += clock() - ts
                    continue

                img, val = ffplayer.get_frame()
                ivl_end = clock() - time_excess

                if ivl_end - ivl_start >= 1.:
                    self.real_rate = count / (ivl_end - ivl_start)
                    count = 0
                    ivl_start = ivl_end

                if val == 'paused':
                    raise ValueError("Player {} got {}".format(self, val))
                if val == 'eof':
                    break

                if not img:
                    time.sleep(min(val, tdiff) if val else tdiff)
                    continue

                count += 1
                self.frames_played += 1

                if last_queue is not self.image_queue:
                    last_queue = self.image_queue
                    if last_queue is not None:
                        put = last_queue.put
                        put(('rate', rate))
                    else:
                        put = None

                if put is not None:
                    put((img[0], ivl_end if use_rt else img[1]))

                self.last_image = img[0], ivl_end if use_rt else img[1]
                trigger()
        except Exception as e:
            self.change_status('play', False, e)
            return
        self.change_status('play', False)


class RTVPlayer(Player):
    '''Wrapper for RTV based player.
    '''

    __settings_attrs__ = ('remote_computer_name', 'pipe_name', 'port',
                          'video_fmt')

    video_fmts = {
        'full_NTSC': (640, 480), 'full_PAL': (768, 576),
        'CIF_NTSC': (320, 240), 'CIF_PAL': (384, 288),
        'QCIF_NTSC': (160, 120), 'QCIF_PAL': (192, 144)
    }

    remote_computer_name = StringProperty('')
    '''The name of the computer running Barst, if it's a remote computer.
    Otherwise it's the empty string.
    '''

    pipe_name = StringProperty('filers_rtv')
    '''The internal name used to communicate with Barst. When running remotely,
    the name is used to discover Barst.
    '''

    port = NumericProperty(0)
    '''The RTV port on the card to use.
    '''

    video_fmt = StringProperty('full_NTSC')
    '''The video format of the video being played.

    It can be one of the keys in::

        {'full_NTSC': (640, 480), 'full_PAL': (768, 576),
        'CIF_NTSC': (320, 240), 'CIF_PAL': (384, 288),
        'QCIF_NTSC': (160, 120), 'QCIF_PAL': (192, 144)}
    '''

    channel = None

    def __init__(self, **kwargs):
        super(RTVPlayer, self).__init__(**kwargs)
        self.metadata_play = self.metadata_play_used = \
            VideoMetadata('gray', 0, 0, 0)
        self.on_port()

    def on_port(self, *largs):
        self.player_summery = 'RTV-Port{}'.format(self.port)

    def play_thread_run(self):
        self.frames_played = 0
        self.ts_play = self.real_rate = 0.
        files = (
            r'C:\Program Files\Barst\Barst.exe',
            r'C:\Program Files\Barst\Barst64.exe',
            r'C:\Program Files (x86)\Barst\Barst.exe')
        if hasattr(sys, '_MEIPASS'):
            files = files + (join(sys._MEIPASS, 'Barst.exe'),
                             join(sys._MEIPASS, 'Barst64.exe'))
        barst_bin = None
        for f in files:
            f = abspath(f)
            if isfile(f):
                barst_bin = f
                break

        local = not self.remote_computer_name
        name = self.remote_computer_name if not local else '.'
        pipe_name = self.pipe_name
        full_name = r'\\{}\pipe\{}'.format(name, pipe_name)

        try:
            server = BarstServer(barst_path=barst_bin, pipe_name=full_name)
            server.open_server()
            img_fmt = self.metadata_play.fmt
            w, h = self.video_fmts[self.video_fmt]
            chan = RTVChannel(
                chan=self.port, server=server, video_fmt=self.video_fmt,
                frame_fmt=img_fmt, luma_filt=img_fmt == 'gray', lossless=True)
            chan.open_channel()
            try:
                chan.close_channel_server()
            except:
                pass
            chan.open_channel()
            chan.set_state(True)

            last_queue = None
            put = None
            started = False
            trigger = self.display_trigger
            use_rt = self.use_real_time
            count = 0

            while self.play_state != 'stopping':
                ts, buf = chan.read()
                if not started:
                    self.ts_play = ivl_start = clock()
                    self.change_status('play', True)
                    started = True

                ivl_end = clock()
                if ivl_end - ivl_start >= 1.:
                    self.real_rate = count / (ivl_end - ivl_start)
                    count = 0
                    ivl_start = ivl_end

                count += 1
                self.frames_played += 1

                if last_queue is not self.image_queue:
                    last_queue = self.image_queue
                    if last_queue is not None:
                        put = last_queue.put
                        put(('rate', 29.97))
                    else:
                        put = None

                img = Image(plane_buffers=[buf], pix_fmt=img_fmt, size=(w, h))
                if put is not None:
                    put((img, ivl_end if use_rt else ts))

                self.last_image = img, ivl_end if use_rt else ts
                trigger()
        except Exception as e:
            self.change_status('play', False, e)
            try:
                chan.close_channel_server()
            except:
                pass
            return

        try:
            chan.close_channel_server()
        except:
            pass
        self.change_status('play', False)


class PTGrayPlayer(Player):
    '''Wrapper for Point Gray based player.
    '''

    __settings_attrs__ = ('serial', 'ip', 'cam_config_opts')

    serial = NumericProperty(0)
    '''The serial number of the camera to open. Either :attr:`ip` or
    :attr:`serial` must be provided.
    '''

    serials = ListProperty([])

    ip = StringProperty('')
    '''The ip address of the camera to open. Either :attr:`ip` or
    :attr:`serial` must be provided.
    '''

    ips = ListProperty([])

    cam_config_opts = DictProperty({})
    '''The configuration options used to configure the camera after opening.
    '''

    config_thread = None

    config_queue = None

    config_active = ListProperty([])

    ffmpeg_pix_map = {
        'mono8': 'gray', 'yuv411': 'uyyvyy411', 'yuv422': 'uyvy422',
        'yuv444': 'yuv444p', 'rgb8': 'rgb8', 'mono16': 'gray16le',
        'rgb16': 'rgb565le', 's_mono16': 'gray16le', 's_rgb16': 'rgb565le',
        'bgr': 'bgr24', 'bgru': 'bgra', 'rgb': 'rgb24', 'rgbu': 'rgba',
        'bgr16': 'bgr565le', 'yuv422_jpeg': 'yuvj422p'}

    def __init__(self, **kwargs):
        super(PTGrayPlayer, self).__init__(**kwargs)
        self.on_ip()
        if CameraContext is not None:
            self.start_config()

    def on_serial(self, *largs):
        self.ask_config('serial')

    def on_ip(self, *largs):
        self.player_summery = 'PT-{}'.format(self.ip)
        self.ask_config('serial')

    def start_config(self, *largs):
        self.config_queue = Queue()
        self.config_active = []
        thread = self.config_thread = Thread(
            target=self.config_thread_run, name='Config thread')
        thread.start()
        self.ask_config('serials')

    def stop_all(self, join=False):
        super(PTGrayPlayer, self).stop_all(join=join)
        self.ask_config('eof')
        if join and self.config_thread:
            self.config_thread.join()

    def ask_config(self, item):
        queue = self.config_queue
        if queue is not None:
            self.config_active.append(item)
            queue.put_nowait(item)

    def finish_ask_config(self, item, *largs, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def write_gige_opts(self, c, opts):
        c.set_gige_mode(opts['mode'])
        c.set_drop_mode(opts['drop'])
        c.set_gige_config(opts['offset_x'], opts['offset_y'], opts['width'],
                          opts['height'], opts['fmt'])
        c.set_gige_packet_config(opts['resend'], opts['resend_timeout'],
                                 opts['max_resend_packets'])
        c.set_gige_binning(opts['horizontal'], opts['vertical'])

    def read_gige_opts(self, c):
        opts = self.cam_config_opts
        opts['drop'] = c.get_drop_mode()
        opts.update(c.get_gige_config())
        opts['mode'] = c.get_gige_mode()
        opts.update(c.get_gige_packet_config())
        opts['horizontal'], opts['vertical'] = c.get_gige_binning()

    def config_thread_run(self):
        queue = self.config_queue
        cc = CameraContext()
        state = self.config_active

        while True:
            item = queue.get()
            try:
                if item == 'eof':
                    return

                ip = ''
                serial = 0
                do_serial = False
                if item == 'serials':
                    cc.rescan_bus()
                    cams = cc.get_gige_cams()
                    old_serial = serial = self.serial
                    old_ip = ip = self.ip

                    ips = ['.'.join(map(str, Camera(serial=s).ip))
                           for s in cams]
                    if cams:
                        if serial not in cams and ip not in ips:
                            serial = cams[0]
                            ip = ips[0]
                        elif serial in cams:
                            ip = ips[cams.index(serial)]
                        else:
                            serial = cams[ips.index(ip)]

                    Clock.schedule_once(partial(
                        self.finish_ask_config, item, serials=cams,
                        serial=serial, ips=ips, ip=ip))

                    if serial:
                        c = Camera(serial=serial)
                        c.connect()
                        if old_serial == serial or old_ip == ip:
                            self.write_gige_opts(c, self.cam_config_opts)
                        self.read_gige_opts(c)
                        c.disconnect()
                        c = None
                elif item == 'serial':
                    do_serial = True
                elif item == 'gui':
                    gui = GUI()
                    gui.show_selection()
                    do_serial = True  # read possibly updated config

                if do_serial:
                    _ip = ip = self.ip
                    serial = self.serial
                    if serial or ip:
                        if _ip:
                            _ip = map(int, _ip.split('.'))
                        c = Camera(serial=serial or None, ip=_ip or None)
                        serial = c.serial
                        ip = '.'.join(map(str, c.ip))
                        c.connect()
                        self.read_gige_opts(c)
                        c.disconnect()
                        c = None

                if serial or ip:
                    opts = self.cam_config_opts
                    if opts['fmt'] not in self.ffmpeg_pix_map:
                        raise Exception('Pixel format {} cannot be converted'.
                                        format(opts['fmt']))
                    if opts['fmt'] == 'yuv411':
                        raise ValueError('yuv411 is not currently supported')
                    metadata = VideoMetadata(
                        self.ffmpeg_pix_map[opts['fmt']], opts['width'],
                        opts['height'], 30.0)
                    Clock.schedule_once(partial(
                        self.finish_ask_config, item, metadata_play=metadata,
                        metadata_play_used=metadata, serial=serial, ip=ip))
            except Exception as e:
                Clock.schedule_once(partial(
                    self.err_callback,
                    msg='PTGray configuration: {}'.format(self),
                    exc_info=sys.exc_info(), e=e),
                    0)
            finally:
                state.remove(item)

    def play_thread_run(self):
        self.frames_played = 0
        self.ts_play = self.real_rate = 0.
        c = None
        ffmpeg_fmts = self.ffmpeg_pix_map

        try:
            ip = map(int, self.ip.split('.')) if self.ip else None
            c = Camera(serial=self.serial or None, ip=ip)
            c.connect()

            last_queue = None
            put = None
            started = False
            trigger = self.display_trigger
            # use_rt = self.use_real_time
            count = 0
            rate = self.metadata_play_used.rate

            c.start_capture()
            while self.play_state != 'stopping':
                try:
                    c.read_next_image()
                except Exception as e:
                    self.frames_skipped += 1
                    continue
                if not started:
                    self.ts_play = ivl_start = clock()
                    self.change_status('play', True)
                    started = True

                ivl_end = clock()
                if ivl_end - ivl_start >= 1.:
                    self.real_rate = count / (ivl_end - ivl_start)
                    count = 0
                    ivl_start = ivl_end

                count += 1
                self.frames_played += 1

                if last_queue is not self.image_queue:
                    last_queue = self.image_queue
                    if last_queue is not None:
                        put = last_queue.put
                        put(('rate', rate))
                    else:
                        put = None

                image = c.get_current_image()
                pix_fmt = image['pix_fmt']
                if pix_fmt not in ffmpeg_fmts:
                    raise Exception('Pixel format {} cannot be converted'.
                                    format(pix_fmt))
                ff_fmt = ffmpeg_fmts[pix_fmt]
                if ff_fmt == 'yuv444p':
                    buff = image['buffer']
                    img = Image(
                        plane_buffers=[buff[1::3], buff[0::3], buff[2::3]],
                        pix_fmt=ff_fmt, size=(image['cols'], image['rows']))
                elif pix_fmt == 'yuv411':
                    raise ValueError('yuv411 is not currently supported')
                else:
                    img = Image(
                        plane_buffers=[image['buffer']], pix_fmt=ff_fmt,
                        size=(image['cols'], image['rows']))
                if put is not None:
                    put((img, ivl_end))

                self.last_image = img, ivl_end
                trigger()
        except Exception as e:
            self.change_status('play', False, e)
            try:
                c.disconnect()
            except:
                pass
            return

        try:
            c.disconnect()
        except:
            pass
        self.change_status('play', False)
