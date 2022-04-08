#!/usr/bin/env python3

from os import path

from setuptools import find_packages, setup

here = path.abspath(path.dirname(__file__))


def get_version():
    with open(path.join(here, 'reprise', '__init__.py')) as source:
        for line in source:
            if line.startswith('__version__'):
                return line.strip().split(' = ')[-1].strip("'")

    raise RuntimeError('Cannot determine package version from package source')


def get_long_description():
    try:
        return open(path.join(here, 'README.md')).read()
    except:
        return None


setup(
    name='reprise',
    version=get_version(),
    description='Manage SQL queries as a Python API',
    long_description=get_long_description(),
    long_description_content_type='text/markdown',
    author='Dmitry Marakasov',
    author_email='amdmi3@amdmi3.ru',
    url='https://github.com/AMDmi3/reprise',
    license='GPLv3+',
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: POSIX :: BSD :: FreeBSD',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.10',
        'Topic :: Software Development :: Build Tools',
        'Topic :: Software Development :: Testing',
        'Topic :: System :: Archiving :: Packaging',
    ],
    python_requires='>=3.10',
    install_requires=['jsonslicer>=0.1.7'],
    packages=find_packages(include=['reprise*']),
    entry_points={
        'console_scripts': ['reprise=reprise.cli:main']
    }
)
