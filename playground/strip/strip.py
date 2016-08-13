#! /usr/bin/env python

"""
Strip a program/library after it is created. Use this tool as an example.

Usage::

	bld.program(features='strip', source='main.c', target='foo')

If stripping at installation time is preferred, override/modify the method
copy_fun on the installation context::

	import shutil, os
	from waflib import Build
	from waflib.Tools import ccroot
	def copy_fun(self, src, tgt, **kw):
		shutil.copy2(src, tgt)
		os.chmod(tgt, kw.get('chmod', Utils.O644))
		try:
			tsk = kw['tsk']
		except KeyError:
			pass
		else:
			if isinstance(tsk.task, ccroot.link_task):
				self.cmd_and_log('strip %s' % tgt)
	Build.InstallContext.copy_fun = copy_fun
"""

from waflib import Task

def configure(conf):
	conf.find_program('strip')

def wrap_compiled_task(classname):
	# override the class to add a new 'run' method
	# such an implementation guarantees that the absence of race conditions
	#
	def run_all(self):
		if self.env.NO_STRIPPING:
			return cls1.run(self)
		return cls1.run(self) or cls2.run(self)

	cls1 = Task.classes[classname]
	cls2 = type(classname, (cls1,), {'run_str': '${STRIP} ${TGT[0].abspath()}'})
	cls3 = type(classname, (cls2,), {'run': run_all})

for k in 'cprogram cshlib cxxprogram cxxshlib fcprogram fcshlib'.split():
	if k in Task.classes:
		wrap_compiled_task(k)

