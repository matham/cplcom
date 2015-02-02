
__version__ = '0.1-dev'

from os.path import join, dirname

from kivy.resources import resource_add_path
from kivy.lang import Builder

resource_add_path(join(dirname(dirname(__file__)), 'media'))
Builder.load_file(join(dirname(__file__), 'graphics.kv'))
