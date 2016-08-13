#! /usr/bin/env python

import shutil, os
from waflib import Build, Utils
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

