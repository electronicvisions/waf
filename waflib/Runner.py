#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2005-2010 (ita)

"""
Runner.py: Task scheduling and execution

"""

import random
try:
	from queue import Queue
except ImportError:
	from Queue import Queue
from waflib import Utils, Task, Errors, Logs

GAP = 10
"""
Wait for free tasks if there are at least ``GAP * njobs`` in queue
"""

class Consumer(Utils.threading.Thread):
	def __init__(self, spawner, task):
		Utils.threading.Thread.__init__(self)
		self.task = task
		self.spawner = spawner
		self.setDaemon(1)
		self.start()
	def run(self):
		self.task.process()
		self.spawner.sem.release()

class Spawner(Utils.threading.Thread):
	def __init__(self, master):
		Utils.threading.Thread.__init__(self)
		self.master = master
		self.sem = Utils.threading.Semaphore(master.numjobs)
		self.setDaemon(1)
		self.start()
	def run(self):
		master = self.master
		while 1:
			task = master.ready.get()
			self.sem.acquire()
			task.log_display(task.generator.bld)
			Consumer(self, task)

class Parallel(object):
	"""
	Schedule the tasks obtained from the build context for execution.
	"""
	def __init__(self, bld, j=2):
		"""
		The initialization requires a build context reference
		for computing the total number of jobs.
		"""

		self.numjobs = j
		"""
		Number of consumers in the pool
		"""

		self.bld = bld
		"""
		Instance of :py:class:`waflib.Build.BuildContext`
		"""

		self.outstanding = []
		"""List of :py:class:`waflib.Task.TaskBase` that may be ready to be executed"""

		self.frozen = []
		"""List of :py:class:`waflib.Task.TaskBase` that cannot be executed immediately"""

		self.ready = Queue(0)

		self.out = Queue(0)
		"""List of :py:class:`waflib.Task.TaskBase` returned by the task consumers"""

		self.count = 0
		"""Amount of tasks that may be processed by :py:class:`waflib.Runner.TaskConsumer`"""

		self.processed = 1
		"""Amount of tasks processed"""

		self.stop = False
		"""Error flag to stop the build"""

		self.error = []
		"""Tasks that could not be executed"""

		self.biter = None
		"""Task iterator which must give groups of parallelizable tasks when calling ``next()``"""

		self.dirty = False
		"""Flag to indicate that tasks have been executed, and that the build cache must be saved (call :py:meth:`waflib.Build.BuildContext.store`)"""

		self.spawner = Spawner(self)

	def get_next_task(self):
		"""
		Obtain the next task to execute.

		:rtype: :py:class:`waflib.Task.TaskBase`
		"""
		if not self.outstanding:
			return None
		return self.outstanding.pop(0)

	def postpone(self, tsk):
		"""
		A task cannot be executed at this point, put it in the list :py:attr:`waflib.Runner.Parallel.frozen`.

		:param tsk: task
		:type tsk: :py:class:`waflib.Task.TaskBase`
		"""
		if random.randint(0, 1):
			self.frozen.insert(0, tsk)
		else:
			self.frozen.append(tsk)

	def refill_task_list(self):
		"""
		Put the next group of tasks to execute in :py:attr:`waflib.Runner.Parallel.outstanding`.
		"""
		while self.count > self.numjobs * GAP:
			self.get_out()

		while not self.outstanding:
			if self.count:
				self.get_out()
			elif self.frozen:
				try:
					cond = self.deadlock == self.processed
				except AttributeError:
					pass
				else:
					if cond:
						msg = 'check the build order for the tasks'
						for tsk in self.frozen:
							if not tsk.run_after:
								msg = 'check the methods runnable_status'
								break
						lst = []
						for tsk in self.frozen:
							lst.append('%s\t-> %r' % (repr(tsk), [id(x) for x in tsk.run_after]))
						raise Errors.WafError('Deadlock detected: %s%s' % (msg, ''.join(lst)))
				self.deadlock = self.processed

			if self.frozen:
				self.outstanding += self.frozen
				self.frozen = []
			elif not self.count:
				self.outstanding.extend(next(self.biter))
				self.total = self.bld.total()
				break

	def add_more_tasks(self, tsk):
		"""
		Tasks may be added dynamically during the build by binding them to the task :py:attr:`waflib.Task.TaskBase.more_tasks`

		:param tsk: task
		:type tsk: :py:attr:`waflib.Task.TaskBase`
		"""
		if getattr(tsk, 'more_tasks', None):
			self.outstanding += tsk.more_tasks
			self.total += len(tsk.more_tasks)

	def get_out(self):
		"""
		Obtain one task returned from the task consumers, and update the task count. Add more tasks if necessary through
		:py:attr:`waflib.Runner.Parallel.add_more_tasks`.

		:rtype: :py:attr:`waflib.Task.TaskBase`
		"""
		tsk = self.out.get()
		if not self.stop:
			self.add_more_tasks(tsk)
		self.count -= 1
		self.dirty = True
		return tsk

	def add_task(self, tsk):
		"""
		Pass a task to a consumer.

		:param tsk: task
		:type tsk: :py:attr:`waflib.Task.TaskBase`
		"""
		self.ready.put(tsk)

	def skip(self, tsk):
		tsk.hasrun = Task.SKIPPED

	def error_handler(self, tsk):
		"""
		Called when a task cannot be executed. The flag :py:attr:`waflib.Runner.Parallel.stop` is set, unless
		the build is executed with::

			$ waf build -k

		:param tsk: task
		:type tsk: :py:attr:`waflib.Task.TaskBase`
		"""
		if hasattr(tsk, 'scan') and hasattr(tsk, 'uid'):
			# TODO waf 1.9 - this breaks encapsulation
			try:
				del self.bld.imp_sigs[tsk.uid()]
			except KeyError:
				pass
		if not self.bld.keep:
			self.stop = True
		self.error.append(tsk)

	def task_status(self, tsk):
		try:
			return tsk.runnable_status()
		except Exception:
			self.processed += 1
			tsk.err_msg = Utils.ex_stack()
			if not self.stop and self.bld.keep:
				self.skip(tsk)
				if self.bld.keep == 1:
					# if -k stop at the first exception, if -kk try to go as far as possible
					if Logs.verbose > 1 or not self.error:
						self.error.append(tsk)
					self.stop = True
				else:
					if Logs.verbose > 1:
						self.error.append(tsk)
				return Task.EXCEPTION
			tsk.hasrun = Task.EXCEPTION

			self.error_handler(tsk)
			return Task.EXCEPTION

	def start(self):
		"""
		Give tasks to :py:class:`waflib.Runner.TaskConsumer` instances until the build finishes or the ``stop`` flag is set.
		If only one job is used, then execute the tasks one by one, without consumers.
		"""

		self.total = self.bld.total()

		while not self.stop:

			self.refill_task_list()

			# consider the next task
			tsk = self.get_next_task()
			if not tsk:
				if self.count:
					# tasks may add new ones after they are run
					continue
				else:
					# no tasks to run, no tasks running, time to exit
					break

			if tsk.hasrun:
				# if the task is marked as "run", just skip it
				self.processed += 1
				continue

			if self.stop: # stop immediately after a failure was detected
				break


			st = self.task_status(tsk)
			if st == Task.RUN_ME:
				self.count += 1
				self.processed += 1

				if self.numjobs == 1:
					tsk.process()
				else:
					self.add_task(tsk)
			if st == Task.ASK_LATER:
				self.postpone(tsk)
			elif st == Task.SKIP_ME:
				self.processed += 1
				self.skip(tsk)
				self.add_more_tasks(tsk)

		# self.count represents the tasks that have been made available to the consumer threads
		# collect all the tasks after an error else the message may be incomplete
		while self.error and self.count:
			self.get_out()

		#print loop
		assert (self.count == 0 or self.stop)

