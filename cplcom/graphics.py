
__all__ = ('VirtualSwitch', )


from os.path import join, dirname
from time import clock
from math import pow

from kivy.uix.widget import Widget
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.lang import Builder
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

    duration = NumericProperty(0)

    elapsed_t = NumericProperty(0)

    scale = NumericProperty(0)

    color = ObjectProperty(None, allownone=True)

    _color = ListProperty([(1, 1, 1, 1), (1, 1, 1, 1)])

    name = StringProperty('')

    text = StringProperty('')

    parent = ObjectProperty(None, allownone=True, rebind=True)


class TimeLine(BoxLayout):

    slices = ListProperty([])

    slice_names = ListProperty([])

    current_slice = NumericProperty(None, allownone=True)

    timer = StringProperty('')

    text = StringProperty('')

    color_odd = ListProperty([(0, .7, .2, 1), (.5, .5, 0, 1)])

    color_even = ListProperty(
        [(0, .2, .7, 1), (135 / 255., 206 / 255., 250 / 255., 1)])

    _start_t = clock()

    def __init__(self, **kwargs):
        super(TimeLine, self).__init__(**kwargs)
        Clock.schedule_interval(self.update_clock, .15)

    def update_clock(self, dt):
        elapsed = clock() - self._start_t
        self.timer = pretty_time(elapsed)
        if self.slices and self.current_slice is not None:
            self.slices[self.current_slice].elapsed_t = elapsed

    def set_active_slice(self, name):
        try:
            idx = self.slice_names.index(name)
            for s in self.slices[:idx]:
                s.elapsed_t = max(s.duration, 10000)
            for s in self.slices[idx:]:
                s.elapsed_t = 0.
            self.current_slice = idx
        except ValueError:
            if self.current_slice is not None:
                for s in self.slices[:self.current_slice + 1]:
                    s.elapsed_t = max(s.duration, 10000)
            self.current_slice = None
            self.text = name
        self._start_t = clock()

    def clear_slices(self):
        for ch in self.box.children[:]:
            self.box.remove_widget(ch)
        self.current_slice = None
        self.slice_names = []
        self.slices = []

    def update_slice_attrs(self, name, **kwargs):
        s = self.slices[self.slice_names.index(name)]
        for key, val in kwargs.items():
            setattr(s, key, val)
        self._update_attrs()

    def _update_attrs(self):
        widgets = list(reversed(self.box.children))
        self.slice_names = [widget.name for widget in widgets]
        for i, wid in enumerate(widgets):
            wid._color = self.color_odd if i % 2 else self.color_even

    def add_slice(
            self, name, before=None, duration=0, size_hint_x=None, **kwargs):
        if 'text' not in kwargs:
            kwargs['text'] = name
        s = TimeLineSlice(
            duration=duration, name=name,
            size_hint_x=size_hint_x if size_hint_x is not None else duration,
            **kwargs)
        if before is not None:
            i = self.slice_names.index(before)
            old_len = len(self.slices)
            self.slices.insert(s, i)
            i = old_len - i
        else:
            self.slices.append(s)
            i = 0
        self.box.add_widget(s, index=i)
        self._update_attrs()

    def remove_slice(self, name):
        s = self.slices.pop(self.slice_names.index(name))
        self.box.remove_widget(s)
        self._update_attrs()

    def smear_slices(self):
        widgets = self.box.children
        vals = [w.duration for w in widgets if w.duration]
        mn, mx = min(vals), max(vals)
        center = (mn + mx) / 2.
        a = pow(mx - center, 3)
        offset = abs(pow(mn - center, 3) / a)
        f = lambda x: max((2 * pow(x - center, 3) / a) + offset, offset)
        for w in widgets:
            w.size_hint_x = f(w.duration)


class ErrorPopup(Popup):
    pass
