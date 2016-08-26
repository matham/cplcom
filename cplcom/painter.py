
from functools import partial
from math import cos, sin, atan2, pi
from copy import copy, deepcopy

from kivy.uix.widget import Widget
from kivy.uix.behaviors.focus import FocusBehavior
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import OptionProperty, BooleanProperty, NumericProperty, \
    ListProperty
from kivy.graphics import Ellipse, Line, Color, Point, Mesh, PushMatrix, \
    PopMatrix, Rotate, Bezier
from kivy.graphics.tesselator import Tesselator
from kivy.event import EventDispatcher

from kivy.garden.collider import CollideEllipse, Collide2DPoly, CollideBezier


def eucledian_dist(x1, y1, x2, y2):
    return ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5


class PaintCanvas(FocusBehavior, Widget):
    ''':attr:`shapes`, :attr:`selected_shapes`, :attr:`draw_mode`,
    :attr:`current_shape`, :attr:`locked`, :attr:`select`, and
    :attr:`selection_shape` are the attributes that make up the state machine.
    '''

    shapes = ListProperty([])

    selected_shapes = ListProperty([])

    draw_mode = OptionProperty('freeform', options=[
        'circle', 'ellipse', 'polygon', 'freeform', 'bezier', 'none'])

    current_shape = None
    '''Holds shape currently being edited. Can be a finished shape, e.g. if
    a point is selected.

    Either :attr:`current_shape` or :attr:`selection_shape` or both must be
    None.
    '''

    selected_point_shape = None

    locked = BooleanProperty(False)
    '''When locked, only selection is allowed. We cannot select points
    (except in :attr:`selection_shape`) and :attr:`current_shape` must
    be None.
    '''

    select = BooleanProperty(False)
    '''When selecting, instead of creating new shapes, the new shape will
    act as a selection area.
    '''

    selection_shape = None

    add_selection = BooleanProperty(True)

    min_touch_dist = dp(10)

    long_touch_delay = .7

    _long_touch_trigger = None

    _ctrl_down = None

    line_color = 0, 1, 0, 1

    line_color_edit = 1, 0, 0, 1

    line_color_selector = 1, .4, 0, 1

    selection_color = 1, 1, 1, .5

    def __init__(self, **kwargs):
        super(PaintCanvas, self).__init__(**kwargs)
        self._ctrl_down = set()

    def on_locked(self, *largs):
        if not self.locked:
            return
        if self._long_touch_trigger:
            self._long_touch_trigger.cancel()
            self._long_touch_trigger = None

        self.clear_selected_point_shape(False)
        self.finish_current_shape()
        for shape in self.shapes:
            shape.clean()

    def on_select(self, *largs):
        if self.select:
            self.finish_current_shape()
            self.clear_selected_point_shape(False)
        else:
            self.finish_selection_shape()

    def on_draw_mode(self, *largs):
        self.finish_selection_shape()
        self.finish_current_shape()

    def finish_current_shape(self):
        '''Returns True if there was a unfinished shape that was finished.
        '''
        shape = self.current_shape
        if shape:
            res = False
            if self.selected_point_shape is shape:
                res = self.clear_selected_point_shape()
            # if it was finished, but just selected, it doesn't count
            res = shape.finish() or res
            shape.clean()
            self.current_shape = None
            if not shape.is_valid:
                self.remove_shape(shape)
            return res
        return False

    def finish_selection_shape(self, do_select=False):
        '''Returns True if there was a selection shape that was finished.
        '''
        selection = self.selection_shape
        if selection:
            if self.selected_point_shape is selection:
                self.clear_selected_point_shape()
            selection.finish()
            selection.clean()

            if do_select and selection.is_valid:
                shapes = [shape for shape in self.shapes
                          if shape.collide_shape(selection)]
                if shapes:
                    if not self.add_selection and not self._ctrl_down:
                        self.clear_selected_shapes()
                    for shape in shapes:
                        self.select_shape(shape)

            selection.remove_paint_widget()
            self.selection_shape = None
            return True
        return False

    def clear_selected_shapes(self):
        shapes = self.selected_shapes[:]
        self.selected_shapes = []
        for shape in shapes:
            self.deselect_shape(shape)
        return shapes

    def clear_selected_point_shape(self, clear_selection=True,
                                   exclude_point=(None, None)):
        if self.selected_point_shape:
            if not clear_selection \
                    and self.selected_point_shape is self.selection_shape:
                return False
            eshape, ep = exclude_point
            if self.selected_point_shape is not eshape:
                ep = None
            if self.selected_point_shape.clear_point_selection(ep):
                self.selected_point_shape = None
                return True
        return False

    def delete_selected_point(self):
        if self.selected_point_shape \
                and self.selected_point_shape.delete_selected_point():
            self.selected_point_shape = None
            return True
        return False

    def delete_selected_shapes(self):
        shapes = self.selected_shapes[:]
        for shape in shapes:
            self.remove_shape(shape)
        return shapes

    def select_shape(self, shape):
        if shape.select():
            self.selected_shapes.append(shape)
            return True
        return False

    def deselect_shape(self, shape):
        if shape.deselect():
            if shape in self.selected_shapes:
                self.selected_shapes.remove(shape)
            return True
        return False

    def remove_shape(self, shape):
        if shape is self.current_shape:
            self.finish_current_shape()
        elif shape is self.selection_shape:
            self.finish_selection_shape()
        if shape is self.selected_point_shape:
            self.clear_selected_point_shape()
        self.deselect_shape(shape)
        shape.remove_paint_widget()
        self.shapes.remove(shape)

    def duplicate_selected_shapes(self):
        shapes = self.selected_shapes[:]
        self.clear_selected_shapes()
        our_shapes = self.shapes
        for shape in shapes:
            shape = deepcopy(shape)
            our_shapes.append(shape)
            self.select_shape(shape)
            shape.translate(dpos=(5, 5))
        return shapes

    def delete_shapes(self):
        if self.delete_selected_point():
            return True
        if not self.current_shape and not self.selection_shape \
                and self.delete_selected_shapes():
            return True
        return False

    def select_shape_with_touch(self, touch, deselect=True):
        pos = int(touch.x), int(touch.y)
        if deselect:
            for s in reversed(self.selected_shapes):
                if pos in s.inside_points:
                    self.deselect_shape(s)
                    return True

        for s in reversed(self.shapes):
            if pos in s.inside_points:
                if not self.add_selection and not self._ctrl_down:
                    self.clear_selected_shapes()
                self.select_shape(s)
                return True
        return False

    def collide_shape(self, x, y, selected=False):
        pos = int(x), int(y)
        for s in reversed(self.selected_shapes if selected else self.shapes):
            if pos in s.inside_points:
                return s
        return None

    def get_closest_shape_point(self, x, y):
        shapes = self.selected_shapes or self.shapes
        if not shapes:
            return None

        dists = [(s, s.closest_point(x, y)) for s in reversed(shapes)]
        shape, (p, dist) = min(dists, key=lambda x: x[1][1])
        if dist <= self.min_touch_dist:
            return shape, p
        return None

    def on_touch_down(self, touch):
        ud = touch.ud
        ud['paint_touch'] = None  # stores the point the touch fell near
        ud['paint_drag'] = None
        ud['paint_long'] = None
        ud['paint_up'] = False
        ud['paint_used'] = False

        if super(PaintCanvas, self).on_touch_down(touch):
            return True
        if not self.collide_point(touch.x, touch.y):
            return super(PaintCanvas, self).on_touch_down(touch)
        touch.grab(self)

        self._long_touch_trigger = Clock.schedule_once(
            partial(self.do_long_touch, touch, touch.x, touch.y),
            self.long_touch_delay)
        return False

    def do_long_touch(self, touch, x, y, *largs):
        self._long_touch_trigger = None
        ud = touch.ud

        # in select mode selected_point_shape can only be selection_shape
        # or None
        shape = self.selection_shape or self.current_shape \
            or self.selected_point_shape

        # if there's a shape you can only interact with it
        res = False
        if shape:
            p, dist = shape.closest_point(touch.x, touch.y)
            if dist <= self.min_touch_dist:
                res = self.clear_selected_point_shape(exclude_point=(shape, p))
                if shape.select_point(p):
                    self.selected_point_shape = shape
                    ud['paint_touch'] = shape, p
                    res = True
            else:
                res = self.clear_selected_point_shape()
            if res:
                ud['paint_long'] = True
        elif self.select:  # in select mode select shape
            if self.select_shape_with_touch(touch):
                ud['paint_long'] = True
        else:  # select any point close enough
            val = self.get_closest_shape_point(touch.x, touch.y)
            res = self.clear_selected_point_shape()
            if val:
                if val[0].select_point(val[1]):
                    res = True
                    self.selected_point_shape = val[0]
                    ud['paint_touch'] = val
            if res or self.select_shape_with_touch(touch):
                ud['paint_long'] = True

        if ud['paint_long'] is None:
            ud['paint_long'] = False
        elif ud['paint_long']:
            ud['paint_used'] = True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            # for move, only use normal touch, not touch outside range
            return

        ud = touch.ud
        if 'paint_used' not in ud:
            return super(PaintCanvas, self).on_touch_up(touch)

        if self._long_touch_trigger:
            self._long_touch_trigger.cancel()
            self._long_touch_trigger = None

        if ud['paint_drag'] is False:
            if ud['paint_used']:
                return True
            return super(PaintCanvas, self).on_touch_move(touch)

        if not self.collide_point(touch.x, touch.y):
            return ud['paint_used'] or \
                super(PaintCanvas, self).on_touch_move(touch)

        draw_shape = self.selection_shape or self.current_shape

        # nothing active, then in freeform add new shape
        if ud['paint_drag'] is None and not draw_shape \
                and not ud['paint_long'] and (not self.locked or self.select) \
                and self.draw_mode == 'freeform':
            self.clear_selected_point_shape()
            if not self.select:
                self.clear_selected_shapes()

            if self.select:
                shape = self.selection_shape = _cls_map['freeform'](
                    paint_widget=self, line_color=self.line_color,
                    line_color_edit=self.line_color_selector,
                    selection_color=self.selection_color)
            else:
                shape = self.current_shape = _cls_map['freeform'](
                    paint_widget=self, line_color=self.line_color,
                    line_color_edit=self.line_color_edit,
                    selection_color=self.selection_color)
                self.shapes.append(shape)
            shape.add_point(pos=touch.opos, source='move')
            shape.add_point(touch, source='move')

            ud['paint_drag'] = ud['paint_used'] = True
            return True

        if self.draw_mode == 'freeform' and draw_shape:
            assert ud['paint_drag'] and ud['paint_used']
            draw_shape.add_point(touch, source='move')
            return True

        shape = p = None
        if ud['paint_touch']:
            assert ud['paint_used']
            shape, p = ud['paint_touch']
        elif ud['paint_drag'] is None:
            if draw_shape:
                p, dist = draw_shape.closest_point(touch.ox, touch.oy)
                if dist <= self.min_touch_dist:
                    self.clear_selected_point_shape(
                        exclude_point=(draw_shape, p))
                    ud['paint_touch'] = draw_shape, p
                    shape = draw_shape
            elif not self.locked and not self.select:
                val = self.get_closest_shape_point(touch.ox, touch.oy)
                if val:
                    ud['paint_touch'] = shape, p = val
                    self.clear_selected_point_shape(exclude_point=(shape, p))

        if shape:
            shape.move_point(touch, p)
        elif not self.locked:
            opos = int(touch.ox), int(touch.oy)
            if (ud['paint_drag'] is None and
                    not self.select_shape_with_touch(touch, deselect=False) and
                    self.selected_shapes and
                    not any((opos in s.inside_points
                             for s in self.selected_shapes))):
                ud['paint_drag'] = False
                return False
            for s in self.selected_shapes:
                s.translate(dpos=(touch.dx, touch.dy))
        else:
            ud['paint_drag'] = False
            return False

        if ud['paint_drag'] is None:
            ud['paint_used'] = ud['paint_drag'] = True
        return True

    def on_touch_up(self, touch):
        ud = touch.ud
        if touch.grab_current is self and ud['paint_up']:
            return False
        if 'paint_used' not in ud:
            if touch.grab_current is not self:
                return super(PaintCanvas, self).on_touch_up(touch)
            return False

        ud['paint_up'] = True  # so that we don't do double on_touch_up
        if self._long_touch_trigger:
            self._long_touch_trigger.cancel()
            self._long_touch_trigger = None

        draw_mode = self.draw_mode
        if draw_mode == 'freeform':
            self.finish_selection_shape(True)
            self.finish_current_shape()
            return True

        shape = self.current_shape or self.selection_shape
        if ud['paint_drag'] and ud['paint_touch'] is not None:
            shape, p = ud['paint_touch']
            shape.move_point_done(touch, p)

        if ud['paint_used']:
            return True
        if not self.collide_point(touch.x, touch.y):
            if touch.grab_current is not self:
                return super(PaintCanvas, self).on_touch_up(touch)
            return False

        select = self.select
        if touch.is_double_tap:
            return self.finish_selection_shape(True) or \
                self.finish_current_shape()

        if self.clear_selected_point_shape():
            return True
        if shape:
            if not select:
                if self.selected_shapes:
                    s = self.collide_shape(touch.x, touch.y, selected=True)
                    if not s and self.clear_selected_shapes():
                        return True
                    if s and self.deselect_shape(s):
                        return True

            return shape.add_point(touch, source='up')
        elif draw_mode != 'none':
            if not select:
                if self.selected_shapes:
                    s = self.collide_shape(touch.x, touch.y, selected=True)
                    if not s and self.clear_selected_shapes():
                        return True
                    if s and self.deselect_shape(s):
                        return True

            shape = _cls_map[draw_mode](
                paint_widget=self, line_color=self.line_color,
                line_color_edit=self.line_color_selector if select
                else self.line_color_edit,
                selection_color=self.selection_color)

            if select:
                self.selection_shape = shape
            else:
                self.current_shape = shape
                self.shapes.append(shape)

            shape.add_point(touch, source='up')
            return True

        if (select or draw_mode == 'none') and \
                self.select_shape_with_touch(touch):
            return True

        if self.clear_selected_shapes():
            return True
        if touch.grab_current is not self:
            return super(PaintCanvas, self).on_touch_up(touch)
        return False

    def keyboard_on_key_down(self, window, keycode, text, modifiers):
        if keycode[1] in ('lctrl', 'ctrl', 'rctrl'):
            self._ctrl_down.add(keycode[1])
        return super(PaintCanvas, self).keyboard_on_key_down(
            window, keycode, text, modifiers)

    def keyboard_on_key_up(self, window, keycode):
        if keycode[1] in ('lctrl', 'ctrl', 'rctrl'):
            self._ctrl_down.remove(keycode[1])
        if keycode[1] == 'escape':
            if self.clear_selected_point_shape() or \
                    self.finish_current_shape() or \
                    self.finish_selection_shape() or \
                    self.clear_selected_shapes():
                return True
        elif keycode[1] == 'delete':
            if self.delete_shapes():
                return True
        elif keycode[1] == 'a' and self._ctrl_down:
            for shape in self.shapes:
                self.select_shape(shape)
            return True
        elif keycode[1] == 'd' and self._ctrl_down:
            if self.duplicate_selected_shapes():
                return True

        return super(PaintCanvas, self).keyboard_on_key_up(
            window, keycode)


