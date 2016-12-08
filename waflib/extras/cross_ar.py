#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2006-2010 (ita)
# Ralf Habacker, 2006 (rh)

"""
The **cross_ar** program creates static libraries. This tool is almost always loaded
from others (C, C++, D, etc) for static library support.
"""

from waflib.Configure import conf

@conf
def find_cross_ar(conf):
	"""Configuration helper used by C/C++ tools to enable the support for static libraries"""
	conf.load('cross_ar')

def configure(conf):
	"""Find the ar program and set the default flags in ``conf.env.ARFLAGS``"""
	conf.find_program('%s-ar' % conf.env.CROSS_PLATFORM, var='AR')
	if not conf.env.ARFLAGS:
		conf.env.ARFLAGS = ['rcs']

