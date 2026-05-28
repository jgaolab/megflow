# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

curdir = os.path.dirname(__file__)
# sys.path.insert(0,os.path.abspath(os.path.join(curdir, "..", "..", "opmqc")))
sys.path.insert(0,os.path.abspath(os.path.join("..", "..")))


# def run_apidoc(app):
#     """Generage API documentation"""
#     import better_apidoc
#     better_apidoc.APP = app
#     try:
#         better_apidoc.main([
#             'better-apidoc',
#             '-t',
#             os.path.join('.', 'source', '_templates'),
#             '--force',
#             '--no-toc',
#             '--separate',
#             '-o',
#             os.path.join('.', 'source', 'apis'),
#             os.path.join('..', 'opmqc'),
#         ])
#     except Exception as e:
#         print(e)


# -- Project information -----------------------------------------------------

project = 'megprep'
copyright = '2025, LiaoPan'
author = 'LiaoPan'

# The full version, including alpha/beta/rc tags
release = '0.0.1'


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx_autodoc_typehints',
    'sphinx.ext.mathjax',
    'sphinx.ext.viewcode',
    'sphinx_design',
    'sphinx.ext.napoleon',
    'sphinx_copybutton',
    'sphinx_click',
]

# myst_enable_extensions = [
#     "colon_fence"
# ]

autosummary_generate = True

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "build"]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3.8", None),
    "sphinx": ("https://www.sphinx-doc.org/en/master", None),
    "pst": ("https://pydata-sphinx-theme.readthedocs.io/en/latest/", None),
}
nitpick_ignore = [
    ("py:class", "docutils.nodes.document"),
    ("py:class", "docutils.parsers.rst.directives.body.Sidebar"),
]

suppress_warnings = ["myst.domains", "ref.ref"]

numfig = True

myst_enable_extensions = [
    "dollarmath",
    "amsmath",
    "deflist",
    # "html_admonition",
    # "html_image",
    "colon_fence",
    # "smartquotes",
    # "replacements",
    # "linkify",
    # "substitution",
]
# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
# html_theme = 'alabaster'
# html_theme = 'sphinx_rtd_theme'
html_theme = 'sphinx_book_theme'
html_logo = '_static/logo.png'
html_favicon = '_static/favicon.png'
html_title = 'MEGPrep Documentation'

html_theme_options = {
    'show_toc_level': 2,
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

html_css_files = [
    'css/custom.css',
]
# -----------------------------------------------------------------------------
# def setup(app):
#     app.connect('builder-inited', run_apidoc)