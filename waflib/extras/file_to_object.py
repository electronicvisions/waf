#!/usr/bin/python
# -*- coding: utf-8 -*-
# Tool to embed file into objects

__author__ = __maintainer__ = "Jérôme Carretero <cJ-waf@zougloub.eu>"
__copyright__ = "Jérôme Carretero, 2014"

"""

This tool allows to embed file contents in object files (.o).
It is not exactly portable, and the file contents are reachable
using various non-portable fashions.
The goal here is to provide a functional interface to the embedding
of file data in objects.
See the ``playground/embedded_resources`` example for an example.

Usage::

   bld(
    name='pipeline',
     # ^ Reference this in use="..." for things using the generated code
    features='file_to_object',
    source='some.file',
     # ^ Name of the file to embed in binary section.
   )

Known issues:

- Currently only handles elf files with GNU ld.

- Destination is named like source, with extension renamed to .o
  eg. some.file -> some.o

"""

from waflib import Task, Utils, TaskGen

class file_to_object(Task.Task):
	run_str = '${LD} -r -b binary -o ${TGT[0].abspath()} ${SRC[0].name}'
	color = 'CYAN'

@TaskGen.feature('file_to_object')
@TaskGen.before_method('process_source')
def tg_file_to_object(self):
	bld = self.bld
	src = self.to_nodes(self.source)
	assert len(src) == 1
	src = src[0]
	tgt = src.change_ext('.o')
	task = self.create_task('file_to_object',
	 src, tgt, cwd=src.parent.abspath())
	try:
		self.compiled_tasks.append(task)
	except AttributeError:
		self.compiled_tasks = [task]
	self.source = []

def configure(conf):
	conf.load('gcc')
	conf.env.LD = [ conf.env.CC[0].replace('gcc', 'ld') ]
