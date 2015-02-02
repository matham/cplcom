from setuptools import setup, find_packages
import cplcom


setup(
    name='CPLCom',
    version=cplcom.__version__,
    packages=find_packages(),
    package_data={'cplcom': ['../media/*']},
    install_requires=['moa', 'kivy'],
    author='Matthew Einhorn',
    author_email='moiein2000@gmail.com',
    license='MIT',
    description=(
        'Project for common widgets used with Moa.')
    )
