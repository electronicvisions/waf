#!/usr/bin/env python
# coding=utf-8
# Thomas Nagy, 2016

"""
Force all build files to go to the build directory:

	def options(opt):
		opt.load('force_build_directory')

"""

import os
from waflib import Node

def find_or_declare(self, lst):
	if isinstance(lst, str) and os.path.isabs(lst):
		node = self.ctx.root.make_node(lst)
	else:
		node = self.get_bld().make_node(lst)
	node.parent.mkdir()
	return node
Node.Node.find_or_declare = find_or_declare
