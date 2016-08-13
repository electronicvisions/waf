#! /usr/bin/env python

"""
This is a hack; In general two tasks should not provide
the same output nodes (bad abstraction), and this cannot
scale to do more operations than just stripping

In this case, the strip task has the same inputs as outputs
so the constraints added by Task.set_file_constraints
will cause a deadlock:
- By setting the input node to be the link task output node
  the strip tasks will run after the link task
- By setting the output node to be the link task output node
  any other task that also uses this output node will wait
  for the strip task to finish too
- By overriding the runnable_status method, the strip task
  will avoid the deadlock and force itself to run only when
  the link task has run
"""

def configure(conf):
	conf.find_program('strip')

from waflib import Task, TaskGen
class strip(Task.Task):
	run_str = '${STRIP} ${SRC}'
	color   = 'BLUE'
	no_errcheck_out = True

	def keyword(self):
		return 'Stripping'

	def runnable_status(self):
		if self in self.run_after:
			self.run_after.remove(self)
		ret = super(strip, self).runnable_status()
		if ret == Task.ASK_LATER:
			return ret

		if self.generator.link_task.hasrun == Task.SUCCESS:
			return Task.RUN_ME
		return Task.SKIP_ME

@TaskGen.feature('cshlib', 'cxxshlib', 'cprogram', 'cxxprogram', 'fcprogram', 'fcshlib')
@TaskGen.after('apply_link')
def add_strip_task(self):
	try:
		link_task = self.link_task
	except AttributeError:
		return

	# special case, a task with same inputs and outputs
	exe_node = link_task.outputs[0]
	self.create_task('strip', exe_node, exe_node)

