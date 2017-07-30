#! /usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2017 (ita)

"""
A system for fast partial rebuilds

Creating a large amount of task objects up front can take some time.
By making a few assumptions, it is possible to avoid posting creating
task objects for targets that are already up-to-date

On a silly benchmark the gain observed for 20000 tasks can be 5s->1s for
a single file change.

Assuptions:
* Mostly for C/C++/Fortran targets with link tasks (object-only targets are not handled)
* This is only for full project builds, so this does not interfere with --targets
* Building from a subfolder does not prune targets from that folder
* The installation phase is ignored
* `use=` dependencies are fully specified up front even across build groups
* Files are not modified while building
"""

import os
from waflib import Build, Context, Errors, Logs, Task, Utils
from waflib.TaskGen import feature, after_method, taskgen_method

DONE = 0
DIRTY = 1
NEEDED = 2

class bld(Build.BuildContext):
	def store(self):
		if self.producer.dirty:
			# For each task generator, record all files involved in task objects
			# optimization: done only if there was something built
			for g in self.groups:
				for tg in g:
					do_cache = False
					for tsk in tg.tasks:
						if tsk.hasrun == Task.SUCCESS:
							do_cache = True
							pass
						elif tsk.hasrun == Task.SKIPPED:
							pass
						else:
							# dependencies are incomplete, clear the cache
							try:
								del self.raw_deps[(tg.path.abspath(), tg.idx)]
							except KeyError:
								pass
							break
					else:
						wscript_time = os.stat(tg.path.abspath()).st_mtime
						if not do_cache:
							try:
								cache = self.raw_deps[(tg.path.abspath(), tg.idx)]
							except KeyError:
								# probably cleared because a wscript file changed
								do_cache = True
							else:
								cache[0] = wscript_time


						if do_cache:
							cache = self.raw_deps[(tg.path.abspath(), tg.idx)] = [wscript_time]
							st = set()
							for tsk in tg.tasks:
								st.update(tsk.inputs)
								st.update(self.node_deps.get(tsk.uid(), []))
							cache += sorted(x.abspath() for x in st)
		return Build.BuildContext.store(self)

	def compute_needed_tgs(self):
		# assume the 'use' keys are not modified during the build phase

		# 1. obtain task generators that contain rebuilds
		stales = set()
		for g in self.groups:
			for tg in g:
				if tg.is_stale():
					stales.add(tg)
		reverse_use_map = Utils.defaultdict(list)
		use_map = Utils.defaultdict(list)

		# 2. obtain the 'use' graph and its dual
		for g in self.groups:
			for tg in g:
				try:
					lst = tg.use = Utils.to_list(tg.use)
				except AttributeError:
					pass
				else:
					for x in lst:
						try:
							xtg = self.get_tgen_by_name(x)
						except Errors.WafError:
							pass
						else:
							use_map[tg].append(xtg)
							reverse_use_map[xtg].append(tg)

		# 3. dfs to post downstream tg as stale
		visited = set()
		def mark_down(tg):
			if tg in visited:
				return
			visited.add(tg)
			Logs.debug('rev_use: marking down %r as stale', tg.name)
			tg.staleness = DIRTY
			for x in reverse_use_map[tg]:
				mark_down(x)
		for tg in stales:
			mark_down(tg)

		# 4. dfs to find ancestors tg to mark as needed
		self.needed_tgs = needed_tgs = set()
		def mark_needed(tg):
			if tg in needed_tgs:
				return
			needed_tgs.add(tg)
			if tg.staleness == DONE:
				Logs.debug('rev_use: marking up %r as needed', tg.name)
				tg.staleness = NEEDED
			for x in use_map[tg]:
				mark_needed(x)
		for xx in visited:
			mark_needed(xx)

		# so we have the whole tg trees to post in the set "needed"
		# the stale ones should be fully build, while the needed ones
		# may skip a few tasks, see create_compiled_task and apply_link_after below
		Logs.debug('rev_use: amount of needed task gens: %r', len(needed_tgs))

	def post_group(self):
		# assumption: we can ignore the folder/subfolders cuts
		def tgpost(tg):
			try:
				f = tg.post
			except AttributeError:
				pass
			else:
				f()

		if not self.targets or self.targets == '*':
			for tg in self.groups[self.current_group]:
				# this can cut quite a lot of tg objects
				if tg in self.needed_tgs:
					tgpost(tg)
		else:
			# default implementation
			return Build.BuildContext.post_group()

	def get_build_iterator(self):
		if not self.targets or self.targets == '*':
			self.compute_needed_tgs()
		return Build.BuildContext.get_build_iterator(self)

@taskgen_method
def is_stale(self):
	# assume no globs

	self.staleness = DIRTY
	db = os.path.join(self.bld.variant_dir, Context.DBFILE)
	try:
		dbstat = os.stat(db).st_mtime
	except OSError:
		return True

	# 1. check if the configuration changed
	if os.stat(self.bld.bldnode.find_node('c4che').abspath()).st_mtime > dbstat:
		Logs.debug('rev_use: must post %r because the configuration has changed', self.name)
		return True

	# 2. check if this is the first build (no cache)
	try:
		lst = self.bld.raw_deps[(self.path.abspath(), self.idx)]
	except KeyError:
		Logs.debug('rev_use: must post %r because there is no cached data', self.name)
		return True

	# 3. check if the wscript file changed from the previous dep storage
	# assume that the folder timestamp reflects the wscript state
	folder_tstamp = os.stat(self.path.abspath()).st_mtime
	if folder_tstamp != lst[0]:
		Logs.debug('rev_use: must post %r because the tg definition may have changed', self.name)
		return True

	# 4. check the timestamp of dependency files listed are not newer than the last build
	# assume that a file is not modified during a build ~
	def tstamp(x):
		# do some caching
		try:
			cache = self.bld.cache_tstamp_rev_use
		except AttributeError:
			cache = self.bld.cache_tstamp_rev_use = {}
		try:
			return cache[x]
		except KeyError:
			ret = cache[x] = os.stat(x).st_mtime
			return ret

	for x in lst[1:]:
		try:
			ts = tstamp(x)
		except OSError:
			self.bld.raw_deps[(self.path.abspath(), self.idx)] = [folder_tstamp]
			Logs.debug('rev_use: must post %r because %r does not exist anymore', self.name, x)
			return True
		else:
			if ts > dbstat:
				Logs.debug('rev_use: must post %r because %r is newer than the db file', self.name, x)
				return True

	self.staleness = DONE
	return False

@taskgen_method
def create_compiled_task(self, name, node):
	if self.staleness == NEEDED:
		return None

	out = '%s.%d.o' % (node.name, self.idx)
	task = self.create_task(name, node, node.parent.find_or_declare(out))
	try:
		self.compiled_tasks.append(task)
	except AttributeError:
		self.compiled_tasks = [task]
	return task

@feature('c', 'cxx', 'd', 'fc', 'asm')
@after_method('apply_link')
def apply_link_after(self):
	if self.staleness != NEEDED:
		return
	try:
		link_task = self.link_task
	except AttributeError:
		pass
	else:
		link_task.hasrun = Task.SKIPPED

