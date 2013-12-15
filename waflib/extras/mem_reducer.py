#! /usr/bin/env python
# encoding: UTF-8

"""
This tool can help to reduce the memory usage in very large builds featuring many tasks with after/before attributes.

Usage:
def options(opt):
	opt.load('mem_reducer')
"""

import itertools
from waflib import Utils, Task

class SetOfTasks(object):
	"""Wraps a set and a task which has a list of other sets.
	The interface is meant to mimic the interface of set. Add missing functions as needed.
	"""
	def __init__(self, owner):
		self._set = owner.run_after
		self._owner = owner

	def __iter__(self):
		for g in self._owner.run_after_groups:
			for task in g:
				yield task
		for task in self._set:
			yield task

	def add(self, obj):
		self._set.add(obj)

	def update(self, obj):
		self._set.update(obj)

def set_precedence_constraints(tasks):
	cstr_groups = Utils.defaultdict(list)
	for x in tasks:
		x.run_after = SetOfTasks(x)
		x.run_after_groups = []

		h = x.hash_constraints()
		cstr_groups[h].append(x)

	# create sets which can be reused for all tasks
	for k in cstr_groups.iterkeys():
		cstr_groups[k] = set(cstr_groups[k])

	# this list should be short
	for key1, key2 in itertools.combinations(cstr_groups.iterkeys(), 2):
		group1 = cstr_groups[key1]
		group2 = cstr_groups[key2]
		# get the first entry of the set
		t1 = iter(group1).next()
		t2 = iter(group2).next()

		# add the constraints based on the comparisons
		if Task.is_before(t1, t2):
			for x in group2:
				x.run_after_groups.append(group1)
		elif Task.is_before(t2, t1):
			for x in group1:
				x.run_after_groups.append(group2)

Task.set_precedence_constraints = set_precedence_constraints

