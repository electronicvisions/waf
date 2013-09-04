#!/usr/bin/env python
# encoding: utf-8
# Jérôme Carretero, 2013 (zougloub)

"""
reStructuredText support (experimental)

Example::

	def configure(conf):
		conf.load('rst')
		if not conf.env.RST2HTML:
			conf.fatal('The program rst2html is required')

	def build(bld):
		bld(
		 features = 'rst',
		 type     = 'rst2html', # rst2html, rst2pdf, ...
		 source   = 'index.rst', # mandatory, the source
		 deps     = 'image.png', # to give additional non-trivial dependencies
		)

By default the tool looks for a set of programs in PATH.
The tools are defined in `rst_progs`.
To configure with a special program use::

	$ RST2HTML=/path/to/rst2html waf configure

This tool is experimental; don't hesitate to contribute to it.

"""

import os, re
from waflib import Node, Utils, Task, Errors, Logs
from waflib.TaskGen import feature, before_method

rst_progs = "rst2html rst2xetex rst2latex rst2xml rst2pdf rst2s5 rst2man rst2odt rst2rtf".split()

def parse_rst_node(node, nodes, names, seen):
	# TODO add extensibility, to handle custom rst include tags...
	if node in seen:
		return
	seen.append(node)
	code = node.read()
	re_rst = re.compile(r'^\s*.. ((?P<subst>\|\S+\|) )?(?P<type>include|image|figure):: (?P<file>.*)$', re.M)
	for match in re_rst.finditer(code):
		ipath = match.group('file')
		itype = match.group('type')
		Logs.debug("rst: visiting %s: %s" % (itype, ipath))
		found = node.parent.find_resource(ipath)
		if found:
			nodes.append(found)
			if itype == 'include':
				parse_rst_node(found, nodes, names, seen)
		else:
			names.append(ipath)

class docutils(Task.Task):
	"""
	Compile a rst file.
	"""

	def scan(self):
		"""
		A recursive regex-based scanner that finds rst dependencies.
		"""

		nodes = []
		names = []
		seen = []

		node = self.inputs[0]

		if not node:
			return (nodes, names)

		parse_rst_node(node, nodes, names, seen)

		Logs.debug("rst: %s: found the following file deps: %s" % (repr(self), nodes))
		if names:
			Logs.warn("rst: %s: could not find the following file deps: %s" % (repr(self), names))

		return (nodes, names)

	def check_status(self, msg, retcode):
		"""
		Check an exit status and raise an error with a particular message

		:param msg: message to display if the code is non-zero
		:type msg: string
		:param retcode: condition
		:type retcode: boolean
		"""
		if retcode != 0:
			raise Errors.WafError("%r command exit status %r" % (msg, retcode))

	def run(self):
		"""
		Runs the rst compilation using docutils
		"""
		raise NotImplementedError()


class rst2html(docutils):
	color = 'BLUE'

	def scan(self):
		nodes, names = docutils.scan(self)

		stylesheet = getattr(self.generator, 'stylesheet', None)
		if stylesheet is not None:
			names.append(stylesheet)
			ssnode = self.generator.to_nodes(stylesheet)[0]
			nodes.append(ssnode)
			Logs.debug("rst: adding dep to stylesheet %s" % stylesheet)

		return nodes, names

	def run(self):
		src = self.inputs[0].bldpath()
		dst = self.outputs[0].bldpath()

		cmd = self.generator.env.RST2HTML
		cmd += Utils.to_list(getattr(self.generator, 'options', []))
		stylesheet = getattr(self.generator, 'stylesheet', None)
		if stylesheet is not None:
			stylesheet = self.generator.to_nodes(stylesheet)[0]
			cmd += ['--stylesheet', stylesheet.bldpath()]
		cmd += [src, dst]

		return self.exec_command(cmd)

class rst2pdf(docutils):
	color = 'BLUE'
	def run(self):
		src = self.inputs[0].bldpath()
		dst = self.outputs[0].bldpath()

		cmd = self.generator.env.RST2PDF + [src, '-o', dst]
		cmd += Utils.to_list(getattr(self.generator, 'options', []))

		return self.exec_command(cmd)

class rst2latex(docutils):
	color = 'BLUE'
	def run(self):
		src = self.inputs[0].bldpath()
		dst = self.outputs[0].bldpath()

		cmd = self.generator.env.RST2LATEX + [rst2x, src, dst]
		cmd += Utils.to_list(getattr(self.generator, 'options', []))

		return self.exec_command(cmd)

@feature('rst')
@before_method('process_source')
def apply_rst(self):
	"""
	Create :py:class:`rst` or other rst-related task objects
	"""

	if self.target:
		if self.target.__class__ == Node.Node:
			tgt = tsk_target
		elif self.target.__class__ == str:
			tgt = self.path.get_bld().make_node(self.target)
		else:
			raise NotImplementedError()
	else:
		tgt = None

	tsk_type = getattr(self, 'type', None)

	src = self.to_nodes(self.source)
	assert len(src) == 1
	src = src[0]

	if tsk_type is not None and tgt is None:
		if tsk_type.startswith('rst2'):
			ext = tsk_type[4:]
		else:
			raise ValueError("Feature rst could not detect the output file extension")
		tgt = src.change_ext('.%s' % ext)
	elif tsk_type is None and tgt is not None:
		out = tgt.name
		ext = out[out.rfind('.')+1:]
		self.type = 'rst2' + ext
	elif tsk_type is not None and tgt is not None:
		# the user knows what he wants
		pass
	else:
		raise ValueError("Need to indicate task type or target name for %s" % str(self))

	deps_lst = []

	if getattr(self, 'deps', None):
		deps = self.to_list(self.deps)
		for filename in deps:
			n = self.path.find_resource(filename)
			if not n:
				self.bld.fatal('Could not find %r for %r' % (filename, self))
			if not n in deps_lst:
				deps_lst.append(n)

	if self.type.startswith('rst2'):
		task = self.create_task(self.type, src, tgt)
	else:
		raise NotImplementedError()

	task.env = self.env

	# add the manual dependencies
	if deps_lst:
		try:
			lst = self.bld.node_deps[task.uid()]
			for n in deps_lst:
				if not n in lst:
					lst.append(n)
		except KeyError:
			self.bld.node_deps[task.uid()] = deps_lst

	inst_to = getattr(self, 'install_path', None)
	if inst_to:
		self.install_task = self.bld.install_files(inst_to, task.outputs[:], env=self.env)

	self.source = []

def configure(self):
	"""
	Try to find the rst programs.

	Do not raise any error if they are not found.
	You'll have to use additional code in configure() to die
	if programs were not found.
	"""
	for p in rst_progs:
		self.find_program(p, mandatory=False)