class PaintShape(EventDispatcher):

    finished = False

    selected = False

    is_valid = False

    paint_widget = None

    line_width = 1

    line_color = 0, 1, 0, 1

    line_color_edit = 1, 0, 0, 1

    selection_color = 1, 1, 1, .5

    graphics_name = ''

    graphics_select_name = ''

    graphics_point_select_name = ''

    selected_point = None

    dragging = False

    _inside_points = None

    selected_point = None

    def __init__(
            self, paint_widget, line_color=(0, 1, 0, 1),
            line_color_edit=(0, 1, 0, 1), selection_color=(1, 1, 1, .5),
            line_width=1, **kwargs):
        super(PaintShape, self).__init__(**kwargs)
        self.paint_widget = paint_widget
        self.line_color = line_color
        self.line_color_edit = line_color_edit
        self.selection_color = selection_color
        self.line_width = line_width
        self.graphics_name = '{}-{}'.format(self.__class__.__name__, id(self))
        self.graphics_select_name = '{}-select'.format(self.graphics_name)
        self.graphics_point_select_name = '{}-point'.format(self.graphics_name)

    def _add_shape(self):
        pass

    def add_point(self, touch=None, pos=None, source='down'):
        return False

    def move_point(self, touch, point):
        return False

    def move_point_done(self, touch, point):
        return False

    def remove_paint_widget(self):
        if not self.paint_widget:
            return
        self.paint_widget.canvas.remove_group(self.graphics_name)
        self.paint_widget.canvas.remove_group(self.graphics_select_name)
        self.paint_widget.canvas.remove_group(self.graphics_point_select_name)

    def finish(self):
        if self.finished:
            return False
        self.finished = True
        return True

    def clean(self):
        '''Removes everything, except its selection state.
        '''
        self.clear_point_selection()

    def select(self):
        if self.selected:
            return False
        self.selected = True
        return True

    def deselect(self):
        if not self.selected:
            return False
        self.selected = False
        self.paint_widget.canvas.remove_group(self.graphics_select_name)
        return True

    def closest_point(self, x, y):
        pass

    def select_point(self, point):
        return False

    def delete_selected_point(self):
        return False

    def clear_point_selection(self, exclude_point=None):
        return False

    def translate(self, dpos):
        return False

    def collide_shape(self, shape, test_all=True):
        if test_all:
            points = shape.inside_points
            return all((p in points for p in self.inside_points))

        points_a, points_b = self.inside_points, shape.inside_points
        if len(points_a) > len(points_b):
            points_a, points_b = points_b, points_a

        for p in points_a:
            if p in points_b:
                return True
        return False

    def _get_collider(self, size):
        pass

    @property
    def inside_points(self):
        if not self.is_valid:
            return set()
        if self._inside_points is not None:
            return self._inside_points

        collider = self._get_collider(self.paint_widget.size)
        points = self._inside_points = set(collider.get_inside_points())
        return points

    def _copy(self, cls, cls_args=[], cls_attrs=[]):
        kw = {attr: copy(getattr(self, attr)) for attr in cls_args +
              ['paint_widget', 'line_color', 'line_color_edit',
               'selection_color', 'line_width']}
        obj = cls(**kw)
        for attr in cls_attrs + ['is_valid']:
            setattr(obj, attr, copy(getattr(self, attr)))
        return obj


