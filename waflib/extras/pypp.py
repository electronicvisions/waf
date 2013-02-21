#! /usr/bin/env python
# encoding: UTF-8
# Thomas Nagy 2008-2010 (ita)

"""

Py++ support

Variables passed to bld():
* headers -- headers to process
* script -- script to run
* outdir -- folder to place generated files

ported from waf 1.5 (incomplete)
"""

import os, sys
from waflib import Task, Utils, Node, Logs, Context, Errors
from waflib.TaskGen import feature, after_method, before_method
from waflib.Tools import c_preproc
from pprint import pprint
from waflib.Tools.ccroot import to_incnodes, link_task

try:
    from waflib.extras import symwaf2ic
    base_dir = symwaf2ic.get_toplevel_path()
except ImportError:
    base_dir = os.environ["SYMAP2IC_PATH"]
    base_dir = os.path.join(base_dir, 'components')

module_folders = [ os.path.abspath(p) for p in [
    os.path.join(base_dir, 'pyplusplus'),
    os.path.join(base_dir, 'pygccxml'),
    ]]

for path in module_folders:
    sys.path.insert(0, path)

# See http://docs.waf.googlecode.com/git/book_17/single.html at
# 10.4.2. A compiler producing source files with names unknown in advance
class pyplusplus(Task.Task):
    vars  = ['PYTHON']
    quiet = True
    color = 'PINK'
    ext_out = ['.hpp', '.cpp']

    def run(self):
        bld = self.generator.bld

        args = self.env.PYTHON + [self.inputs[0].abspath()]
        args += ["-o", self.output_dir.abspath() ]
        args += ["-M", self.module ]
        args += self.colon("INC_ST", "INCLUDES" )
        args += self.colon("DEF_ST", "DEFINES" )
        args += [ x.abspath() for x in self.inputs[1:] ]

        old_nodes = self.output_dir.ant_glob('*.cpp', quiet=True)

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(module_folders + env.get("PYHTONPATH", "").split(os.pathsep))

        try:
            bld.cmd_and_log(args, cwd = bld.variant_dir, env=env, output=Context.BOTH, quiet=Context.BOTH)
        except Errors.WafError as e:
            try:
                print e.stdout
                print e.stderr
                return e.returncode
            except AttributeError:
                raise e

        self.outputs = self.output_dir.ant_glob('*.cpp', quiet=True)
        self.generator.bld.raw_deps[self.uid()] = [self.signature()] + self.outputs
        self.add_cxx_tasks(self.outputs)

    def __str__(self):
        "string to display to the user"
        env = self.env
        src_str = ' '.join([a.nice_path(env) for a in self.inputs])
        mod = self.module
        return '%s: %s -> module %s\n' % (self.__class__.__name__.replace('_task', ''), src_str, mod)


    def uid(self):
        try:
            return self.uid_
        except AttributeError:
            # this is not a real hot zone, but we want to avoid surprises here
            m = Utils.md5()
            up = m.update
            up(self.__class__.__name__.encode())
            up(self.output_dir.abspath().encode())
            up(self.module.encode())
            for x in self.inputs + self.outputs:
                up(x.abspath().encode())
            self.uid_ = m.digest()
            return self.uid_

    def scan(task):
        """
            Modified from c_preproc, to scan all input nodes except the first one
        """
        try:
            incn = task.generator.includes_nodes
        except AttributeError:
            raise Errors.WafError('%r is missing a feature such as "c", "cxx" or "includes": ' % task.generator)

        nodepaths = [x for x in incn if x.is_child_of(x.ctx.srcnode) or x.is_child_of(x.ctx.bldnode)]

        nodes = []
        names = []
        for input in task.inputs[1:]:
            tmp = c_preproc.c_parser(nodepaths)
            tmp.start(input, task.env)
            Logs.debug('deps: deps for %r: %r; unresolved %r' % (task.inputs, tmp.nodes, tmp.names))
            nodes += tmp.nodes
            names += tmp.names
        return nodes, names


    def add_cxx_tasks(self, lst):
        self.more_tasks = getattr(self, "more_tasks", [])
        for node in lst:
            if not node.name.endswith('.cpp'):
                continue
            tsk = self.generator.create_compiled_task('cxx', node)
            tsk.env.append_value('INCPATHS', [node.parent.abspath()])
            self.more_tasks.append(tsk)

            self.helper_task.set_run_after(tsk)
            self.helper_task.inputs.extend(tsk.outputs)

    def getEnviron(self):
        # Add python path to env
        seen = set()
        env = os.environ.copy()
        pyhtonpath = modules_folders + env.get("PYTHONPATH", "").split(os.pathsep)
        pythonpath = [ x for x in pythonpath if x not in seen and not seen.add(x)]
        env["PYTHONPATH"] = os.pathsep.join(pyhtonpath)

    def runnable_status(self):
        ret = super(pyplusplus, self).runnable_status()
        if ret == Task.SKIP_ME:

            lst = self.generator.bld.raw_deps[self.uid()]
            if lst[0] != self.signature():
                return Task.RUN_ME

            nodes = lst[1:]
            for x in nodes:
                try:
                    os.stat(x.abspath())
                except:
                    return Task.RUN_ME

            nodes = lst[1:]
            self.set_outputs(nodes)
            self.add_cxx_tasks(nodes)

        return ret

