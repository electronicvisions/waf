#!/usr/bin/env python
# encoding: utf-8
# ECM copied (it's GPL-2) from
# http://code.nsnam.org/ns-3-dev/file/fd8c9ed96d3d/waf-tools/cflags.py

# Support for --build-profile=
DEFAULT_PROFILE = 'debug'

import os
import shlex
from waflib import Logs, Options, Errors


class CompilerTraits(object):
	profiles = (
		'coverage',              # coverage
		'gerrit',                # gerrit, build fast, warn a lot
		'debug',                 # optimized for debugging
		'release',               # performance-optimized
		'release_with_debug',    # performance-optimied with debugging support
	)

	def get_cflags(self, level):
		raise NotImplementedError(type(self))

	def get_cxxflags(self, level):
		raise NotImplementedError(type(self))

	def get_defines(self, level):
		raise NotImplementedError(type(self))

	def get_linkflags(self, level):
		raise NotImplementedError(type(self))


class CommonTraits(CompilerTraits):
	warning_flags = '-Wall -Wextra -pedantic'.split()
	cflags = {
		'coverage':           '-O0 --coverage'.split(),
		'gerrit':             '-O0'.split(),
		'debug':              '-Og -ggdb -g3 -fno-omit-frame-pointer'.split(),
		'release_with_debug': '-O2 -g -fno-omit-frame-pointer'.split(),
		'release':            '-O2'.split(),
	}
	ldflags = {
		'coverage':           '--coverage'.split(),
	}

	def __init__(self, version, linker=None):
		super(CommonTraits, self).__init__()
		self.version = tuple([int(elem) for elem in version])
		self.linker = linker

	def get_cflags(self, build_profile):
		return self.cflags[build_profile] + self.warning_flags

	def get_cpp_language_standard_flags(self):
		return []

	def get_cxxflags(self, build_profile):
		return self.get_cpp_language_standard_flags() + self.get_cflags(build_profile)

	def get_defines(self, build_profile):
		if 'debug' not in build_profile:
			return ['NDEBUG']
		return []

	def get_linkflags(self, build_profile):
		linkflags = []
		if self.linker is not None:
			linkflags += ['-fuse-ld={}'.format(self.linker)]
		linkflags += self.ldflags.get(build_profile, [])
		return linkflags


class GccTraits(CommonTraits):
	def __init__(self, version, linker=None):
		super(GccTraits, self).__init__(version, linker)

		if self.linker == 'gold' and self.version < (4, 8):
			raise Errors.WafError('GCC >= 4.8 is required for gold linker')

		# copy defaults into instance
		self.cflags = GccTraits.cflags

		if self.version[0] < 4 or (self.version[0] == 4 and self.version[1] <= 9):
			for profile, flags in self.cflags.items():
				self.cflags[profile] = [
					('-O0' if flag == '-Og' else flag) for flag in flags
				]

	def get_cpp_language_standard_flags(self):
		# Default for gcc 5.0 should be `-std=gnu++14` (cf. upstream changelog),
		# but it's not the case for Ubuntu's 5.4.0!
		if self.version[0] < 4 or (self.version[0] == 4 and self.version[1] < 9):
			msg = 'gcc 4.9 (or higher) is required'
			raise Errors.ConfigurationError(msg)
		elif self.version[0] <= 5:
			return  ['-std=gnu++14']
		return []


class ClangTraits(CommonTraits):
	def __init__(self, version, linker=None):
		super(ClangTraits, self).__init__(version, linker)

		# copy defaults into instance
		self.cflags = ClangTraits.cflags

		for profile, flags in self.cflags.items():
			self.cflags[profile] = [
				('-O0' if flag == '-Og' else flag) for flag in flags
			]

	def get_cpp_language_standard_flags(self):
		if self.version < (3, 5):
			return  ['-std=c++11']
		return  ['-std=c++14']


COMPILER_MAPPING = {
	'clang': ClangTraits,
	'clang++': ClangTraits,
	'g++': GccTraits,
	'gcc': GccTraits,
	'powerpc-eabi-gcc': GccTraits,
}

def options(opt):
	profiles = CompilerTraits.profiles

	assert DEFAULT_PROFILE in profiles
	opt.add_option('-d', '--build-profile',
		action='store',
		default=DEFAULT_PROFILE,
		help=("Specify the build profile.  "
			"Build profiles control the default compilation flags"
			" used for C/C++ programs, if CFLAGS/CXXFLAGS are not"
			" set in the environment. [Allowed Values: %s]"
			% ", ".join([repr(p) for p in profiles])),
		choices=profiles,
		dest='build_profile')
	opt.add_option('--check-profile',
		help=('print out current build profile'),
		default=False, dest='check_profile', action="store_true")
	opt.add_option('--linker', type=str, default=None,
	               help='Specify the linker to use, e.g. --linker=gold.')


def configure(conf):
	cc = conf.env['COMPILER_CC'] or (conf.env['CC_NAME'] or None)
	cxx = conf.env['COMPILER_CXX'] or (conf.env['CXX_NAME'] or None)
	if not (cc or cxx):
		raise Errors.WafError("neither COMPILER_CC nor COMPILER_CXX are defined; "
			"maybe the compiler_cc or compiler_cxx tool has not been configured yet?")

	linker = Options.options.linker
	try:
		compiler = COMPILER_MAPPING[cc](conf.env['CC_VERSION'], linker)
	except KeyError:
		try:
			compiler = COMPILER_MAPPING[cxx](conf.env['CC_VERSION'], linker)
		except KeyError:
			Logs.warn("No compiler flags support for compiler %r or %r" % (cc, cxx))
			return

	for profile in CompilerTraits.profiles:
		assert profile in compiler.profiles

	build_profile = Options.options.build_profile
	
	# ECM: Policy => don't touch env vars if they are set! The user knows it better!
	env_vars = 'DEFINES CFLAGS CXXFLAGS LINKFLAGS'.split()
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

	conf.env.append_value(*sandwich('CFLAGS',   compiler.get_cflags(build_profile)))
	conf.env.append_value(*sandwich('DEFINES', compiler.get_defines(build_profile)))
	conf.env.append_value(*sandwich('CXXFLAGS',   compiler.get_cxxflags(build_profile)))
	conf.env.append_value(*sandwich('LINKFLAGS', compiler.get_linkflags(build_profile)))
