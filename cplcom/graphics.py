
__all__ = ('VirtualSwitch', )


import math
from os.path import join, dirname
from time import clock

from kivy.uix.widget import Widget
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.behaviors import ToggleButtonBehavior
from kivy.uix.popup import Popup
from kivy.lang import Factory, Builder
from kivy.properties import (
    ObjectProperty, StringProperty, NumericProperty, BooleanProperty,
    ListProperty)
from kivy.clock import Clock
from kivy.graphics import Rectangle, BindTexture
from kivy.graphics.texture import Texture
from kivy.graphics.fbo import Fbo

from cplcom.utils import pretty_time


Builder.load_file(join(dirname(__file__), 'graphics.kv'))


class LabeledIcon(Widget):

    text = StringProperty('')


class VirtualSwitch(object):
    '''Requires it be combined with class that has a state property.
    '''

    def __init__(self, **kw):
        super(VirtualSwitch, self).__init__(**kw)
        Clock.schedule_once(self._bind_button)

    def _bind_button(self, *largs):
        if (not self.read_only and not self.virtual):
            self.bind(state=self.update_from_button)

    dev = ObjectProperty(None, allownone=True)

    _dev = None

    chan_name = StringProperty('state')

    read_only = BooleanProperty(False)
    '''Whether pressing the button will change the device state (False) or
    if the device only updates the button.
    '''

    virtual = BooleanProperty(False)
    '''If it's backed up by a button. Similar to app.simulate, but even if
    that's false it could be kivy button backed.
    '''

    is_port = BooleanProperty(True)

    _last_chan_value = None

    def on_dev(self, *largs):
        if self._dev:
            self._dev.unbind(**{self.chan_name: self.update_from_channel})
        self._dev = self.dev
        if (self.dev and not self.virtual):
            self.dev.bind(**{self.chan_name: self.update_from_channel})

    def update_from_channel(self, *largs):
        '''A convenience method which takes the state of the simulated device
        (buttons) and the state of the actual device and returns if the
        simulated device should be `'down'` or `'normal'`.

        It is used to set the button state to match the actual device state,
        if not simulating.
        '''

        self._last_chan_value = state = getattr(self.dev, self.chan_name)
        self.state = 'down' if state else 'normal'
        self._last_chan_value = None

    def update_from_button(self, *largs):
        '''A convenience method which takes the state of the simulated device
        (buttons) and sets the state of the actual device to match it when not
        simulating.
        '''
        dev = self.dev
        if dev is not None:
            if self.state == 'down':
                if self._last_chan_value is not True:
                    self._last_chan_value = None
                    if self.is_port:
                        dev.set_state(high=[self.chan_name])
                    else:
                        dev.set_state(True)
            else:
                if self._last_chan_value is not False:
                    self._last_chan_value = None
                    if self.is_port:
                        dev.set_state(low=[self.chan_name])
                    else:
                        dev.set_state(False)


class ToggleSwitch(ToggleButtonBehavior, VirtualSwitch, LabeledIcon):
    pass


class PortSwitch(ToggleSwitch):
    pass


class DarkPortSwitch(PortSwitch):
    pass


class PortContainer(GridLayout):

    num_devs = NumericProperty(8)

    name_pat = StringProperty('p{}')

    def __init__(self, **kwargs):
        super(PortContainer, self).__init__(**kwargs)
        if '__no_builder' in kwargs:
            Clock.schedule_once(self.populate_devs)
        else:
            self.populate_devs()

    def populate_devs(self, *largs):
        classes = [PortSwitch, DarkPortSwitch] * int(
            math.ceil(self.num_devs / 2.))
        pat = self.name_pat
        for i, cls in enumerate(classes):
            self.add_widget(cls(chan_name=pat.format(i)))


