#!/usr/bin/env python
# encoding: utf-8
# ECM copied (it's GPL-2) from
# http://code.nsnam.org/ns-3-dev/file/fd8c9ed96d3d/waf-tools/cflags.py

# Support for --build-profile=
DEFAULT_PROFILE = 'debug'

import os
import shlex
from waflib import Logs, Options, Utils


class CompilerTraits(object):
	profiles = (
		'gerrit',                # gerrit, build fast, warn a lot
		'debug',                 # optimized for debugging
		'release',               # performance-optimized
		'release_with_debug',    # performance-optimied with debugging support
	)

	def get_ccdefines(self, level):
		raise NotImplementedError

	def get_ccflags(self, level):
		raise NotImplementedError

	def get_cxxdefines(self, level):
		raise NotImplementedError

	def get_cxxflags(self, level):
		raise NotImplementedError


class GccTraits(CompilerTraits):
	ccflags = {
		'gerrit':             '-O0           -Wall -Wextra -pedantic'.split(),
		'debug':              '-Og -ggdb -g3 -Wall -Wextra -pedantic'.split(),
		'release':            '-O2           -Wall -Wextra -pedantic'.split(),
		'release_with_debug': '-O2 -g        -Wall -Wextra -pedantic'.split(),
	}

	def __init__(self, version):
		super(GccTraits, self).__init__()
		self.version = tuple([int(elem) for elem in version])
		# copy defaults into instance
		self.ccflags = GccTraits.ccflags

	def get_cpp_language_standard(self):
		if self.version[0] <= 4:
			return  ['-std=gnu++11']
		return []

	def get_ccdefines(self, build_profile):
		if 'debug' not in build_profile:
			return ['NDEBUG']
		return []

	def get_ccflags(self, build_profile):
		if self.version[0] < 4 or (self.version[0] == 4 and self.version[1] <= 9):
			self.ccflags['debug'] = '-O0 -ggdb -g3 -Wall -Wextra -pedantic'.split()
		return self.ccflags[build_profile]

	def get_cxxdefines(self, build_profile):
		return self.get_ccdefines(build_profile)

	def get_cxxflags(self, build_profile):
		return self.get_cpp_language_standard() + self.get_ccflags(build_profile)


COMPILER_MAPPING = {
	'gcc': GccTraits,
	'g++': GccTraits,
	'clang': GccTraits,
	'clang++': GccTraits,
}

def options(opt):
	profiles = CompilerTraits.profiles

	assert DEFAULT_PROFILE in profiles
	opt.add_option('-d', '--build-profile',
		action='store',
		default=DEFAULT_PROFILE,
		help=("Specify the build profile.  "
			"Build profiles control the default compilation flags"
			" used for C/C++ programs, if CCFLAGS/CXXFLAGS are not"
			" set in the environment. [Allowed Values: %s]"
			% ", ".join([repr(p) for p in profiles])),
		choices=profiles,
		dest='build_profile')
	opt.add_option('--check-profile',
		help=('print out current build profile'),
		default=False, dest='check_profile', action="store_true")


def configure(conf):
	cc = conf.env['COMPILER_CC'] or (conf.env['CC_NAME'] or None)
	cxx = conf.env['COMPILER_CXX'] or (conf.env['CXX_NAME'] or None)
	if not (cc or cxx):
		raise Utils.WafError("neither COMPILER_CC nor COMPILER_CXX are defined; "
			"maybe the compiler_cc or compiler_cxx tool has not been configured yet?")

	try:
		compiler = COMPILER_MAPPING[cc](conf.env['CC_VERSION'])
	except KeyError:
		try:
			compiler = COMPILER_MAPPING[cxx](conf.env['CC_VERSION'])
		except KeyError:
			Logs.warn("No compiler flags support for compiler %r or %r" % (cc, cxx))
			return

	for profile in CompilerTraits.profiles:
		assert profile in compiler.profiles

	build_profile = Options.options.build_profile
	
	# ECM: Policy => don't touch env vars if they are set! The user knows it better!
	env_vars = 'CCDEFINES CCFLAGS CXXDEFINES CXXFLAGS'.split()
	user_vars = [ var for var in env_vars if os.environ.has_key(var) ]
	if user_vars:
		Logs.warn('Visionary build flags have been disabled due to user-defined '
		          'environment variables: %s' % ', '.join(user_vars))
		return

	# _PREPEND and _APPEND variables to a given variable
	def sandwich(var_name, content):
		pre = shlex.split(os.environ.get('%s_PREPEND' % var_name, ''))
		app = shlex.split(os.environ.get('%s_APPEND' % var_name, ''))
		return var_name, pre + content + app

	conf.env.append_value(*sandwich('CCFLAGS',   compiler.get_ccflags(build_profile)))
	conf.env.append_value(*sandwich('CCDEFINES', compiler.get_ccdefines(build_profile)))
	conf.env.append_value(*sandwich('CXXFLAGS',   compiler.get_cxxflags(build_profile)))
	conf.env.append_value(*sandwich('CXXDEFINES', compiler.get_cxxdefines(build_profile)))
