#!/usr/bin/env python
# encoding: utf-8
# Remote Builds tool using rsync+ssh

__author__ = "Jérôme Carretero <cJ-waf@zougloub.eu>"
__copyright__ = "Jérôme Carretero, 2013"

"""
Simple Remote Builds
********************

This tool is an *experimental* tool (meaning, do not even try to pollute
the waf bug tracker with bugs in here, contact me directly) providing simple
remote builds.

It uses rsync and ssh to perform the remote builds.
It is intended for performing cross-compilation on platforms where
a cross-compiler is either unavailable (eg. MacOS, QNX) a specific product
does not exist (eg. Windows builds using Visual Studio) or simply not installed.
This tool sends the sources and the waf script to the remote host,
and commands the usual waf execution.

There are alternatives to using this tool, such as setting up shared folders,
logging on to remote machines, and building on the shared folders.
Electing one method or another depends on the size of the program.


Usage
=====

1. Set your wscript file so it includes a list of variants,
   e.g.::

     from waflib import Utils
     top = '.'
     out = 'build'

     variants = [
      'linux_64_debug',
      'linux_64_release',
      'linux_32_debug',
      'linux_32_release',
      ]

     from waflib.extras import remote

     def options(opt):
         # normal stuff from here on
         opt.load('compiler_c')

     def configure(conf):
         if not conf.variant:
             return
         # normal stuff from here on
         conf.load('compiler_c')

     def build(bld):
         if not bld.variant:
             return
         # normal stuff from here on
         bld(features='c cprogram', target='app', source='main.c')


2. Build the waf file, so it includes this tool, and put it in the current
   directory

   .. code:: bash

      ./waf-light --tools=remote

3. Setup the ssh server and ssh keys so that password-less login is possible
   (unless you really want to type the passwords every time...).

4. Set host names to access the hosts:

   .. code:: bash

      export REMOTE_QNX=user@kiunix

5. Perform the build:

   .. code:: bash

      waf configure_all build_all --remote

"""


import getpass, os, sys
from collections import OrderedDict
from waflib import Context, Options, Utils, ConfigSet

from waflib.Build import BuildContext, CleanContext, InstallContext, UninstallContext
from waflib.Configure import ConfigurationContext


is_remote = False
if '--remote' in sys.argv:
	is_remote = True
	sys.argv.remove('--remote')

class init(Context.Context):
	"""
	Generates the *_all commands
	"""
	cmd = 'init'
	fun = 'init'
	def execute(self):
		for x in list(Context.g_module.variants):
			self.make_variant(x)
		for name in ('configure', 'clean', 'build', 'install'):
			if ('%s_all' % name) in Options.commands:
				Options.commands.remove('%s_all' % name)
				for x in Context.g_module.variants:
					Options.commands.insert(0, '%s_%s' % (name, x))

		Options.commands.insert(0, 'remote')

	def make_variant(self, x):
		for y in (BuildContext, CleanContext, InstallContext, UninstallContext):
			name = y.__name__.replace('Context','').lower()
			class tmp(y):
				cmd = name + '_' + x
				fun = 'build'
				variant = x
		class tmp(ConfigurationContext):
			cmd = 'configure_' + x
			fun = 'configure'
			def __init__(self, **kw):
				ConfigurationContext.__init__(self, **kw)
				self.setenv(x)