class PaintCircle(PaintShape):

    center = None

    perim_ellipse_inst = None

    center_point_inst = None

    selection_ellipse_inst = None

    ellipse_color_inst = None

    radius = NumericProperty(dp(10))

    def __init__(self, **kwargs):
        super(PaintCircle, self).__init__(**kwargs)
        self.fbind('radius', self._update_radius)

    def _add_shape(self):
        x, y = self.center
        r = self.radius
        with self.paint_widget.canvas:
            self.ellipse_color_inst = Color(
                *self.line_color_edit, group=self.graphics_name)
            self.perim_ellipse_inst = Line(
                circle=(x, y, r), width=self.line_width,
                group=self.graphics_name)

    def add_point(self, touch=None, pos=None, source='down'):
        if self.perim_ellipse_inst is None:
            self.center = pos or (touch.x, touch.y)
            self._add_shape()
            self._inside_points = None
            self.is_valid = True
            return True
        return False

    def move_point(self, touch, point):
        if not self.dragging:
            if point == 'center':
                with self.paint_widget.canvas:
                    Color(*self.ellipse_color_inst.rgba,
                          group=self.graphics_point_select_name)
                    self.center_point_inst = Point(
                        points=self.center[:],
                        group=self.graphics_point_select_name,
                        pointsize=max(1, min(self.radius / 2., 2)))
            self.dragging = True

        if point == 'center':
            self.translate(pos=(touch.x, touch.y))
        else:
            x, y = self.center
            ndist = eucledian_dist(x, y, touch.x, touch.y)
            odist = eucledian_dist(x, y, touch.x - touch.dx,
                                   touch.y - touch.dy)
            self.radius = max(1, self.radius + ndist - odist)
        self._inside_points = None
        return True

    def move_point_done(self, touch, point):
        if self.dragging:
            self.paint_widget.canvas.remove_group(
                self.graphics_point_select_name)
            self.center_point_inst = None
            self.dragging = False
            return True
        return False

    def finish(self):
        if super(PaintCircle, self).finish():
            self.ellipse_color_inst.rgba = self.line_color
            return True
        return False

    def select(self):
        if not super(PaintCircle, self).select():
            return False
        x, y = self.center
        r = self.radius
        with self.paint_widget.canvas:
            Color(*self.selection_color, group=self.graphics_select_name)
            self.selection_ellipse_inst = Ellipse(
                size=(r * 2., r * 2.), pos=(x - r, y - r),
                group=self.graphics_select_name)
        self.perim_ellipse_inst.width = 2 * self.line_width
        return True

    def deselect(self):
        if super(PaintCircle, self).deselect():
            self.selection_ellipse_inst = None
            self.perim_ellipse_inst.width = self.line_width
            return True
        return False

    def closest_point(self, x, y):
        d = eucledian_dist(x, y, *self.center)
        r = self.radius
        if d <= r / 2.:
            return 'center', d

        if d <= r:
            return 'outside', r - d
        return 'outside', d - r

    def translate(self, dpos=None, pos=None):
        if dpos is not None:
            x, y = self.center
            dx, dy = dpos
            x += dx
            y += dy
        elif pos is not None:
            x, y = pos
        else:
            x, y = self.center

        r = self.radius
        self.center = x, y
        if self.perim_ellipse_inst:
            self.perim_ellipse_inst.circle = x, y, r
        if self.selection_ellipse_inst:
            self.selection_ellipse_inst.pos = x - r, y - r
        if self.center_point_inst:
            self.center_point_inst.points = x, y

        self._inside_points = None
        return True

    def _update_radius(self, *largs):
        x, y = self.center
        r = self.radius
        if self.perim_ellipse_inst:
            self.perim_ellipse_inst.circle = x, y, r
        if self.selection_ellipse_inst:
            self.selection_ellipse_inst.size = r * 2., r * 2.
            self.selection_ellipse_inst.pos = x - r, y - r

        self._inside_points = None

    def _get_collider(self, size):
        x, y = self.center
        r = self.radius
        return CollideEllipse(x=x, y=y, rx=r, ry=r)

    def __deepcopy__(self, memo):
        obj = self._copy(PaintCircle, cls_attrs=['center', 'radius'])
        obj._add_shape()
        obj.finish()
        return obj


