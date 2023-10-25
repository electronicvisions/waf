#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy 2009-2018 (ita)

"""
Detects the Intel C++ compiler
"""

from waflib import Utils
from waflib.Tools import ccroot, ar, gxx
from waflib.Configure import conf
from waflib.Tools import msvc

@conf
def find_icpc(conf):
	"""
	Finds the program icpc, and execute it to ensure it really is icpc
	"""
	if Utils.is_win32:
		conf.find_program(['icx-cl'], var='ICXCL', mandatory=False)
		if conf.env.ICXCL:
			conf.env.INTEL_CLANG_COMPILER = True
			conf.env.CXX = conf.env.ICXCL

	if not conf.env.INTEL_CLANG_COMPILER:
		cc = conf.find_program(['icpx', 'icpc', 'ICL'], var='CXX')
		conf.get_cc_version(cc, icc=True)

	conf.env.CC_NAME = 'icc'

def configure(conf):
	conf.find_icpc()
	if conf.env.INTEL_CLANG_COMPILER and Utils.is_win32:
		conf.find_msvc()
		conf.find_program('MT', var='MT')
		conf.env.MTFLAGS = ['/nologo']
		conf.env.MSVC_MANIFEST = True

		conf.msvc_common_flags()

		conf.env.CXXFLAGS = []
		conf.cc_load_tools()
		conf.cc_add_flags()
		conf.link_add_flags()

		conf.visual_studio_add_flags()
		conf.env.CXX_TGT_F = ['/c', '/Fo']
		conf.env.CPPPATH_ST = '/I%s'
	else:
		conf.find_ar()
		conf.gxx_common_flags()
		conf.gxx_modifier_platform()
		conf.cc_load_tools()
		conf.cc_add_flags()
		conf.link_add_flags()
