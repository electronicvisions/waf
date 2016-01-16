#! /usr/bin/env python
# encoding: utf-8
# DC 2008
# Thomas Nagy 2010 (ita)

import re
from waflib import Utils
from waflib.Tools import fc, fc_config, fc_scan, ar
from waflib.Configure import conf

@conf
def find_ifort(conf):
	fc = conf.find_program('ifort', var='FC')
	conf.get_ifort_version(fc)
	conf.env.FC_NAME = 'IFORT'

@conf
def ifort_modifier_cygwin(conf):
	raise NotImplementedError("Ifort on cygwin not yet implemented")

@conf
def ifort_modifier_win32(conf):
	v = conf.env
	v.FCSTLIB_MARKER = ''
	v.FCSHLIB_MARKER = ''

	v.FCLIB_ST = v.FCSTLIB_ST = '%s.lib'
	v.FCLIBPATH_ST = v.STLIBPATH_ST = '/LIBPATH:%s'
	v.FCINCPATH_ST = '/I%s'
	v.FCDEFINES_ST = '/D%s'

	v.fcprogram_PATTERN = v.fcprogram_test_PATTERN = '%s.exe'
	v.fcshlib_PATTERN = '%s.dll'
	v.fcstlib_PATTERN = v.implib_PATTERN = '%s.lib'

	v.FCLNK_TGT_F = '/o'
	v.FC_TGT_F = ['/c', '/o']
	v.FCFLAGS_fcshlib = ''
	v.AR_TGT_F = '/out:'

@conf
def ifort_modifier_darwin(conf):
	fc_config.fortran_modifier_darwin(conf)

@conf
def ifort_modifier_platform(conf):
	dest_os = conf.env['DEST_OS'] or Utils.unversioned_sys_platform()
	ifort_modifier_func = getattr(conf, 'ifort_modifier_' + dest_os, None)
	if ifort_modifier_func:
		ifort_modifier_func()

@conf
def get_ifort_version(conf, fc):
	"""get the compiler version"""

	version_re = re.compile(r"\bIntel\b.*\bVersion\s*(?P<major>\d*)\.(?P<minor>\d*)",re.I).search
	if Utils.is_win32:
		cmd = fc
	else:
		cmd = fc + ['-logo']

	out, err = fc_config.getoutput(conf, cmd, stdin=False)
	match = version_re(out) or version_re(err)
	if not match:
		conf.fatal('cannot determine ifort version.')
	k = match.groupdict()
	conf.env['FC_VERSION'] = (k['major'], k['minor'])

def configure(conf):
	conf.find_ifort()
	conf.find_program('xiar', var='AR')
	conf.find_ar()
	conf.fc_flags()
	conf.fc_add_flags()
	conf.ifort_modifier_platform()