class PaintEllipse(PaintShape):

    center = None

    angle = NumericProperty(0)

    rx = NumericProperty(dp(10))

    ry = NumericProperty(dp(10))

    _second_point = None

    perim_ellipse_inst = None

    perim_rotate = None

    center_point_inst = None

    selection_ellipse_inst = None

    selection_rotate = None

    ellipse_color_inst = None

    def __init__(self, **kwargs):
        super(PaintEllipse, self).__init__(**kwargs)
        self.fbind('rx', self._update_radius)
        self.fbind('ry', self._update_radius)
        self.fbind('angle', self._update_radius)

    def _add_shape(self):
        x, y = self.center
        rx, ry = self.rx, self.ry
        with self.paint_widget.canvas:
            self.ellipse_color_inst = Color(
                *self.line_color_edit, group=self.graphics_name)
            PushMatrix(group=self.graphics_name)
            self.perim_rotate = Rotate(angle=self.angle, origin=(x, y),
                                       group=self.graphics_name)
            self.perim_ellipse_inst = Line(
                ellipse=(x - rx, y - ry, 2 * rx, 2 * ry),
                width=self.line_width, group=self.graphics_name)
            PopMatrix(group=self.graphics_name)

    def add_point(self, touch=None, pos=None, source='down'):
        if self.perim_ellipse_inst is None:
            self.center = pos or (touch.x, touch.y)
            self._add_shape()
            self._inside_points = None
            self.is_valid = True
            return True
        return False

    def move_point(self, touch, point):
        if not self.dragging:
            if point == 'center':
                with self.paint_widget.canvas:
                    Color(*self.ellipse_color_inst.rgba,
                          group=self.graphics_point_select_name)
                    self.center_point_inst = Point(
                        points=self.center[:],
                        group=self.graphics_point_select_name,
                        pointsize=max(1, min(min(self.rx, self.ry) / 2., 2)))
            self.dragging = True

        self._inside_points = None
        if point == 'center':
            self.translate(pos=(touch.x, touch.y))
            return True

        if not self._second_point:
            cx, cy = self.center
            self.angle = atan2(
                touch.y - touch.dy - cy, touch.x - touch.dx - cx) * 180. / pi
            self._second_point = True

        x = touch.dx
        y = touch.dy
        if self.angle:
            angle = -self.angle * pi / 180.
            x, y = (x * cos(angle) - y * sin(angle),
                    x * sin(angle) + y * cos(angle))
        self.rx = max(1, self.rx + x)
        self.ry = max(1, self.ry + y)
        return True

    def move_point_done(self, touch, point):
        if self.dragging:
            self.paint_widget.canvas.remove_group(
                self.graphics_point_select_name)
            self.center_point_inst = None
            self.dragging = False
            return True
        return False

    def finish(self):
        if super(PaintEllipse, self).finish():
            self.ellipse_color_inst.rgba = self.line_color
            return True
        return False

    def select(self):
        if not super(PaintEllipse, self).select():
            return False
        x, y = self.center
        rx, ry = self.rx, self.ry
        with self.paint_widget.canvas:
            Color(*self.selection_color, group=self.graphics_select_name)
            PushMatrix(group=self.graphics_select_name)
            self.selection_rotate = Rotate(angle=self.angle, origin=(x, y),
                                           group=self.graphics_select_name)

            self.selection_ellipse_inst = Ellipse(
                size=(rx * 2., ry * 2.), pos=(x - rx, y - ry),
                group=self.graphics_select_name)
            PopMatrix(group=self.graphics_select_name)
        self.perim_ellipse_inst.width = 2 * self.line_width
        return True

    def deselect(self):
        if super(PaintEllipse, self).deselect():
            self.selection_ellipse_inst = None
            self.selection_rotate = None
            self.perim_ellipse_inst.width = self.line_width
            return True
        return False

    def closest_point(self, x, y):
        cx, cy = self.center
        rx, ry = self.rx, self.ry
        collider = CollideEllipse(x=cx, y=cy, rx=rx, ry=ry, angle=self.angle)
        dist = collider.estimate_distance(x, y)
        center_dist = eucledian_dist(cx, cy, x, y)

        if not collider.collide_point(x, y) or dist < center_dist:
            return 'outside', dist
        return 'center', center_dist

    def translate(self, dpos=None, pos=None):
        if dpos is not None:
            x, y = self.center
            dx, dy = dpos
            x += dx
            y += dy
        elif pos is not None:
            x, y = pos
        else:
            x, y = self.center

        rx, ry = self.rx, self.ry
        self.center = x, y
        if self.perim_ellipse_inst:
            self.perim_ellipse_inst.ellipse = x - rx, y - ry, 2 * rx, 2 * ry
            self.perim_rotate.origin = x, y
        if self.selection_ellipse_inst:
            self.selection_ellipse_inst.pos = x - rx, y - ry
            self.selection_rotate.origin = x, y
        if self.center_point_inst:
            self.center_point_inst.points = x, y

        self._inside_points = None
        return True

    def _update_radius(self, *largs):
        x, y = self.center
        rx, ry = self.rx, self.ry
        if self.perim_ellipse_inst:
            self.perim_ellipse_inst.ellipse = x - rx, y - ry, 2 * rx, 2 * ry
            self.perim_rotate.angle = self.angle
            self.perim_rotate.origin = x, y
        if self.selection_ellipse_inst:
            self.selection_ellipse_inst.size = rx * 2., ry * 2.
            self.selection_ellipse_inst.pos = x - rx, y - ry
            self.selection_rotate.angle = self.angle
            self.selection_rotate.origin = x, y

        self._inside_points = None

    def _get_collider(self, size):
        x, y = self.center
        rx, ry = self.rx, self.ry
        return CollideEllipse(x=x, y=y, rx=rx, ry=ry, angle=self.angle)

    def __deepcopy__(self, memo):
        obj = self._copy(
            PaintEllipse,
            cls_attrs=['center', 'angle', 'rx', 'ry', '_second_point'])
        obj._add_shape()
        obj.finish()
        return obj