class remote(BuildContext):
	cmd = 'remote'
	fun = 'build'

	def skip_unbuildable_variant(self):
		# skip variants that cannot be built on this OS
		for k in Options.commands:
			a, _, b = k.partition('_')
			if b in Context.g_module.variants:
				c, _, _ = b.partition('_')
				if c != Utils.unversioned_sys_platform():
					Options.commands.remove(k)

	def variant_to_host(self, variant):
		"""linux_32_debug -> search LINUX_32 configs and then LINUX"""
		x = variant[:variant.rfind('_')]
		ret = os.environ.get('REMOTE_' + x.upper(), '')
		if not ret:
			x = x[:x.find('_')]
			ret = os.environ.get('REMOTE_' + x.upper(), '')
		if not ret:
			ret = '%s@localhost' % getpass.getuser()
		return ret

	def execute(self):
		global is_remote
		if not is_remote:
			self.skip_unbuildable_variant()
		else:
			BuildContext.execute(self)

	def restore(self):
		self.top_dir = os.path.abspath(Context.g_module.top)
		self.srcnode = self.root.find_node(self.top_dir)
		self.path = self.srcnode

		self.out_dir = os.path.join(self.top_dir, Context.g_module.out)
		self.bldnode = self.root.make_node(self.out_dir)
		self.bldnode.mkdir()

		self.env = ConfigSet.ConfigSet()

	def extract_groups_of_builds(self):
		"""Return a dict mapping each variants to the commands to build"""
		groups = {}
		for x in reversed(Options.commands):
			_, _, variant = x.partition('_')
			if variant in Context.g_module.variants:
				try:
					dct = groups[variant]
				except KeyError:
					dct = groups[variant] = OrderedDict()
				try:
					dct[variant].append(x)
				except KeyError:
					dct[variant] = [x]
				Options.commands.remove(x)
		return groups

	def custom_options(self, login):
		try:
			return Context.g_module.host_options[login]
		except (AttributeError, KeyError):
			return {}

	def recurse(self, *k, **kw):
		self.env.RSYNC = getattr(Context.g_module, 'rsync', 'rsync -a --chmod=u+rwx')
		self.env.SSH = getattr(Context.g_module, 'ssh', 'ssh')
		try:
			self.env.WAF = getattr(Context.g_module, 'waf')
		except AttributeError:
			try:
				os.stat('waf')
			except KeyError:
				self.fatal('Put a waf file in the directory (./waf-light --tools=remote)')
			else:
				self.env.WAF = './waf'

		groups = self.extract_groups_of_builds()
		for k, v in groups.items():
			task = self(rule=rsync_and_ssh, always=True)
			task.env.login = self.variant_to_host(k)

			task.env.commands = []
			for opt, value in v.items():
				task.env.commands += value
			task.env.variant = task.env.commands[0].partition('_')[2]
			for opt, value in self.custom_options(k):
				task.env[opt] = value
		self.jobs = len(groups)
		self.synchronized = (self.jobs > 1)

	def make_mkdir_command(self, task):
		return Utils.subst_vars('${SSH} ${login} "rm -fr ${remote_dir} && mkdir -p ${remote_dir}"', task.env)

	def make_send_command(self, task):
		return Utils.subst_vars('${RSYNC} -e "${SSH}" ${local_dir} ${login}:${remote_dir}', task.env)

	def make_exec_command(self, task):
		txt = '''${SSH} ${login} "cd ${remote_dir} && ${WAF} ${commands}"'''
		return Utils.subst_vars(txt, task.env)

	def make_save_command(self, task):
		return Utils.subst_vars('${RSYNC} -e "${SSH}" ${login}:${remote_dir_variant} ${build_dir}', task.env)

def rsync_and_ssh(task):

	# remove a warning
	task.uid_ = id(task)

	bld = task.generator.bld

	task.env.user, _, _ = task.env.login.partition('@')
	task.env.hdir = Utils.to_hex(Utils.h_list((task.generator.path.abspath(), task.env.variant)))
	task.env.remote_dir = '~%s/wafremote/%s' % (task.env.user, task.env.hdir)
	task.env.local_dir = bld.srcnode.abspath() + '/'

	task.env.remote_dir_variant = '%s/%s/%s' % (task.env.remote_dir, Context.g_module.out, task.env.variant)
	task.env.build_dir = bld.bldnode.abspath()

	ret = task.exec_command(bld.make_mkdir_command(task))
	if ret:
		return ret
	ret = task.exec_command(bld.make_send_command(task))
	if ret:
		return ret
	ret = task.exec_command(bld.make_exec_command(task))
	if ret:
		return ret
	ret = task.exec_command(bld.make_save_command(task))
	if ret:
		return ret

