#!/usr/bin/env python
# encoding: utf-8
# Stian Selnes 2008
# Thomas Nagy 2009-2018 (ita)

"""
Detects the Intel C compiler
"""

from waflib import Utils
from waflib.Tools import ccroot, ar, gcc
from waflib.Configure import conf
from waflib.Tools import msvc

@conf
def find_icc(conf):
	"""
	Finds the program icc and execute it to ensure it really is icc
	"""
	if Utils.is_win32:
		cc = conf.find_program(['icx-cc', 'icc', 'ICL'], var='CC')
	else:
		cc = conf.find_program(['icx', 'icc', 'ICL'], var='CC')
	conf.get_cc_version(cc, icc=True)
	conf.env.CC_NAME = 'icc'

def configure(conf):
	conf.find_icc()
	if conf.env.INTEL_CLANG_COMPILER and Utils.is_win32:
		# need the linker from msvc
		cc = conf.env.CC
		cxx = conf.env.CXX
		cxx_name = conf.env.CXX_NAME
		conf.find_msvc()
		conf.env.CC = cc
		conf.env.CXX = cxx
		conf.env.CC_NAME = 'icc'
		conf.env.CXX_NAME = cxx_name

		conf.msvc_common_flags()

		conf.env.CFLAGS = []
		conf.cc_load_tools()
		conf.cc_add_flags()
		conf.link_add_flags()

		conf.visual_studio_add_flags()
		conf.env.LINK_CC = conf.env.AR
		conf.env.CC_TGT_F = ['/c', '/o']
	else:
		conf.find_ar()
		conf.gcc_common_flags()
		conf.gcc_modifier_platform()
		conf.cc_load_tools()
		conf.cc_add_flags()
		conf.link_add_flags()
