#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2006-2018 (ita)
# Rafaël Kooi, 2023 (RA-Kooi)

"""
This tool helps with finding Qt5 and Qt6 tools and libraries,
and also provides syntactic sugar for using Qt5 and Qt6 tools.

The following snippet illustrates the tool usage::

	def options(opt):
		opt.load('compiler_cxx qt5')

	def configure(conf):
		conf.load('compiler_cxx qt5')

	def build(bld):
		bld(
			features = 'qt5 cxx cxxprogram',
			uselib   = 'QT5CORE QT5GUI QT5OPENGL QT5SVG',
			source   = 'main.cpp textures.qrc aboutDialog.ui',
			target   = 'window',
		)

Alternatively the following snippet illustrates Qt6 tool usage::

    def options(opt):
        opt.load('compiler_cxx qt5')

    def configure(conf):
        conf.want_qt6 = True
        conf.load('compiler_cxx qt5')

    def build(bld):
        bld(
            features = 'qt6 cxx cxxprogram',
            uselib   = 'QT6CORE QT6GUI QT6OPENGL QT6SVG',
            source   = 'main.cpp textures.qrc aboutDialog.ui',
            target   = 'window',
        )

Here, the UI description and resource files will be processed
to generate code.

Usage
=====

Load the "qt5" tool.

You also need to edit your sources accordingly:

- the normal way of doing things is to have your C++ files
  include the .moc file.
  This is regarded as the best practice (and provides much faster
  compilations).
  It also implies that the include paths have beenset properly.

- to have the include paths added automatically, use the following::

     from waflib.TaskGen import feature, before_method, after_method
     @feature('cxx')
     @after_method('process_source')
     @before_method('apply_incpaths')
     def add_includes_paths(self):
        incs = set(self.to_list(getattr(self, 'includes', '')))
        for x in self.compiled_tasks:
            incs.add(x.inputs[0].parent.path_from(self.path))
        self.includes = sorted(incs)

Note: another tool provides Qt processing that does not require
.moc includes, see 'playground/slow_qt/'.

A few options (--qt{dir,bin,...}) and environment variables
(QT5_{ROOT,DIR,MOC,UIC,XCOMPILE}) allow finer tuning of the tool,
tool path selection, etc; please read the source for more info.
For Qt6 replace the QT5_ prefix with QT6_.

The detection uses pkg-config on Linux by default. The list of
libraries to be requested to pkg-config is formulated by scanning
in the QTLIBS directory (that can be passed via --qtlibs or by
setting the environment variable QT5_LIBDIR or QT6_LIBDIR otherwise is
derived by querying qmake for QT_INSTALL_LIBS directory) for
shared/static libraries present.
Alternatively the list of libraries to be requested via pkg-config
can be set using the qt5_vars attribute, ie:

      conf.qt5_vars = ['Qt5Core', 'Qt5Gui', 'Qt5Widgets', 'Qt5Test'];

For Qt6 use the qt6_vars attribute.

This can speed up configuration phase if needed libraries are
known beforehand, can improve detection on systems with a
sparse QT5/Qt6 libraries installation (ie. NIX) and can improve
detection of some header-only Qt modules (ie. Qt5UiPlugin).

To force static library detection use:
QT5_XCOMPILE=1 QT5_FORCE_STATIC=1 waf configure

To use Qt6 set the want_qt6 attribute, ie:

    conf.want_qt6 = True;
"""

from __future__ import with_statement

try:
	from xml.sax import make_parser
	from xml.sax.handler import ContentHandler
except ImportError:
	has_xml = False
	ContentHandler = object
else:
	has_xml = True

import os, sys, re
from waflib.Tools import cxx
from waflib import Build, Task, Utils, Options, Errors, Context
from waflib.TaskGen import feature, after_method, extension, before_method
from waflib.Configure import conf
from waflib import Logs

MOC_H = ['.h', '.hpp', '.hxx', '.hh']
"""
File extensions associated to .moc files
"""

EXT_RCC = ['.qrc']
"""
File extension for the resource (.qrc) files
"""

EXT_UI  = ['.ui']
"""
File extension for the user interface (.ui) files
"""

EXT_QT5 = ['.cpp', '.cc', '.cxx', '.C']
"""
File extensions of C++ files that may require a .moc processing
"""

class qxx(Task.classes['cxx']):
	"""
	Each C++ file can have zero or several .moc files to create.
	They are known only when the files are scanned (preprocessor)
	To avoid scanning the c++ files each time (parsing C/C++), the results
	are retrieved from the task cache (bld.node_deps/bld.raw_deps).
	The moc tasks are also created *dynamically* during the build.
	"""

	def __init__(self, *k, **kw):
		Task.Task.__init__(self, *k, **kw)
		self.moc_done = 0

	def runnable_status(self):
		"""
		Compute the task signature to make sure the scanner was executed. Create the
		moc tasks by using :py:meth:`waflib.Tools.qt5.qxx.add_moc_tasks` (if necessary),
		then postpone the task execution (there is no need to recompute the task signature).
		"""
		if self.moc_done:
			return Task.Task.runnable_status(self)
		else:
			for t in self.run_after:
				if not t.hasrun:
					return Task.ASK_LATER
			self.add_moc_tasks()
			return Task.Task.runnable_status(self)

	def create_moc_task(self, h_node, m_node):
		"""
		If several libraries use the same classes, it is possible that moc will run several times (Issue 1318)
		It is not possible to change the file names, but we can assume that the moc transformation will be identical,
		and the moc tasks can be shared in a global cache.
		"""
		try:
			moc_cache = self.generator.bld.moc_cache
		except AttributeError:
			moc_cache = self.generator.bld.moc_cache = {}

		try:
			return moc_cache[h_node]
		except KeyError:
			tsk = moc_cache[h_node] = Task.classes['moc'](env=self.env, generator=self.generator)
			tsk.set_inputs(h_node)
			tsk.set_outputs(m_node)
			tsk.env.append_unique('MOC_FLAGS', '-i')

			if self.generator:
				self.generator.tasks.append(tsk)

			# direct injection in the build phase (safe because called from the main thread)
			gen = self.generator.bld.producer
			gen.outstanding.append(tsk)
			gen.total += 1

			return tsk

		else:
			# remove the signature, it must be recomputed with the moc task
			delattr(self, 'cache_sig')

	def add_moc_tasks(self):
		"""
		Creates moc tasks by looking in the list of file dependencies ``bld.raw_deps[self.uid()]``
		"""
		node = self.inputs[0]
		bld = self.generator.bld

		# skip on uninstall due to generated files
		if bld.is_install == Build.UNINSTALL:
			return

		try:
			# compute the signature once to know if there is a moc file to create
			self.signature()
		except KeyError:
			# the moc file may be referenced somewhere else
			pass
		else:
			# remove the signature, it must be recomputed with the moc task
			delattr(self, 'cache_sig')

		include_nodes = [node.parent] + self.generator.includes_nodes

		moctasks = []
		mocfiles = set()
		for d in bld.raw_deps.get(self.uid(), []):
			if not d.endswith('.moc'):
				continue

			# process that base.moc only once
			if d in mocfiles:
				continue
			mocfiles.add(d)

			# find the source associated with the moc file
			h_node = None
			base2 = d[:-4]

			# foo.moc from foo.cpp
			prefix = node.name[:node.name.rfind('.')]
			if base2 == prefix:
				h_node = node
			else:
				# this deviates from the standard
				# if bar.cpp includes foo.moc, then assume it is from foo.h
				for x in include_nodes:
					for e in MOC_H:
						h_node = x.find_node(base2 + e)
						if h_node:
							break
					else:
						continue
					break
			if h_node:
				m_node = h_node.change_ext('.moc')
			else:
				raise Errors.WafError('No source found for %r which is a moc file' % d)

			# create the moc task
			task = self.create_moc_task(h_node, m_node)
			moctasks.append(task)

		# simple scheduler dependency: run the moc task before others
		self.run_after.update(set(moctasks))
		self.moc_done = 1

class trans_update(Task.Task):
	"""Updates a .ts files from a list of C++ files"""
	run_str = '${QT_LUPDATE} ${SRC} -ts ${TGT}'
	color   = 'BLUE'

class XMLHandler(ContentHandler):
	"""
	Parses ``.qrc`` files
	"""
	def __init__(self):
		ContentHandler.__init__(self)
		self.buf = []
		self.files = []
	def startElement(self, name, attrs):
		if name == 'file':
			self.buf = []
	def endElement(self, name):
		if name == 'file':
			self.files.append(str(''.join(self.buf)))
	def characters(self, cars):
		self.buf.append(cars)

@extension(*EXT_RCC)
def create_rcc_task(self, node):
	"Creates rcc and cxx tasks for ``.qrc`` files"
	rcnode = node.change_ext('_rc.%d.cpp' % self.idx)
	self.create_task('rcc', node, rcnode)
	cpptask = self.create_task('cxx', rcnode, rcnode.change_ext('.o'))
	try:
		self.compiled_tasks.append(cpptask)
	except AttributeError:
		self.compiled_tasks = [cpptask]
	return cpptask

@extension(*EXT_UI)
def create_uic_task(self, node):
	"Create uic tasks for user interface ``.ui`` definition files"

	"""
	If UIC file is used in more than one bld, we would have a conflict in parallel execution
	It is not possible to change the file names (like .self.idx. as for objects) as they have
	to be referenced by the source file, but we can assume that the transformation will be identical
	and the tasks can be shared in a global cache.
	"""
	try:
		uic_cache = self.bld.uic_cache
	except AttributeError:
		uic_cache = self.bld.uic_cache = {}

	if node not in uic_cache:
		uictask = uic_cache[node] = self.create_task('ui5', node)
		uictask.outputs = [node.parent.find_or_declare(self.env.ui_PATTERN % node.name[:-3])]

@extension('.ts')
def add_lang(self, node):
	"""Adds all the .ts file into ``self.lang``"""
	self.lang = self.to_list(getattr(self, 'lang', [])) + [node]

@feature('qt5', 'qt6')
@before_method('process_source')
def process_mocs(self):
	"""
	Processes MOC files included in headers::

		def build(bld):
			bld.program(features='qt5', source='main.cpp', target='app', use='QT5CORE', moc='foo.h')

	The build will run moc on foo.h to create moc_foo.n.cpp. The number in the file name
	is provided to avoid name clashes when the same headers are used by several targets.
	"""
	lst = self.to_nodes(getattr(self, 'moc', []))
	self.source = self.to_list(getattr(self, 'source', []))
	for x in lst:
		prefix = x.name[:x.name.rfind('.')] # foo.h -> foo
		moc_target = 'moc_%s.%d.cpp' % (prefix, self.idx)
		moc_node = x.parent.find_or_declare(moc_target)
		self.source.append(moc_node)

		self.create_task('moc', x, moc_node)

@feature('qt5', 'qt6')
@after_method('apply_link')
def apply_qt5(self):
	"""
	Adds MOC_FLAGS which may be necessary for moc::

		def build(bld):
			bld.program(features='qt5', source='main.cpp', target='app', use='QT5CORE')

	The additional parameters are:

	:param lang: list of translation files (\\*.ts) to process
	:type lang: list of :py:class:`waflib.Node.Node` or string without the .ts extension
	:param update: whether to process the C++ files to update the \\*.ts files (use **waf --translate**)
	:type update: bool
	:param langname: if given, transform the \\*.ts files into a .qrc files to include in the binary file
	:type langname: :py:class:`waflib.Node.Node` or string without the .qrc extension
	"""
	if getattr(self, 'lang', None):
		qmtasks = []
		for x in self.to_list(self.lang):
			if isinstance(x, str):
				x = self.path.find_resource(x + '.ts')
			qmtasks.append(self.create_task('ts2qm', x, x.change_ext('.%d.qm' % self.idx)))

		if getattr(self, 'update', None) and Options.options.trans_qt5:
			cxxnodes = [a.inputs[0] for a in self.compiled_tasks] + [
				a.inputs[0] for a in self.tasks if a.inputs and a.inputs[0].name.endswith('.ui')]
			for x in qmtasks:
				self.create_task('trans_update', cxxnodes, x.inputs)

		if getattr(self, 'langname', None):
			qmnodes = [x.outputs[0] for x in qmtasks]
			rcnode = self.langname
			if isinstance(rcnode, str):
				rcnode = self.path.find_or_declare(rcnode + ('.%d.qrc' % self.idx))
			t = self.create_task('qm2rcc', qmnodes, rcnode)
			k = create_rcc_task(self, t.outputs[0])
			self.link_task.inputs.append(k.outputs[0])

	lst = []
	for flag in self.to_list(self.env.CXXFLAGS):
		if len(flag) < 2:
			continue
		f = flag[0:2]
		if f in ('-D', '-I', '/D', '/I'):
			if (f[0] == '/'):
				lst.append('-' + flag[1:])
			else:
				lst.append(flag)
	self.env.append_value('MOC_FLAGS', lst)

@extension(*EXT_QT5)
def cxx_hook(self, node):
	"""
	Re-maps C++ file extensions to the :py:class:`waflib.Tools.qt5.qxx` task.
	"""
	return self.create_compiled_task('qxx', node)

class rcc(Task.Task):
	"""
	Processes ``.qrc`` files
	"""
	color   = 'BLUE'
	run_str = '${QT_RCC} -name ${tsk.rcname()} ${SRC[0].abspath()} ${RCC_ST} -o ${TGT}'
	ext_out = ['.h']

	def rcname(self):
		return os.path.splitext(self.inputs[0].name)[0]

	def scan(self):
		"""Parse the *.qrc* files"""
		if not has_xml:
			Logs.error('No xml.sax support was found, rcc dependencies will be incomplete!')
			return ([], [])

		parser = make_parser()
		curHandler = XMLHandler()
		parser.setContentHandler(curHandler)
		with open(self.inputs[0].abspath(), 'r') as f:
			parser.parse(f)

		nodes = []
		names = []
		root = self.inputs[0].parent
		for x in curHandler.files:
			nd = root.find_resource(x)
			if nd:
				nodes.append(nd)
			else:
				names.append(x)
		return (nodes, names)

	def quote_flag(self, x):
		"""
		Override Task.quote_flag. QT parses the argument files
		differently than cl.exe and link.exe

		:param x: flag
		:type x: string
		:return: quoted flag
		:rtype: string
		"""
		return x


class moc(Task.Task):
	"""
	Creates ``.moc`` files
	"""
	color   = 'BLUE'
	run_str = '${QT_MOC} ${MOC_FLAGS} ${MOCCPPPATH_ST:INCPATHS} ${MOCDEFINES_ST:DEFINES} ${SRC} ${MOC_ST} ${TGT}'

	def quote_flag(self, x):
		"""
		Override Task.quote_flag. QT parses the argument files
		differently than cl.exe and link.exe

		:param x: flag
		:type x: string
		:return: quoted flag
		:rtype: string
		"""
		return x


class ui5(Task.Task):
	"""
	Processes ``.ui`` files
	"""
	color   = 'BLUE'
	run_str = '${QT_UIC} ${SRC} -o ${TGT}'
	ext_out = ['.h']

class ts2qm(Task.Task):
	"""
	Generates ``.qm`` files from ``.ts`` files
	"""
	color   = 'BLUE'
	run_str = '${QT_LRELEASE} ${QT_LRELEASE_FLAGS} ${SRC} -qm ${TGT}'

class qm2rcc(Task.Task):
	"""
	Generates ``.qrc`` files from ``.qm`` files
	"""
	color = 'BLUE'
	after = 'ts2qm'
	def run(self):
		"""Create a qrc file including the inputs"""
		txt = '\n'.join(['<file>%s</file>' % k.path_from(self.outputs[0].parent) for k in self.inputs])
		code = '<!DOCTYPE RCC><RCC version="1.0">\n<qresource>\n%s\n</qresource>\n</RCC>' % txt
		self.outputs[0].write(code)

def configure(self):
	"""
	Besides the configuration options, the environment variable QT5_ROOT may be used
	to give the location of the qt5 libraries (absolute path).

	The detection uses the program ``pkg-config`` through :py:func:`waflib.Tools.config_c.check_cfg`
	"""
	if 'COMPILER_CXX' not in self.env:
		self.fatal('No CXX compiler defined: did you forget to configure compiler_cxx first?')

	self.want_qt6 = getattr(self, 'want_qt6', False)

	if self.want_qt6:
		self.qt_vars = Utils.to_list(getattr(self, 'qt6_vars', []))
	else:
		self.qt_vars = Utils.to_list(getattr(self, 'qt5_vars', []))

	self.find_qt5_binaries()
	self.set_qt5_libs_dir()
	self.set_qt5_libs_to_check()
	self.set_qt5_defines()
	self.find_qt5_libraries()
	self.add_qt5_rpath()
	self.simplify_qt5_libs()

	# warn about this during the configuration too
	if not has_xml:
		Logs.error('No xml.sax support was found, rcc dependencies will be incomplete!')

	feature = 'qt6' if self.want_qt6 else 'qt5'

	# Qt5 may be compiled with '-reduce-relocations' which requires dependent programs to have -fPIE or -fPIC?
	frag = '#include <QMap>\nint main(int argc, char **argv) {QMap<int,int> m;return m.keys().size();}\n'
	uses = 'QT6CORE' if self.want_qt6 else 'QT5CORE'

	# Qt6 requires C++17 (https://www.qt.io/blog/qt-6.0-released)
	flag_list = []
	if self.env.CXX_NAME == 'msvc':
		stdflag = '/std:c++17' if self.want_qt6 else '/std:c++11'
		flag_list = [[], ['/Zc:__cplusplus', '/permissive-', stdflag]]
	else:
		stdflag = '-std=c++17' if self.want_qt6 else '-std=c++11'
		flag_list = [[], '-fPIE', '-fPIC', stdflag, [stdflag, '-fPIE'], [stdflag, '-fPIC']]
	for flag in flag_list:
		msg = 'See if Qt files compile '
		if flag:
			msg += 'with %s' % flag
		try:
			self.check(features=feature + ' cxx', use=uses, uselib_store=feature, cxxflags=flag, fragment=frag, msg=msg)
		except self.errors.ConfigurationError:
			pass
		else:
			break
	else:
		self.fatal('Could not build a simple Qt application')

	# FreeBSD does not add /usr/local/lib and the pkg-config files do not provide it either :-/
	if Utils.unversioned_sys_platform() == 'freebsd':
		frag = '#include <QMap>\nint main(int argc, char **argv) {QMap<int,int> m;return m.keys().size();}\n'
		try:
			self.check(features=feature + ' cxx cxxprogram', use=uses, fragment=frag, msg='Can we link Qt programs on FreeBSD directly?')
		except self.errors.ConfigurationError:
			self.check(features=feature + ' cxx cxxprogram', use=uses, uselib_store=feature, libpath='/usr/local/lib', fragment=frag, msg='Is /usr/local/lib required?')

@conf
def find_qt5_binaries(self):
	"""
	Detects Qt programs such as qmake, moc, uic, lrelease
	"""
	env = self.env
	opt = Options.options

	qtdir = getattr(opt, 'qtdir', '')
	qtbin = getattr(opt, 'qtbin', '')
	qt_ver = '6' if self.want_qt6 else '5'

	paths = []

	if qtdir:
		qtbin = os.path.join(qtdir, 'bin')

	# the qt directory has been given from QT5_ROOT - deduce the qt binary path
	if not qtdir:
		qtdir = self.environ.get('QT' + qt_ver + '_ROOT', '')
		qtbin = self.environ.get('QT' + qt_ver + '_BIN') or os.path.join(qtdir, 'bin')

	if qtbin:
		paths = [qtbin]

	# no qtdir, look in the path and in /usr/local/Trolltech
	if not qtdir:
		paths = self.environ.get('PATH', '').split(os.pathsep)
		paths.extend([
			'/usr/share/qt' + qt_ver + '/bin',
			'/usr/local/lib/qt' + qt_ver + '/bin'])

		try:
			lst = Utils.listdir('/usr/local/Trolltech/')
		except OSError:
			pass
		else:
			if lst:
				lst.sort()
				lst.reverse()

				# keep the highest version
				qtdir = '/usr/local/Trolltech/%s/' % lst[0]
				qtbin = os.path.join(qtdir, 'bin')
				paths.append(qtbin)

	# at the end, try to find qmake in the paths given
	# keep the one with the highest version
	cand = None
	prev_ver = ['0', '0', '0']
	qmake_vars = ['qmake-qt' + qt_ver, 'qmake' + qt_ver, 'qmake']

	for qmk in qmake_vars:
		try:
			qmake = self.find_program(qmk, path_list=paths)
		except self.errors.ConfigurationError:
			pass
		else:
			try:
				version = self.cmd_and_log(qmake + ['-query', 'QT_VERSION']).strip()
			except self.errors.WafError:
				pass
			else:
				if version:
					new_ver = version.split('.')
					if new_ver[0] == qt_ver and new_ver > prev_ver:
						cand = qmake
						prev_ver = new_ver

	# qmake could not be found easily, rely on qtchooser
	if not cand:
		try:
			self.find_program('qtchooser')
		except self.errors.ConfigurationError:
			pass
		else:
			cmd = self.env.QTCHOOSER + ['-qt=' + qt_ver, '-run-tool=qmake']
			try:
				version = self.cmd_and_log(cmd + ['-query', 'QT_VERSION'])
			except self.errors.WafError:
				pass
			else:
				cand = cmd

	if cand:
		self.env.QMAKE = cand
	else:
		self.fatal('Could not find qmake for qt' + qt_ver)

	# Once we have qmake, we want to query qmake for the paths where we want to look for tools instead
	paths = []

	self.env.QT_HOST_BINS = qtbin = self.cmd_and_log(self.env.QMAKE + ['-query', 'QT_HOST_BINS']).strip()
	paths.append(qtbin)

	if self.want_qt6:
		self.env.QT_HOST_LIBEXECS = self.cmd_and_log(self.env.QMAKE + ['-query', 'QT_HOST_LIBEXECS']).strip()
		paths.append(self.env.QT_HOST_LIBEXECS)

	def find_bin(lst, var):
		if var in env:
			return
		for f in lst:
			try:
				ret = self.find_program(f, path_list=paths)
			except self.errors.ConfigurationError:
				pass
			else:
				env[var]=ret
				break

	find_bin(['uic-qt' + qt_ver, 'uic'], 'QT_UIC')
	if not env.QT_UIC:
		self.fatal('cannot find the uic compiler for qt' + qt_ver)

	self.start_msg('Checking for uic version')
	uicver = self.cmd_and_log(env.QT_UIC + ['-version'], output=Context.BOTH)
	uicver = ''.join(uicver).strip()
	uicver = uicver.replace('Qt User Interface Compiler ','').replace('User Interface Compiler for Qt', '')
	self.end_msg(uicver)
	if uicver.find(' 3.') != -1 or uicver.find(' 4.') != -1 or (self.want_qt6 and uicver.find(' 5.') != -1):
		if self.want_qt6:
			self.fatal('this uic compiler is for qt3 or qt4 or qt5, add uic for qt6 to your path')
		else:
			self.fatal('this uic compiler is for qt3 or qt4, add uic for qt5 to your path')

	find_bin(['moc-qt' + qt_ver, 'moc'], 'QT_MOC')
	find_bin(['rcc-qt' + qt_ver, 'rcc'], 'QT_RCC')
	find_bin(['lrelease-qt' + qt_ver, 'lrelease'], 'QT_LRELEASE')
	find_bin(['lupdate-qt' + qt_ver, 'lupdate'], 'QT_LUPDATE')

	env.UIC_ST = '%s -o %s'
	env.MOC_ST = '-o'
	env.ui_PATTERN = 'ui_%s.h'
	env.QT_LRELEASE_FLAGS = ['-silent']
	env.MOCCPPPATH_ST = '-I%s'
	env.MOCDEFINES_ST = '-D%s'

@conf
def set_qt5_libs_dir(self):
	env = self.env
	qt_ver = '6' if self.want_qt6 else '5'

	qtlibs = getattr(Options.options, 'qtlibs', None) or self.environ.get('QT' + qt_ver + '_LIBDIR')

	if not qtlibs:
		try:
			qtlibs = self.cmd_and_log(env.QMAKE + ['-query', 'QT_INSTALL_LIBS']).strip()
		except Errors.WafError:
			qtdir = self.cmd_and_log(env.QMAKE + ['-query', 'QT_INSTALL_PREFIX']).strip()
			qtlibs = os.path.join(qtdir, 'lib')

	self.msg('Found the Qt' + qt_ver + ' library path', qtlibs)

	env.QTLIBS = qtlibs

@conf
def find_single_qt5_lib(self, name, uselib, qtlibs, qtincludes, force_static):
	env = self.env
	qt_ver = '6' if self.want_qt6 else '5'

	if force_static:
		exts = ('.a', '.lib')
		prefix = 'STLIB'
	else:
		exts = ('.so', '.lib')
		prefix = 'LIB'

	def lib_names():
		for x in exts:
			for k in ('', qt_ver) if Utils.is_win32 else ['']:
				for p in ('lib', ''):
					yield (p, name, k, x)

	for tup in lib_names():
		k = ''.join(tup)
		path = os.path.join(qtlibs, k)
		if os.path.exists(path):
			if env.DEST_OS == 'win32':
				libval = ''.join(tup[:-1])
			else:
				libval = name
			env.append_unique(prefix + '_' + uselib, libval)
			env.append_unique('%sPATH_%s' % (prefix, uselib), qtlibs)
			env.append_unique('INCLUDES_' + uselib, qtincludes)
			env.append_unique('INCLUDES_' + uselib, os.path.join(qtincludes, name.replace('Qt' + qt_ver, 'Qt')))
			return k
	return False

@conf
def find_qt5_libraries(self):
	env = self.env
	qt_ver = '6' if self.want_qt6 else '5'

	qtincludes =  self.environ.get('QT' + qt_ver + '_INCLUDES') or self.cmd_and_log(env.QMAKE + ['-query', 'QT_INSTALL_HEADERS']).strip()
	force_static = self.environ.get('QT' + qt_ver + '_FORCE_STATIC')

	try:
		if self.environ.get('QT' + qt_ver + '_XCOMPILE'):
			self.fatal('QT' + qt_ver + '_XCOMPILE Disables pkg-config detection')
		self.check_cfg(atleast_pkgconfig_version='0.1')
	except self.errors.ConfigurationError:
		for i in self.qt_vars:
			uselib = i.upper()
			if Utils.unversioned_sys_platform() == 'darwin':
				# Since at least qt 4.7.3 each library locates in separate directory
				fwk = i.replace('Qt' + qt_ver, 'Qt')
				frameworkName = fwk + '.framework'

				qtDynamicLib = os.path.join(env.QTLIBS, frameworkName, fwk)
				if os.path.exists(qtDynamicLib):
					env.append_unique('FRAMEWORK_' + uselib, fwk)
					env.append_unique('FRAMEWORKPATH_' + uselib, env.QTLIBS)
					self.msg('Checking for %s' % i, qtDynamicLib, 'GREEN')
				else:
					self.msg('Checking for %s' % i, False, 'YELLOW')
				env.append_unique('INCLUDES_' + uselib, os.path.join(env.QTLIBS, frameworkName, 'Headers'))
			else:
				ret = self.find_single_qt5_lib(i, uselib, env.QTLIBS, qtincludes, force_static)
				if not force_static and not ret:
					ret = self.find_single_qt5_lib(i, uselib, env.QTLIBS, qtincludes, True)
				self.msg('Checking for %s' % i, ret, 'GREEN' if ret else 'YELLOW')
	else:
		path = '%s:%s:%s/pkgconfig:/usr/lib/qt%s/lib/pkgconfig:/opt/qt%s/lib/pkgconfig:/usr/lib/qt%s/lib:/opt/qt%s/lib' % (
			self.environ.get('PKG_CONFIG_PATH', ''), env.QTLIBS, env.QTLIBS, qt_ver, qt_ver, qt_ver, qt_ver)
		for i in self.qt_vars:
			self.check_cfg(package=i, args='--cflags --libs', mandatory=False, force_static=force_static, pkg_config_path=path)

@conf
def simplify_qt5_libs(self):
	"""
	Since library paths make really long command-lines,
	and since everything depends on qtcore, remove the qtcore ones from qtgui, etc
	"""
	env = self.env
	def process_lib(vars_, coreval):
		for d in vars_:
			var = d.upper()
			if var == 'QTCORE':
				continue

			value = env['LIBPATH_'+var]
			if value:
				core = env[coreval]
				accu = []
				for lib in value:
					if lib in core:
						continue
					accu.append(lib)
				env['LIBPATH_'+var] = accu
	process_lib(self.qt_vars, 'LIBPATH_QTCORE')

@conf
def add_qt5_rpath(self):
	"""
	Defines rpath entries for Qt libraries
	"""
	env = self.env
	if getattr(Options.options, 'want_rpath', False):
		def process_rpath(vars_, coreval):
			for d in vars_:
				var = d.upper()
				value = env['LIBPATH_' + var]
				if value:
					core = env[coreval]
					accu = []
					for lib in value:
						if var != 'QTCORE':
							if lib in core:
								continue
						accu.append('-Wl,--rpath='+lib)
					env['RPATH_' + var] = accu
		process_rpath(self.qt_vars, 'LIBPATH_QTCORE')

@conf
def set_qt5_libs_to_check(self):
	qt_ver = '6' if self.want_qt6 else '5'

	if not self.qt_vars:
		dirlst = Utils.listdir(self.env.QTLIBS)

		pat = self.env.cxxshlib_PATTERN
		if Utils.is_win32:
			pat = pat.replace('.dll', '.lib')
		if self.environ.get('QT' + qt_ver + '_FORCE_STATIC'):
			pat = self.env.cxxstlib_PATTERN
		if Utils.unversioned_sys_platform() == 'darwin':
			pat = r"%s\.framework"

		# We only want to match Qt5 or Qt in the case of Qt5, in the case
		# of Qt6 we want to match Qt6 or Qt. This speeds up configuration
		# and reduces the chattiness of the configuration. Should also prevent
		# possible misconfiguration.
		if self.want_qt6:
			re_qt = re.compile(pat % 'Qt6?(?!\\d)(?P<name>\\w+)' + '$')
		else:
			re_qt = re.compile(pat % 'Qt5?(?!\\d)(?P<name>\\w+)' + '$')

		for x in sorted(dirlst):
			m = re_qt.match(x)
			if m:
				self.qt_vars.append("Qt%s%s" % (qt_ver, m.group('name')))
		if not self.qt_vars:
			self.fatal('cannot find any Qt%s library (%r)' % (qt_ver, self.env.QTLIBS))

	qtextralibs = getattr(Options.options, 'qtextralibs', None)
	if qtextralibs:
		self.qt_vars.extend(qtextralibs.split(','))

@conf
def set_qt5_defines(self):
	qt_ver = '6' if self.want_qt6 else '5'

	if sys.platform != 'win32':
		return

	for x in self.qt_vars:
		y=x.replace('Qt' + qt_ver, 'Qt')[2:].upper()
		self.env.append_unique('DEFINES_%s' % x.upper(), 'QT_%s_LIB' % y)

def options(opt):
	"""
	Command-line options
	"""
	opt.add_option('--want-rpath', action='store_true', default=False, dest='want_rpath', help='enable the rpath for qt libraries')
	for i in 'qtdir qtbin qtlibs'.split():
		opt.add_option('--'+i, type='string', default='', dest=i)

	opt.add_option('--translate', action='store_true', help='collect translation strings', dest='trans_qt5', default=False)
	opt.add_option('--qtextralibs', type='string', default='', dest='qtextralibs', help='additional qt libraries on the system to add to default ones, comma separated')

