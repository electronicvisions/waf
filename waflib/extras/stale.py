#! /usr/bin/env python
# encoding: UTF-8
# Thomas Nagy, 2006-2014 (ita)

"""
Add a pre-build hook to remove all build files
which do not have a corresponding target

This can be used for example to remove the targets
that have changed name without performing
a full 'waf clean'

Of course, it will only work if there are no dynamically generated
nodes/tasks, in which case the method will have to be modified
to exclude some folders for example.
"""

from waflib import Logs, Build
from waflib.Runner import Parallel

DYNAMIC_EXT = ['.moc']

old = Parallel.refill_task_list
def refill_task_list(self):
	iit = old(self)
	bld = self.bld

	# execute this operation only once
	if getattr(self, 'stale_done', False):
		return iit
	self.stale_done = True

	# this does not work in partial builds
	if hasattr(bld, 'options') and bld.options.targets and bld.options.targets != '*':
		return iit

	# this does not work in dynamic builds
	if not hasattr(bld, 'post_mode') or bld.post_mode == Build.POST_LAZY:
		return iit

	# obtain the nodes to use during the build
	nodes = []
	for i in range(len(bld.groups)):
		tasks = bld.get_tasks_group(i)
		for x in tasks:
			try:
				nodes.extend(x.outputs)
			except:
				pass

	# recursion over the nodes to find the stale files
	def iter(node):

		if node.abspath() in bld.env[Build.CFG_FILES]:
			return

		if getattr(node, 'children', []):
			for x in node.children.values():
				if x.name != "c4che":
					iter(x)
		else:
			for ext in DYNAMIC_EXT:
				if node.name.endswith(ext):
					break
			else:
				if not node in nodes:
					Logs.warn("Removing stale file -> %s" % node.abspath())
					node.delete()
	iter(bld.bldnode)
	return iit

Parallel.refill_task_list = refill_task_list

