#!/usr/bin/env python

from distutils.core import setup

setup(
    name='ringbuffer',
    version='0.4',
    description='Ring buffer that allows for high-throughput data transfer'
    'between multiproccessing Python processes.',
    url='https://github.com/ctrl-labs/cringbuffer',
    py_modules=['ringbuffer'])