class FFImage(Widget):

    YUV_RGB_FS = """
    $HEADER$
    uniform sampler2D tex_y;
    uniform sampler2D tex_u;
    uniform sampler2D tex_v;

    void main(void) {
        float y = texture2D(tex_y, tex_coord0).r;
        float u = texture2D(tex_u, tex_coord0).r - 0.5;
        float v = texture2D(tex_v, tex_coord0).r - 0.5;
        float r = y +             1.402 * v;
        float g = y - 0.344 * u - 0.714 * v;
        float b = y + 1.772 * u;
        gl_FragColor = vec4(r, g, b, 1.0);
    }
    """

    fmt_conversion = {'rgb24': 'rgb', 'gray': 'luminance'}

    _texture = ObjectProperty(None)
    _pix_fmt = ''

    def display(self, img):
        fmt = img.get_pixel_format()
        if (list(img.get_size()) != self.size or self._texture is None or
                self._pix_fmt != fmt):
            self.size = w, h = img.get_size()
            self._pix_fmt = fmt
            if fmt not in ('rgb24', 'yuv420p', 'gray'):
                raise TypeError(
                    '{} is not an accepted image format'.format(fmt))

            if fmt == 'yuv420p':
                w2 = int(w / 2)
                h2 = int(h / 2)
                self._tex_y = Texture.create(
                    size=(w, h), colorfmt='luminance')
                self._tex_u = Texture.create(
                    size=(w2, h2), colorfmt='luminance')
                self._tex_v = Texture.create(
                    size=(w2, h2), colorfmt='luminance')
                with self.canvas:
                    self._fbo = fbo = Fbo(size=self.size)
                with fbo:
                    BindTexture(texture=self._tex_u, index=1)
                    BindTexture(texture=self._tex_v, index=2)
                    Rectangle(size=fbo.size, texture=self._tex_y)
                fbo.shader.fs = FFImage.YUV_RGB_FS
                fbo['tex_y'] = 0
                fbo['tex_u'] = 1
                fbo['tex_v'] = 2
                self._texture = fbo.texture
            else:
                self._texture = Texture.create(
                    size=self.size, colorfmt=FFImage.fmt_conversion[fmt])

            # XXX FIXME
            # self.texture.add_reload_observer(self.reload_buffer)
            self._texture.flip_vertical()

        if self._texture is not None:
            if fmt == 'yuv420p':
                dy, du, dv, _ = img.to_memoryview()
                self._tex_y.blit_buffer(dy, colorfmt='luminance')
                self._tex_u.blit_buffer(du, colorfmt='luminance')
                self._tex_v.blit_buffer(dv, colorfmt='luminance')
                self._fbo.ask_update()
                self._fbo.draw()
            else:
                self._texture.blit_buffer(
                    img.to_memoryview()[0],
                    colorfmt=FFImage.fmt_conversion[fmt])
            self.canvas.ask_update()


class TimeLineSlice(Widget):

    end_t = NumericProperty(0)

    elapsed_t = NumericProperty(0)

    start_t = NumericProperty(0)

    color = ObjectProperty((1, 1, 1))

    color_odd = ObjectProperty((0, .7, .2))

    color_even = ObjectProperty((0, .2, .7))

    text = StringProperty('')

    parent = ObjectProperty(None, allownone=True, rebind=True)


class TimeLine(Widget):

    range = NumericProperty(1)

    slices = ListProperty([])

    slice_names = ListProperty([])

    current_slice = NumericProperty(0)

    offset = NumericProperty(0)

    timer = StringProperty('')

    text = StringProperty('')

    scale = NumericProperty(0)

    start_t = NumericProperty(clock())

    def __init__(self, **kwargs):
        super(TimeLine, self).__init__(**kwargs)
        Clock.schedule_interval(self.update_clock, .15)

    def update_clock(self, dt):
        elapsed = clock() - self.start_t
        self.timer = pretty_time(elapsed)
        if self.slices:
            self.slices[self.current_slice].elapsed_t = elapsed

    def set_active_slice(self, idx):
        for s in self.slices[:idx]:
            s.elapsed_t = s.end_t - s.start_t
        for s in self.slices[idx:]:
            s.elapsed_t = 0.
        self.current_slice = idx
        self.start_t = clock()
        if self.slices:
            self.text = self.slices[idx].text
        else:
            self.text = 'Init'

    def update_slice_time(self, idx, duration):
        s0 = self.slices[idx]
        ts = s0.start_t
        for s in self.slices[idx:]:
            if s != s0:
                duration = s.end_t - s.start_t
            s.start_t = ts
            ts = s.end_t = ts + duration

    def update_slices(self, end_times, text):
        for ch in self.children[:-1]:
            self.remove_widget(ch)
        self.slices = []
        ts = 0
        slices = self.slices
        for t, txt in zip(end_times, text):
            slices.append(TimeLineSlice(start_t=ts, end_t=t, text=txt))
            ts = t
        for s in slices:
            self.add_widget(s)


class ErrorPopup(Popup):
    pass

Factory.register('VirtualSwitch', cls=VirtualSwitch)
