#!/usr/bin/env python
# encoding: utf-8
# Carlos Rafael Giani, 2007 (dv)
# Thomas Nagy, 2010 (ita)

"""
Try to detect a D compiler from the list of supported compilers::

	def options(opt):
		opt.load('compiler_d')
	def configure(cnf):
		cnf.load('compiler_d')
	def build(bld):
		bld.program(source='main.d', target='app')

Only three D compilers are really present at the moment:

* gdc
* dmd, the ldc compiler having a very similar command-line interface
* ldc2
"""

import os, sys, imp, types, re
from waflib import Utils, Configure, Options, Logs

d_compiler = {
'default' : ['gdc', 'dmd', 'ldc2']
}
"""
Dict mapping the platform names to lists of names of D compilers to try, in order of preference::

	from waflib.Tools.compiler_d import d_compiler
	d_compiler['default'] = ['gdc', 'dmd', 'ldc2']
"""

def configure(conf):
	"""
	Try to find a suitable D compiler or raise a :py:class:`waflib.Errors.ConfigurationError`.
	"""
	for compiler in re.split('[ ,]+', conf.options.dcheck):
		conf.env.stash()
		conf.start_msg('Checking for %r (D compiler)' % compiler)
		try:
			conf.load(compiler)
		except conf.errors.ConfigurationError as e:
			conf.env.revert()
			conf.end_msg(False)
			Logs.debug('compiler_d: %r' % e)
		else:
			if conf.env.D:
				conf.end_msg(conf.env.get_flat('D'))
				conf.env['COMPILER_D'] = compiler
				break
			conf.end_msg(False)
	else:
		conf.fatal('could not configure a D compiler!')

def options(opt):
	"""
	Restrict the compiler detection from the command-line::

		$ waf configure --check-d-compiler=dmd
	"""
	build_platform = Utils.unversioned_sys_platform()
	possible_compiler_list = d_compiler.get(build_platform, d_compiler['default'])
	test_for_compiler = ' '.join(possible_compiler_list)
	d_compiler_opts = opt.add_option_group('Configuration options')
	d_compiler_opts.add_option('--check-d-compiler', default=test_for_compiler, action='store',
		help='list of D compilers to try [%s]' % test_for_compiler, dest='dcheck')
	for d_compiler in ('gdc', 'dmd', 'ldc2'):
		opt.load('%s' % d_compiler)

