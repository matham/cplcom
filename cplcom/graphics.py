'''Graphics
============
'''
from os.path import join, dirname
from time import clock
from math import pow

from ffpyplayer.tools import get_best_pix_fmt
from ffpyplayer.pic import SWScale

from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import (
    NumericProperty, ReferenceListProperty, ObjectProperty,
    ListProperty, StringProperty, BooleanProperty, DictProperty, AliasProperty,
    OptionProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scatter import Scatter
from kivy.uix.popup import Popup
from kivy.graphics.texture import Texture
from kivy.graphics import Rectangle, BindTexture
from kivy.graphics.transformation import Matrix
from kivy.graphics.fbo import Fbo
from kivy.uix.behaviors import DragBehavior
from kivy.uix.widget import Widget
from kivy.uix.behaviors.knspace import KNSpaceBehavior
from kivy.uix.behaviors.button import ButtonBehavior
from kivy.uix.behaviors.focus import FocusBehavior
from kivy.animation import Sequence, Animation
from kivy.factory import Factory
from kivy.garden.filebrowser import FileBrowser

from cplcom.utils import pretty_time

__all__ = (
    'CallbackPopup', 'EventFocusBehavior', 'BufferImage', 'ErrorIndicator',
    'TimeLineSlice', 'TimeLine')


Builder.load_file(join(dirname(__file__), 'graphics.kv'))


class CallbackPopup(KNSpaceBehavior, DragBehavior, Popup):
    ''' A popup based class.
    '''
    pass


class EventFocusBehavior(FocusBehavior):

    __events__ = ('on_keypress', )

    keys = ListProperty(['spacebar', 'escape', 'enter'])

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        if super(EventFocusBehavior, self).keyboard_on_key_down(
                window, keycode, text, modifiers):
            return True
        if keycode[1] in self.keys:
            self.dispatch('on_keypress', keycode[1])
            return True

    def on_keypress(self, key):
        pass


class BufferImage(KNSpaceBehavior, Scatter):
    ''' Class that displays an image and allows its manipulation using touch.
    It receives an ffpyplayer :py:class:`~ffpyplayer.pic.Image` object.
    '''

    iw = NumericProperty(0.)
    ''' The width of the input image. Defaults to zero.
    '''
    ih = NumericProperty(0.)
    ''' The height of the input image. Defaults to zero.
    '''
    last_w = 0
    ''' The width of the screen region available to display the image. Can be
    used to determine if the screen size changed and we need to output a
    different sized image. This gets set internally by :meth:`update_img`.
    Defaults to zero.
    '''
    last_h = 0
    ''' The width of the screen region available to display the image. This
    gets set internally by :meth:`update_img`. Defaults to zero.
    '''
    fmt = ''
    ''' The input format of the last image passed in. E.g. rgb24, yuv420p, etc.
    '''

    sw_src_fmt = ''

    swscale = None

    img = None
    ''' Holds the last input :py:class:`~ffpyplayer.pic.Image`.
    '''

    texture_size = ObjectProperty((0, 0))

    img_texture = ObjectProperty(None)
    ''' The texture into which the images are blitted if not yuv420p.
    Defaults to None.
    '''
    kivy_fmt = ''
    ''' The last kivy color format type of the image. Defaults to `''`. '''
    _tex_y = None
    ''' The y texture into which the y plane of the images are blitted when
    yuv420p. Defaults to None.
    '''
    _tex_u = None
    ''' The u texture into which the u plane of the images are blitted when
    yuv420p. Defaults to None.
    '''
    _tex_v = None
    ''' The v texture into which the v plane of the images are blitted when
    yuv420p. Defaults to None.
    '''
    _fbo = None
    ''' The Fbo used when blitting yuv420p images. '''

    YUV_RGB_FS = b'''
    $HEADER$
    uniform sampler2D tex_y;
    uniform sampler2D tex_u;
    uniform sampler2D tex_v;

    void main(void) {
        float y = texture2D(tex_y, tex_coord0).r;
        float u = texture2D(tex_u, tex_coord0).r - 0.5;
        float v = texture2D(tex_v, tex_coord0).r - 0.5;
        float r = y + 1.402 * v;
        float g = y - 0.344 * u - 0.714 * v;
        float b = y + 1.772 * u;
        gl_FragColor = vec4(r, g, b, 1.0);
    }
    '''
    ''' The shader code used blitting yuv420p images.
    '''

    def update_img(self, img):
        ''' Updates the screen with a new image.
        '''
        if img is None:
            return

        img_fmt = img.get_pixel_format()
        img_w, img_h = img.get_size()

        update = False
        if self.iw != img_w or self.ih != img_h:
            update = True

        if img_fmt not in ('yuv420p', 'rgba', 'rgb24', 'gray'):
            swscale = self.swscale
            if img_fmt != self.sw_src_fmt or swscale is None or update:
                ofmt = get_best_pix_fmt(
                    img_fmt, ('yuv420p', 'rgba', 'rgb24', 'gray'))
                self.swscale = swscale = SWScale(
                    iw=img_w, ih=img_h, ifmt=img_fmt, ow=0, oh=0, ofmt=ofmt)
                self.sw_src_fmt = img_fmt
            img = swscale.scale(img)
            img_fmt = img.get_pixel_format()

        w, h = self.size
        if (not w) or not h:
            self.img = img
            return

        if self.fmt != img_fmt:
            self.fmt = img_fmt
            self.kivy_ofmt = {'yuv420p': 'yuv420p', 'rgba': 'rgba',
                              'rgb24': 'rgb', 'gray': 'luminance'}[img_fmt]
            update = True

        if update or w != self.last_w or h != self.last_h:
            scalew, scaleh = w / float(img_w), h / float(img_h)
            scale = min(min(scalew, scaleh), 1)
            pos = self.pos
            self.transform = Matrix()
            self.pos = pos
            self.apply_transform(Matrix().scale(scale, scale, 1),
                                 post_multiply=True)
            self.iw, self.ih = img_w, img_h
            self.last_h = h
            self.last_w = w

        self.img = img
        kivy_ofmt = self.kivy_ofmt

        if update:
            self.canvas.remove_group(str(self) + 'image_display')
            if kivy_ofmt == 'yuv420p':
                w2 = int(img_w / 2)
                h2 = int(img_h / 2)
                self._tex_y = Texture.create(size=(img_w, img_h),
                                             colorfmt='luminance')
                self._tex_u = Texture.create(size=(w2, h2),
                                             colorfmt='luminance')
                self._tex_v = Texture.create(size=(w2, h2),
                                             colorfmt='luminance')
                with self.canvas:
                    self._fbo = fbo = Fbo(size=(img_w, img_h),
                                          group=str(self) + 'image_display')
                with fbo:
                    BindTexture(texture=self._tex_u, index=1)
                    BindTexture(texture=self._tex_v, index=2)
                    Rectangle(size=fbo.size, texture=self._tex_y)
                fbo.shader.fs = BufferImage.YUV_RGB_FS
                fbo['tex_y'] = 0
                fbo['tex_u'] = 1
                fbo['tex_v'] = 2
                tex = self.img_texture = fbo.texture
                fbo.add_reload_observer(self.reload_buffer)
            else:
                tex = self.img_texture = Texture.create(
                    size=(img_w, img_h), colorfmt=kivy_ofmt)
                tex.add_reload_observer(self.reload_buffer)

            tex.flip_vertical()
            self.texture_size = img_w, img_h

        if kivy_ofmt == 'yuv420p':
            dy, du, dv, _ = img.to_memoryview()
            self._tex_y.blit_buffer(dy, colorfmt='luminance')
            self._tex_u.blit_buffer(du, colorfmt='luminance')
            self._tex_v.blit_buffer(dv, colorfmt='luminance')
            self._fbo.ask_update()
            self._fbo.draw()
        else:
            self.img_texture.blit_buffer(img.to_memoryview()[0],
                                         colorfmt=kivy_ofmt)
            self.canvas.ask_update()

    def reload_buffer(self, *args):
        ''' Reloads the last displayed image. It is called whenever the
        screen size changes or the last image need to be recalculated.
        '''
        self.update_img(self.img)


class ErrorIndicator(KNSpaceBehavior, ButtonBehavior, Widget):

    display = None

    seen = BooleanProperty(True)

    alpha = NumericProperty(1.)

    queue = ListProperty([])

    anim = None

    def __init__(self, **kw):
        super(ErrorIndicator, self).__init__(**kw)
        a = self.anim = Sequence(
            Animation(t='in_bounce', alpha=1.),
            Animation(t='out_bounce', alpha=0))
        a.repeat = True
        self.display = Factory.ErrorLog(title='Error Log')

    def on_queue(self, *largs):
        display = self.display
        cls = Factory.ErrorLabel
        display.container.clear_widgets()
        add = display.container.add_widget
        q = self.queue
        for t in q:
            add(cls(text=t))

        if q and self.seen:
            self.seen = False
            self.anim.start(self)


class TimeLineSlice(Widget):

    duration = NumericProperty(0)

    elapsed_t = NumericProperty(0)

    scale = NumericProperty(0)

    color = ObjectProperty(None, allownone=True)

    _color = ListProperty([(1, 1, 1, 1), (1, 1, 1, 1)])

    name = StringProperty('')

    text = StringProperty('')


class TimeLine(KNSpaceBehavior, BoxLayout):

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

    def set_active_slice(self, name, after=None):
        try:
            idx = self.slice_names.index(name)
            for s in self.slices[:idx]:
                s.elapsed_t = max(s.duration, 10000)
            for s in self.slices[idx:]:
                s.elapsed_t = 0.
            self.current_slice = idx
        except ValueError:
            if after is not None:
                idx = self.slice_names.index(after)
                for s in self.slices[:idx + 1]:
                    s.elapsed_t = max(s.duration, 10000)
                for s in self.slices[idx + 1:]:
                    s.elapsed_t = 0.
            elif self.current_slice is not None:
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

        def f(x):
            return max((2 * pow(x - center, 3) / a) + offset, offset)

        for w in widgets:
            w.size_hint_x = f(w.duration)
