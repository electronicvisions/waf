#!/usr/bin/env python
# encoding: utf-8
"""
cross_gxx cross compiler detection.
"""

import os, sys
from waflib import Configure, Options, Utils
from waflib.Tools import ccroot, gxx
from waflib.Configure import conf
from waflib.extras import cross_ar, visionflags

@conf
def find_cross_gxx(conf):
	"""
	Find the cross compiler and if present, try to detect its version number
	"""
	cxx = conf.find_program('%s-g++' % conf.env.CROSS_PLATFORM, var='CXX')
	conf.get_cc_version(cxx, gcc=True)
	conf.env.CXX_NAME = '%s-gxx' % conf.env.CROSS_PLATFORM

@conf
def cross_gxx_common_flags(conf):
	# Update some flags to be compatible with the separate linker, instead of
	# using the cross compiler as the linker driver
	conf.env['SONAME_ST']           = '-h,%s'
	conf.env['SHLIB_MARKER']        = '-Bdynamic'
	conf.env['STLIB_MARKER']        = '-Bstatic'
	conf.env['LINKFLAGS_cstlib']    = '-Bstatic'

def options(opt):
	opt.load('visionflags')

def configure(conf):
	"""
	Configuration for cross_gcc
	"""
	conf.find_cross_gxx()
	conf.find_cross_ar()
	conf.gxx_common_flags()
	conf.cross_gxx_common_flags()
	# ECM: cf. gcc.py
	conf.load("visionflags")
	conf.cxx_load_tools()