class PaintPolygon(PaintShape):

    perim_inst = None

    perim_point_inst = None

    selection_inst = None

    selection_point_inst = None

    perim_color_inst = None

    line_type_name = 'points'

    def _locate_point(self, i, x, y):
        points = self.perim_inst.points
        if len(points) > i:
            return i

        try:
            i = 0
            while True:
                i = points.index(x, i)
                if i != len(points) - 1 and points[i + 1] == y:
                    return i
                i += 1
        except ValueError:
            return 0

    def _get_points(self):
        return self.perim_inst and self.perim_inst.points

    def _update_points(self, points):
        self.perim_inst.flag_update()

    def _get_perim_points(self, points):
        return Point(points=points, group=self.graphics_name, pointsize=2)

    def _add_shape(self, new_points):
        with self.paint_widget.canvas:
            self.perim_color_inst = Color(
                *self.line_color_edit, group=self.graphics_name)

            self.perim_inst = Line(
                width=self.line_width, close=False,
                group=self.graphics_name, **{self.line_type_name: []})
            points = self._get_points()
            points += new_points
            self._update_points(points)

            self.perim_point_inst = self._get_perim_points(new_points)

    def add_point(self, touch=None, pos=None, source='down'):
        self._inside_points = None
        line = self.perim_inst
        x, y = pos or (touch.x, touch.y)
        if line is None:
            self._add_shape([x, y])
            return True

        points = self._get_points()
        if not points or int(points[-2]) != (x) \
                or int(points[-1]) != (y):
            points += [x, y]
            self._update_points(points)
            self.perim_point_inst.points += [x, y]
            self.perim_point_inst.flag_update()
            if self.selection_inst is not None:
                self._update_mesh(points)
            if not self.is_valid and len(points) >= 6:
                self.is_valid = True
            return True
        return False

    def move_point(self, touch, point):
        points = self._get_points()
        perim_points_inst = self.perim_point_inst
        perim_points = perim_points_inst.points
        if not points:
            return False

        self._inside_points = None
        i = self._locate_point(*point)

        if not self.dragging:
            with self.paint_widget.canvas:
                assert self.selected or not self.selection_point_inst
            self.dragging = True

        points[i] = touch.x
        points[i + 1] = touch.y
        perim_points[i] = touch.x
        perim_points[i + 1] = touch.y

        self._update_points(points)
        perim_points_inst.flag_update()

        if self.selection_inst is not None:
            self._update_mesh(points)
        return True

    def move_point_done(self, touch, point):
        if self.dragging:
            self.dragging = False
            return True
        return False

    def finish(self):
        if super(PaintPolygon, self).finish():
            self.perim_color_inst.rgba = self.line_color
            self.perim_inst.close = True
            return True
        return False

    def _update_mesh(self, points):
        self.paint_widget.canvas.remove_group(
            self.graphics_select_name)
        meshes = []
        tess = Tesselator()

        tess.add_contour(points)
        if tess.tesselate():
            with self.paint_widget.canvas:
                Color(*self.selection_color, group=self.graphics_select_name)
                for vertices, indices in tess.meshes:
                    m = Mesh(
                        vertices=vertices, indices=indices,
                        mode='triangle_fan', group=self.graphics_select_name)
                    meshes.append(m)

        self.selection_inst = meshes

    def select(self):
        if not super(PaintPolygon, self).select():
            return False
        points = self._get_points()
        if not points or not len(points) // 2:
            return True

        self._update_mesh(points)
        self.perim_inst.width = 2 * self.line_width
        return True

    def deselect(self):
        if super(PaintPolygon, self).deselect():
            self.selection_inst = None
            self.perim_inst.width = self.line_width
            return True
        return False

    def closest_point(self, x, y):
        points = self._get_points()
        if not points:
            return ((None, None, None), 1e12)
        i = min(range(len(points) // 2),
                key=lambda i: eucledian_dist(x, y, points[2 * i],
                                             points[2 * i + 1]))
        i *= 2
        px, py = points[i], points[i + 1]
        return ((i, px, py), eucledian_dist(x, y, px, py))

    def select_point(self, point):
        i, x, y = point
        points = self._get_points()

        if i is None or not points:
            return False
        i = self._locate_point(i, x, y)

        if self.selected_point:
            self.clear_point_selection()
        self.selected_point = point

        with self.paint_widget.canvas:
            assert not self.selection_point_inst
            Color(*self.perim_color_inst.rgba,
                  group=self.graphics_point_select_name)
            self.selection_point_inst = Point(
                points=[points[i], points[i + 1]],
                group=self.graphics_point_select_name,
                pointsize=3)
        return True

    def delete_selected_point(self):
        point = self.selected_point
        if point is None:
            return False

        i, x, y = point
        points = self._get_points()
        if i is None or not points:
            return False
        i = self._locate_point(i, x, y)
        self._inside_points = None

        self.clear_point_selection()
        if len(points) <= 6:
            return True

        del points[i:i + 2]
        del self.perim_point_inst.points[i:i + 2]
        self._update_points(points)
        self.perim_point_inst.flag_update()

        if self.selection_inst is not None:
            self._update_mesh(points)
        return True

    def clear_point_selection(self, exclude_point=None):
        point = self.selected_point
        if point is None:
            return False

        if point[0] is None or exclude_point == point:
            return False
        self.paint_widget.canvas.remove_group(
            self.graphics_point_select_name)
        self.selection_point_inst = None
        return True

    def translate(self, dpos):
        self._inside_points = None
        dx, dy = dpos
        points = self._get_points()
        if not points:
            return False

        perim_points = self.perim_point_inst.points
        for i in range(len(points) // 2):
            i *= 2
            points[i] += dx
            points[i + 1] += dy
            perim_points[i] += dx
            perim_points[i + 1] += dy

        self._update_points(points)
        self.perim_point_inst.flag_update()

        if self.selection_point_inst:
            x, y = self.selection_point_inst.points
            self.selection_point_inst.points = [x + dx, y + dy]

        if self.selection_inst:
            for mesh in self.selection_inst:
                verts = mesh.vertices
                for i in range(len(verts) // 4):
                    i *= 4
                    verts[i] += dx
                    verts[i + 1] += dy
                mesh.vertices = verts

    def _get_collider(self, size):
        return Collide2DPoly(points=self.perim_inst.points, cache=True)

    def __deepcopy__(self, memo):
        obj = self._copy(self.__class__)
        obj._add_shape(self._get_points())
        obj.finish()
        return obj


class PaintBezier(PaintPolygon):

    points = None

    line_type_name = 'bezier'

    def __init__(self, **kwargs):
        super(PaintBezier, self).__init__(**kwargs)
        self.points = []

    def _get_points(self):
        return self.points

    def _update_points(self, points):
        self.perim_inst.bezier = points + points[:2]

    def _update_mesh(self, points):
        points = CollideBezier.convert_to_poly(points + points[:2])
        super(PaintBezier, self)._update_mesh(points)

    def _get_collider(self, size):
        return CollideBezier(points=self.points + self.points[:2], cache=True)

_cls_map = {
    'circle': PaintCircle, 'ellipse': PaintEllipse,
    'polygon': PaintPolygon, 'freeform': PaintPolygon,
    'bezier': PaintBezier
}
