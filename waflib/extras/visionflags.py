#!/usr/bin/env python
# encoding: utf-8
# ECM copied (it's GPL-2) from
# http://code.nsnam.org/ns-3-dev/file/fd8c9ed96d3d/waf-tools/cflags.py

# Support for --build-profile=
DEFAULT_PROFILE = 'release_with_debug'

from functools import wraps
import os
import shlex
from waflib import Logs, Options, Errors


class CompilerTraits(object):
	profiles = (
		'coverage',              # coverage
		'debug',                 # optimized for debugging
		'sanitize',              # like debug plus sanitizers
		'release',               # performance-optimized
		'ci',                    # default profile for CI
		'release_with_debug',    # performance-optimized with debugging support
		'release_with_sanitize',  # performance-optimized with sanitizer support
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
		'coverage':              '-fdiagnostics-color=always -O0 --coverage'.split(),
		'debug':                 '-fdiagnostics-color=always -Og -ggdb -g3 -fno-omit-frame-pointer'.split(),
		'sanitize':              '-fdiagnostics-color=always -Og -ggdb -g3 -fno-omit-frame-pointer -fsanitize=address -fsanitize-recover=address -fsanitize=leak'.split(),
		'release_with_debug':    '-fdiagnostics-color=always -O2 -g -fno-omit-frame-pointer -fno-strict-aliasing'.split(),
		'release_with_sanitize': '-fdiagnostics-color=always -O2 -g -fno-omit-frame-pointer -fno-strict-aliasing -fsanitize=address -fsanitize-recover=address -fsanitize=leak'.split(),
		'release':               '-fdiagnostics-color=always -O2 -fno-strict-aliasing'.split(),
		'ci':                    '-fdiagnostics-color=always -O2 -fno-strict-aliasing'.split(),
	}
	ldflags = {
		'coverage':           '--coverage'.split(),
		'sanitize':           '-fsanitize=address -fsanitize-recover=address -fsanitize=leak'.split(),
		'release_with_sanitize': '-fsanitize=address -fsanitize-recover=address -fsanitize=leak'.split()
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
		if all([substr not in build_profile for substr in ('debug', 'sanitize', 'ci')]):
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
		if self.version[0] < 4 or (self.version[0] == 4 and self.version[1] < 8):
			msg = 'gcc 4.8 (or higher) is required'
			raise Errors.ConfigurationError(msg)
		elif self.version[0] == 4 and self.version[1] == 8:
			return  ['-std=gnu++11']
		elif self.version[0] <= 5:
			return  ['-std=gnu++14']
		elif self.version[0] >= 9:
			return  ['-std=gnu++2a']
		elif self.version[0] >= 7:
			return  ['-std=gnu++17']
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
		return  ['-std=c++1z']


COMPILER_MAPPING = {
	'clang': ClangTraits,
	'clang++': ClangTraits,
	'g++': GccTraits,
	'gcc': GccTraits,
	'powerpc-eabi-gcc': GccTraits,
	'powerpc-ppu-gcc': GccTraits,
}

def _add_confcache_warning_to_fatal(klass):
	fatal_orig = klass.fatal
	@wraps(klass.fatal)
	def fatal(self, msg, *args, **kwargs):
		if getattr(Options.options, 'confcache', None):
			msg = "{}\nNOTE: confcache is enabled, make sure you supply " \
                  "--disable-confcache to configure from scratch!".format(msg)
		fatal_orig(self, msg, *args, **kwargs)
	klass.fatal = fatal

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
	opt.add_option('--linker', type=str, default="gold",
	               help='Specify the linker to use, e.g. --linker=gold or bfd.')
	# ECM (2018-01-19): optparse does not support bool-type (and monkey-patching
	# a custom optparse.Option into waf seems too much)
	opt.add_option('--disable-confcache', dest='confcache',
				action='store_false', help='Disable config cache mechanism')
	opt.add_option('--enable-confcache', dest='confcache', default=True,
				action='store_true', help='Enabling config cache mechanism (default)')

def configure(conf):
	if conf.env.LOADED_VISIONFLAGS:
		return
	conf.env.LOADED_VISIONFLAGS = True

	cc = conf.env['COMPILER_CC'] or (conf.env['CC_NAME'] or None)
	cxx = conf.env['COMPILER_CXX'] or (conf.env['CXX_NAME'] or None)
	if not (cc or cxx):
		raise Errors.WafError("neither COMPILER_CC nor COMPILER_CXX are defined; "
			"maybe the compiler_cc or compiler_cxx tool has not been configured yet?")

	# let's stick to bfd for nux cross compilation
	# PS (20-12-18): this prevents from using the powerpc compiler without using libnux (#3033)
	if 'powerpc-ppu' in conf.env.CROSS_PLATFORM:
		linker = 'bfd'
	else:
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
	user_vars = [ var for var in env_vars if var in os.environ ]
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

	# Ordered set difference: paths - paths_filter.
	def difference_paths(paths, paths_filter):
		return [x for x in paths if x not in paths_filter]

	# Get paths from environment variables.
	def get_paths_from_env(name):
		return [str(x) for x in os.environ.get(name, '').split(':') if x]

	# Inject system paths (e.g. by module environment) from `source` into `target` using compiler options:
	# uses `option_quiet` for `QUIET_` variables and drops those from the regular options.
	def inject_into_environment(envvar_source, envvar_target, option_regular, option_quiet=None):
		regular = get_paths_from_env(envvar_source)
		quiet = []

		# quiet system paths (optional, e.g. for `-I` vs. `-Isystem`)
		if option_quiet:
			quiet = get_paths_from_env("QUIET_" + envvar_source)
			if len(quiet) > 0:
				conf.env.append_value(envvar_target, ['{}{}'.format(option_quiet, x) for x in quiet])

		# non-quiet system paths
		if len(regular) > 0:
			leftover = difference_paths(regular, quiet)
			conf.env.append_value(envvar_target, ['{}{}'.format(option_regular, x) for x in leftover])

	if not conf.env.CROSS_PLATFORM:
		inject_into_environment('C_INCLUDE_PATH',     'CFLAGS',       '-I', '-isystem ')
		inject_into_environment('CPLUS_INCLUDE_PATH', 'CXXFLAGS',     '-I', '-isystem ')
		inject_into_environment('LIBRARY_PATH',       'LIBRARY_PATH', '-L')

	_add_confcache_warning_to_fatal(conf.__class__)
