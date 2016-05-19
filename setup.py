from setuptools import setup, find_packages
import cplcom

with open('README.rst') as fh:
    long_description = fh.read()

setup(
    name='CPLCom',
    version=cplcom.__version__,
    author='Matthew Einhorn',
    author_email='moiein2000@gmail.com',
    license='MIT',
    description=(
        'Project for common kivy and moa tools used in CPL.'),
    url='http://matham.github.io/cplcom/',
    long_description=long_description,
    classifiers=['License :: OSI Approved :: MIT License',
                 'Topic :: Scientific/Engineering',
                 'Topic :: System :: Hardware',
                 'Programming Language :: Python :: 2.7',
                 'Programming Language :: Python :: 3.3',
                 'Programming Language :: Python :: 3.4',
                 'Programming Language :: Python :: 3.5',
                 'Operating System :: Microsoft :: Windows',
                 'Intended Audience :: Developers'],
    packages=find_packages(),
    package_data={'cplcom': ['../media/*', 'graphics.kv', 'cplcom/data/*']},
    install_requires=['moa'],
    setup_requires=['moa']
)
