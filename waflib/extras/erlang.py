#!/usr/bin/env python
# encoding: utf-8
#Thomas Nagy, 2010 (ita),  Przemyslaw Rzepecki, 2016

"""
Erlang support
"""

from waflib import Task, TaskGen
from waflib.TaskGen import extension, feature, after_method, before_method
import os
import re

# Those flags are required by the Erlang VM to execute/evaluate code in
# non-interactive mode. It is used in this tool to create Erlang modules
# documentation and run unit tests. The user can pass additional arguments to the
# 'erl' command with ERL_FLAGS environment variable.
EXEC_NON_INTERACTIVE = ['-noshell', '-noinput', '-eval']

def scan_meth(task): 
	node = task.inputs[0] 
	parent = node.parent

	deps = []
	scanned = set([])
	nodes_to_scan = [node]

	for n in nodes_to_scan:
		if n.abspath() in scanned:
			continue

		for i in re.findall('-include\("(.*)"\)\.', n.read()):
			found = False
			for d in task.includes_nodes:
				r = task.generator.path.find_resource(os.path.join(d,i))
				if r:
					deps.append(r)
					nodes_to_scan.append(r)
					found = True
					break
				r = task.generator.bld.root.find_resource(os.path.join(d,i))
				if r:
					deps.append(r)
					nodes_to_scan.append(r)
					found = True
					break
		if not found:
			pass
		scanned.add(n.abspath())

	return (deps, [])

def configure(conf):
	conf.find_program('erlc', var='ERLC')
	conf.find_program('erl', var='ERL')
	conf.add_os_flags('ERLC_FLAGS')
	conf.add_os_flags('ERL_FLAGS')

@TaskGen.extension('.erl')
def process(self, node):
	tsk = self.create_task('erl', node, node.change_ext('.beam'))
	tsk.includes_nodes = self.to_list(getattr(self, 'includes', [])) + self.env['INCLUDES'] + [node.parent.abspath()]
	tsk.defines = self.to_list(getattr(self, 'defines', [])) + self.env['DEFINES']
	tsk.flags = self.to_list(getattr(self, 'flags', [])) + self.env['ERLC_FLAGS']

class erl(Task.Task): 
	scan=scan_meth 
	color='GREEN'
	vars = ['ERLC_FLAGS', 'ERLC', 'ERL', 'INCLUDES', 'DEFINES']

	def run(self):
		output=self.inputs[0].change_ext('.beam')
		erlc = self.generator.env["ERLC"]
		inca = [i for i in self.includes_nodes if os.path.isabs(i)]
		incr = [self.generator.path.find_dir(i) for i in self.includes_nodes if not os.path.isabs(i)]
		incr = filter(lambda x:x, incr)
		incb = [i.get_bld() for i in incr]
		inc = inca + [i.abspath() for i in incr+incb]
		r = self.exec_command(
			erlc + self.flags 
			+ ["-I"+i for i in inc]
			+ ["-D"+d for d in self.defines]
			+ [self.inputs[0].path_from(output.parent)],
			cwd=output.parent.abspath(),
			shell=False)
		return r

@TaskGen.extension('.beam')
def process(self, node):
	pass


class erl_test(Task.Task):
	color = 'BLUE'
	vars = ['ERL', 'ERL_FLAGS']

	def run(self):
		test_list = ", ".join([m.change_ext("").path_from(m.parent)+":test()" for m in self.modules])
		flags = " ".join(self.flags)
		return self.exec_command(
			self.generator.env.ERL
			+ self.generator.env.ERL_FLAGS
			+ self.flags
			+ EXEC_NON_INTERACTIVE
			+ ['halt(case lists:all(fun(Elem) -> Elem == ok end, [%s]) of true  -> 0; false -> 1 end).' % test_list],
			cwd = self.modules[0].parent.abspath())

@feature('eunit')
@after_method('process_source')
def addtestrun(self):
	test_modules = [t.outputs[0] for t in self.tasks]
	test_task = self.create_task('erl_test')
	test_task.set_inputs(self.source + test_modules)
	test_task.modules = test_modules
	test_task.flags = self.to_list(getattr(self, 'flags', []))

class edoc(Task.Task):
	color = 'BLUE'
	vars = ['ERL_FLAGS', 'ERL']

	def run(self):
		self.exec_command(
			self.generator.env.ERL
			+ self.generator.env.ERL_FLAGS
			+ EXEC_NON_INTERACTIVE
			+ ['edoc:files([\"'+self.inputs[0].abspath()+'\"]), halt(0).'],
			cwd = self.outputs[0].parent.abspath()
			)

@feature('edoc')
@before_method('process_source')
def add_edoc_task(self):
	# do not process source, it would create double erl->beam task
	self.meths.remove('process_source')
	e = self.path.find_resource(self.source)
	t = e.change_ext('.html')
	png = t.parent.make_node('erlang.png')
	css = t.parent.make_node('stylesheet.css')
	self.create_task('edoc', e, [t, png, css])
