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
from waflib import Build, Errors, Logs, Task, Runner, Utils
from waflib.TaskGen import feature, after_method, taskgen_method

DONE = 0
DIRTY = 1
NEEDED = 2

STALE_FLAG_FILE_COMMITTED = '.stale-flag-committed'
STALE_FLAG_FILE_TMP = '.stale-flag-tmp'

SKIPPABLE = ['cshlib', 'cxxshlib', 'cstlib', 'cxxstlib', 'cprogram', 'cxxprogram']

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
						if not do_cache:
							try:
								self.raw_deps[(tg.path.abspath(), tg.idx)]
							except KeyError:
								# probably cleared because a wscript file changed
								do_cache = True

						if do_cache:
							st = set()
							for tsk in tg.tasks:
								st.update(tsk.inputs)
								st.update(self.node_deps.get(tsk.uid(), []))
							lst = list(sorted(x.abspath() for x in st))
							self.raw_deps[(tg.path.abspath(), tg.idx)] = lst

		stale_file_tmp = os.path.join(self.variant_dir, STALE_FLAG_FILE_TMP)
		stale_file_committed = os.path.join(self.variant_dir, STALE_FLAG_FILE_COMMITTED)
		os.rename(stale_file_tmp, stale_file_committed)

		if self.producer.dirty:
			return Build.BuildContext.store(self)

	def compile(self):
		Logs.debug('build: compile()')
		self.producer = Runner.Parallel(self, self.jobs)
		self.producer.biter = self.get_build_iterator()
		try:
			self.producer.start()
		except KeyboardInterrupt:
			self.store()
			raise
		else:
			# always store here
			self.store()

		if self.producer.error:
			raise Errors.BuildError(self.producer.error)

	def compute_needed_tgs(self):
		# assume the 'use' keys are not modified during the build phase

		# 1. obtain task generators that contain rebuilds
		# 2. obtain the 'use' graph and its dual
		stales = set()
		reverse_use_map = Utils.defaultdict(list)
		use_map = Utils.defaultdict(list)

		for g in self.groups:
			for tg in g:
				if tg.is_stale():
					stales.add(tg)

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

		Logs.debug('rev_use: found %r stale tgs', len(stales))

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
			stale_file_tmp = os.path.join(self.variant_dir, STALE_FLAG_FILE_TMP)
			Utils.writef(stale_file_tmp, '')
			self.compute_needed_tgs()
		return Build.BuildContext.get_build_iterator(self)

@taskgen_method
def is_stale(self):
	# assume no globs
	self.staleness = DIRTY

	# 0. the case of always stale targets
	if getattr(self, 'always_stale', False):
		return True

	db = os.path.join(self.bld.variant_dir, STALE_FLAG_FILE_COMMITTED)
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


	try:
		cache = self.bld.cache_tstamp_rev_use
	except AttributeError:
		cache = self.bld.cache_tstamp_rev_use = {}

	def tstamp(x):
		# compute files timestamps with some caching
		try:
			return cache[x]
		except KeyError:
			ret = cache[x] = os.stat(x).st_mtime
			return ret

	# 3. double-check if this is the first build
	rev_path = os.path.join(self.bld.variant_dir, STALE_FLAG_FILE_COMMITTED)
	try:
		dbstat = tstamp(rev_path)
	except OSError:
		Logs.debug('rev_use: must post %r because there is no rev path file %r', self.name, rev_path)
		return True

	# 4. check if the wscript file changed from the previous dep storage
	# assume that the folder timestamp reflects the wscript state
	folder_tstamp = os.stat(self.path.abspath()).st_mtime
	if folder_tstamp >= dbstat:
		Logs.debug('rev_use: must post %r because the tg definition may have changed', self.name)
		return True

	# 5. check the timestamp of dependency files listed are not newer than the last build
	for x in lst:
		try:
			ts = tstamp(x)
		except OSError:
			self.bld.raw_deps[(self.path.abspath(), self.idx)] = [folder_tstamp]
			Logs.debug('rev_use: must post %r because %r does not exist anymore', self.name, x)
			return True
		else:
			if ts >= dbstat:
				Logs.debug('rev_use: must post %r because %r is newer than the db file', self.name, x)
				return True

	self.staleness = DONE
	return False

@taskgen_method
def create_compiled_task(self, name, node):
	# the purpose is to skip the creation of object files
	if self.staleness == NEEDED:
		# only libraries/programs can skip object files
		for x in SKIPPABLE:
			if x in self.features:
				return None

	out = '%s.%d.o' % (node.name, self.idx)
	task = self.create_task(name, node, node.parent.find_or_declare(out))
	try:
		self.compiled_tasks.append(task)
	except AttributeError:
		self.compiled_tasks = [task]
	return task

@feature(*SKIPPABLE)
@after_method('apply_link')
def apply_link_after(self):
	# assumption: object-only targets are not skippable
	# cprogram/cxxprogram might be unnecessary
	if self.staleness != NEEDED:
		return
	try:
		link_task = self.link_task
	except AttributeError:
		pass
	else:
		link_task.hasrun = Task.SKIPPED

