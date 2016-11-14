#!/usr/bin/env python
# coding=utf-8
# Thomas Nagy, 2016

"""
Force all build files to go to the build directory:

	def options(opt):
		opt.load('force_build_directory')

"""

import os
from waflib import Node, Utils

def find_or_declare(self, lst):
	if isinstance(lst, str):
		lst = [x for x in Utils.split_path(lst) if x and x != '.']

	node = self.get_bld().search_node(lst)
	if node:
		if not os.path.isfile(node.abspath()):
			node.parent.mkdir()
		return node
	node = self.get_bld().make_node(lst)
	node.parent.mkdir()
	return node
Node.Node.find_or_declare = find_or_declare
