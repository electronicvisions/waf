#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy 2009-2018 (ita)

"""
Detects the Intel C++ compiler
"""

from waflib.Tools import ccroot, ar, gxx
from waflib.Configure import conf

@conf
def find_icpc(conf):
	"""
	Finds the program icpc, and execute it to ensure it really is icpc
	"""
	cxx = conf.find_program(['icpx', 'icpc'], var='CXX')
	conf.get_cc_version(cxx, icc=True)
	conf.env.CXX_NAME = 'icc'

def configure(conf):
	conf.find_icpc()
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
		conf.env.LINK_CXX = conf.env.AR
		conf.env.CXX_TGT_F = ['/c', '/o']
	else:
		conf.find_ar()
		conf.gcc_common_flags()
		conf.gcc_modifier_platform()
		conf.cc_load_tools()
		conf.cc_add_flags()
		conf.link_add_flags()
