#!/usr/bin/env python

from setuptools import setup, find_packages
from get_git_version import get_git_version
import os, os.path

setup(name='ftldat',
      version=get_git_version(),
      description='CLI tool to pack and unpack FTL .dat files',
      author='Bas Westerbaan',
      author_email='bas@westerbaan.name',
      url='http://github.com/bwesterb/ftldat/',
      packages=['ftldat'],
      package_dir={'ftldat': 'src'},
      install_requires = [''],
      entry_points = {
          'console_scripts': [
              'ftldat = ftldat.main:main',
              ]
          }
      )

# vim: et:sta:bs=2:sw=4:
