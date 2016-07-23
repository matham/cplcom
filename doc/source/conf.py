# -*- coding: utf-8 -*-

from sphinx.ext.autodoc import ClassDocumenter

import cplcom
from cplcom.config import create_doc_listener

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.todo',
    'sphinx.ext.coverage',
    'sphinx.ext.intersphinx'
]

html_sidebars = {
    '**': [
        'about.html',
        'navigation.html',
        'relations.html',
        'searchbox.html',
        'sourcelink.html'
    ]
}

html_theme_options = {
    'github_button': 'true',
    'github_banner': 'true',
    'github_user': 'matham',
    'github_repo': 'cplcom'
}

intersphinx_mapping = {
    'moa': ('https://matham.github.io/moa/', None),
    'pybarst': ('https://matham.github.io/pybarst/', None),
    'ffpyplayer': ('https://matham.github.io/ffpyplayer/', None)
}

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'CPLCom'

# The short X.Y version.
version = cplcom.__version__
# The full version, including alpha/beta/rc tags.
release = cplcom.__version__

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
html_theme = 'alabaster'

# Output file base name for HTML help builder.
htmlhelp_basename = 'CPLComdoc'

latex_elements = {}

latex_documents = [
  ('index', 'CPLCom.tex', u'CPLCom Documentation',
   u'Matthew Einhorn', 'manual'),
]

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [
    ('index', 'CPLCom', u'CPLCom Documentation',
     [u'Matthew Einhorn'], 1)
]

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
  ('index', 'CPLCom', u'CPLCom Documentation',
   u'Matthew Einhorn', 'CPLCom', 'One line description of project.',
   'Miscellaneous'),
]


class MyClassDocumenter(ClassDocumenter):

    def add_line(self, line, source, *lineno):
        line = line.replace('._ftdi', '')
        super(MyClassDocumenter, self).add_line(line, source, *lineno)


def setup(app):
    app.add_autodocumenter(MyClassDocumenter)
    create_doc_listener(app, cplcom)
