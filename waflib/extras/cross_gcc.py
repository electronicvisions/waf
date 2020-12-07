#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2006-2010 (ita)
# Ralf Habacker, 2006 (rh)
# Yinon Ehrlich, 2009

"""
cross_gcc cross compiler detection.
"""

import os, sys
from waflib import Configure, Options, Utils
from waflib.Tools import ccroot, gcc
from waflib.Configure import conf
from waflib.extras import cross_ar, visionflags

@conf
def find_cross_gcc(conf):
	"""
	Find the cross compiler and if present, try to detect its version number
	"""
	# call twice (kw "value") to avoid usage of preset CC variable
	cc = conf.find_program('%s-gcc' % conf.env.CROSS_PLATFORM)
	cc = conf.find_program('%s-gcc' % conf.env.CROSS_PLATFORM, value=cc, var='CC')
	conf.get_cc_version(cc, gcc=True)
	conf.env.CC_NAME = '%s-gcc' % conf.env.CROSS_PLATFORM

@conf
def cross_gcc_common_flags(conf):
	# Update some flags to be compatible with the separate linker, instead of
	# using the cross compiler as the linker driver
	conf.env['SONAME_ST']           = '-h,%s'
	conf.env['SHLIB_MARKER']        = '-Bdynamic'
	conf.env['STLIB_MARKER']        = '-Bstatic'
	conf.env['LINKFLAGS_cstlib']    = '-Bstatic'

def options(opt):
	opt.load("visionflags")

def configure(conf):
	"""
	Configuration for cross_gcc
	"""
	conf.find_cross_gcc()
	conf.find_cross_ar()
	conf.gcc_common_flags()
	conf.cross_gcc_common_flags()
	# ECM: If CFLAGS/CCDEPS (or CXX) exist here, it has been provided by the
	# user. If we would load later, the env vars would have been already
	# touched by waf. We could have the idea to push the load into the c_config
	# file, but seems a bit too "intrusive"...
	conf.load("visionflags")
	conf.cc_load_tools()