class merge_cxx_objects(Task.Task):
    vars  = ['CXX']
    quiet = True
    color = 'PINK'
    ext_out = ['.o']
    after = ["cxx", "pyplusplus"]
    before = ["cxxshlib", "cxxstlib"]
    run_str = 'ld -r ${CXXLNK_SRC_F}${SRC} ${CXXLNK_TGT_F}${TGT[0].abspath()}'
#    run_str = '${LINK_CXX} -Wl,-r -o ${TGT[0].abspath()} ${SRC}'


@feature('pypp')
@before_method('process_source')
def fix_pyplusplus_compiler(self):
    self.env.detach()
    self.env.CXX = self.env.CXX_PYPP

    if not getattr(self, 'script', None):
        self.generator.bld.fatal('script file not set')
    self.module = getattr(self, 'module', self.target)
    out_dir = getattr(self, 'output_dir', self.module)
    out_dir = self.path.get_bld().make_node(out_dir)
    out_dir.mkdir()
    self.pypp_output_dir = out_dir

    self.pypp_helper_task = self.create_compiled_task(
            'merge_cxx_objects', self.pypp_output_dir)
    self.pypp_helper_task.inputs = []

@feature('pypp')
@after_method('process_use', 'apply_incpaths')
def create_pyplusplus(self):
    headers = self.to_list(getattr(self, 'headers', []))

    input_nodes = self.to_nodes( [self.script] + headers )

    defines = self.to_list(getattr(self, 'gen_defines', []))
    includes = to_incnodes(self, getattr(self, 'includes', []))
    t = self.create_task('pyplusplus', input_nodes)
    t.env.OUTPUT_DIR = self.pypp_output_dir.abspath()
    t.env.DEF_ST = ["-D"]
    t.env.INC_ST = ["-I"]
    t.env.DEFINES = defines
    t.env.INCLUDES = [ inc.abspath() for inc in includes ]
    t.module = self.module
    t.output_dir = self.pypp_output_dir
    t.helper_task = self.pypp_helper_task


not_found_msg = """Please use the patched pygccxml and pyplusplus provided at:
git@gitviz.kip.uni-heidelberg.de:pygccxml.git
git@gitviz.kip.uni-heidelberg.de:pyplusplus.git

Use 'python -v waf configure' to find see where the loaded packageses are located
"""


exec_configure = True
def configure(conf):
    global exec_configure
    if exec_configure:
        exec_configure = False

        conf.load('gxx')
        conf.load('python')
        conf.load('boost')
        conf.check_python_version(minver=(2,5))
        conf.check_python_headers()

        try:
            import pyplusplus
            import pygccxml
        except ImportError:
            conf.fatal(not_found_msg)

        try:
            if not pyplusplus.symap2ic_patched:
                raise AttributeError
            if not pygccxml.symap2ic_patched:
                raise AttributeError
        except AttributeError:
            conf.fatal(not_found_msg)

        # ECM: We would have to check if compiled boost library was compiled
        # with the current compiler. => This is not possible for non-debug builds.
        # Workaround:
        #  - if CXX matches system's g++, accept
        #    (as 4.7-built boost works with 4.7, same holds for 4.6)
        #  - if user provides PYPP_CXX, don't check (we trust the user ;))
        #    (otherwise see first comment...)

        if conf.environ.get('CXX_PYPP', None) is None:
            old_CC_VERSION = conf.env.CC_VERSION
            conf.env.stash()
            cc = conf.cmd_to_list(conf.find_program('g++'))
            conf.get_cc_version(cc, gcc=True)
            if old_CC_VERSION != conf.env.CC_VERSION:
                msg = "System compiler (%s) doesn't match CXX (%s)." % ('.'.join(conf.env.CC_VERSION), '.'.join(old_CC_VERSION))
                msg += "\nThis might cause problems (see gcc bugzilla #53455)."
                msg += "\nUse CXX_PYPP=g++-4.X to specify the boost library compiler."
                msg += "\nIf your boost library matches the rest of the OS, CXX_PYPP=g++ should suffice."
                raise Errors.WafError, msg
            conf.env.revert()

        conf.env.CXX_PYPP = os.environ.get('CXX_PYPP', conf.env.CXX)
