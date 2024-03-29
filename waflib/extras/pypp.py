#! /usr/bin/env python
# encoding: UTF-8
# Thomas Nagy 2008-2010 (ita)

"""

Py++ support

Variables passed to bld():
* headers -- headers to process
* script -- script to run
* outdir -- folder to place generated files
* depends_on_files -- add files to manual dependencies

"""

import os
from waflib import Task, Utils, Logs, Context, Errors, Options
from waflib.TaskGen import feature, after_method, before_method
from waflib.Tools import c_preproc
from waflib.Configure import conf
from waflib.Tools.ccroot import link_task


try:
    from waflib.extras import symwaf2ic
    base_dir = symwaf2ic.get_toplevel_path()
except ImportError:
    base_dir = os.environ["SYMAP2IC_PATH"]
    base_dir = os.path.join(base_dir, 'components')
ENV_PYPP_MODULE_DEPENDENCIES = "PYPP_MODULE_DEPENDENCIES"
ENV_PYPP_MODULE_PATHS = "PYPP_MODULE_PATHS"
ENV_PYPP_USES = "PYPP_USES"


@conf
def pypp_add_module_path(cfg, *paths):
    cfg.env.append_unique(ENV_PYPP_MODULE_PATHS,
        [os.path.abspath(path) for path in paths])

@conf
def pypp_add_module_dependency(cfg, *modules):
    cfg.env.append_unique(ENV_PYPP_MODULE_DEPENDENCIES, modules)

@conf
def pypp_add_use(cfg, *uses):
    cfg.env.append_unique(ENV_PYPP_USES, uses)

def get_environ(conf):
    env = os.environ.copy()

    pp = []
    for path in conf.env[ENV_PYPP_MODULE_PATHS] + env.get('PYTHONPATH', '').split(os.pathsep):
        if path not in pp:
            pp.append(path)
    env["PYTHONPATH"] = os.pathsep.join(pp)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env

def get_manual_module_dependencies(ctx):
    env = get_environ(ctx)
    if hasattr(ctx, "pypp_module_dependencies_cache"):
        return ctx.pypp_module_dependencies_cache
    dependencies = []
    for module in ctx.env[ENV_PYPP_MODULE_DEPENDENCIES]:
        code = "\n".join([
                "import " + module,
                "import os.path",
                "print(os.path.dirname(" + module + ".__file__))",
        ])
        try:
            path = ctx.cmd_and_log(ctx.env.PYTHON + ['-c', code], env=env,
                    quiet=Context.BOTH)
            path = os.path.abspath(path.strip())
            assert os.path.isdir(path)
        except Errors.WafError as e:
            err = getattr(e, 'stdout', e.msg) + getattr(e, 'stderr', '')
            ctx.fatal("pypp: Manual dependency module '%s' could not be imported:" % module + err)
        except AssertionError:
            ctx.fatal("pypp: Could not find manual dependency module '%s'" % module)
        module_path = ctx.root.find_node(path)
        dependencies.extend(module_path.ant_glob("**/*.py"))
    ctx.pypp_module_dependencies_cache = dependencies
    return dependencies

def options(opt):
    """
    Provide options for gtest tests
    """
    grp = opt.add_option_group('Py++ Options')
    grp.add_option('--pypp-force', action='store_true', default=False,
                   help='Enforces to run Py++ scripts', dest='pypp_force')

def force_run():
    return getattr(Options.options, 'pypp_force', False)

# See http://docs.waf.googlecode.com/git/book_17/single.html at
# 10.4.2. A compiler producing source files with names unknown in advance
class pyplusplus(Task.Task):
    vars  = ['PYTHON']
    quiet = False
    color = 'PINK'
    ext_out = ['.hpp', '.cpp']

    def run(self):
        bld = self.generator.bld

        args = self.env.PYTHON + [self.inputs[0].abspath()]
        args += ["-o", self.output_dir.abspath() ]
        args += ["-M", self.module ]
        args += self.colon("INC_ST", "INCPATHS" )
        args += self.colon("DEF_ST", "DEFINES" )
        args += self.colon('DEP_MODULE_ST', 'DEP_MODULES')
        args += self.colon('DECL_DB_ST', 'DECL_DBS')
        args += [ x.abspath() for x in self.inputs[1:] ]

        env = get_environ(bld)

        try:
            stdout, stderr = bld.cmd_and_log(args, cwd = bld.variant_dir, env=env, output=Context.BOTH, quiet=Context.BOTH)
        except Errors.WafError as e:
            try:
                print(e.stdout)
                print(e.stderr)
                return e.returncode
            except AttributeError:
                raise e

        Logs.debug("pypp: " + stdout)
        Logs.debug("pypp: " + stderr)

        self.outputs.extend(self.find_output_nodes())
        self.generator.bld.raw_deps[self.uid()] = [self.signature()] + self.outputs
        self.add_cxx_tasks(self.outputs)

    def __str__(self):
        "string to display to the user"
        env = self.env
        src_str = ' '.join([a.nice_path(env) for a in self.inputs])
        mod = self.module
        return '%s: %s -> module %s\n' % (self.__class__.__name__.replace('_task', ''), src_str, mod)

    def find_output_nodes(self):
        outputs = []
        md5db = self.output_dir.find_node(self.module + ".md5.sum")
        if (md5db):
            outputs.append(md5db)
            data = md5db.read().split('\n')
            for line in data:
                try:
                    f = line.split()[1]
                    if f.endswith(".cpp"):
                        node = self.output_dir.find_node(f)
                        if node:
                            outputs.append(node)
                except IndexError:
                    pass
        else:
            node = self.output_dir.find_node(self.module + ".cpp")
            outputs.append(node)
        return outputs

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
        # ECM (2018-10-23) did we support more_tasks?
        assert getattr(self, "more_tasks", None) is None
        self.more_tasks = []
        for node in lst:
            if not node.name.endswith('.cpp'):
                continue
            tsk = self.generator.create_compiled_task('cxx', node)
            self.more_tasks.append(tsk)

            tsk.env.append_value('INCPATHS', [node.parent.abspath()])
            tsk.env.append_value('CXXFLAGS', ['-Wno-unused-parameter'])
            tsk.env.append_value('CXXFLAGS', ['-Wno-unused-local-typedefs'])

            # ignore some more warnings introduced with g++ 8.x
            if tsk.env['COMPILER_CXX'] == 'g++' and int(tsk.env['CC_VERSION'][0]) > 7:
                tsk.env.append_value('CXXFLAGS', ['-Wno-catch-value'])
                tsk.env.append_value('CXXFLAGS', ['-Wno-ignored-qualifiers'])
                tsk.env.append_value('CXXFLAGS', ['-Wno-maybe-uninitialized'])

            if getattr(self.generator, 'link_task', None):
                self.generator.link_task.set_run_after(tsk)
                self.generator.link_task.inputs.append(tsk.outputs[0])
            self.generator.link_task.inputs.sort(key=lambda x: x.abspath())

    def runnable_status(self):
        ret = super(pyplusplus, self).runnable_status()
        if ret == Task.SKIP_ME and force_run():
            return Task.RUN_ME
        elif ret == Task.SKIP_ME:
            # Tasks.runnable_status() does not know about the generated files, so lets check
            # for existance here; it checks for previous vs signature though -> first element
            # checking can be skipped
            nodes = self.generator.bld.raw_deps[self.uid()][1:]
            for x in nodes:
                try:
                    # user might have changed something in the build folder...
                    os.stat(x.abspath())
                except:
                    Logs.warn("Expected generated file {} missing; " +
                              "deleted manually? RUN_ME!".format(x.abspath()))
                    return Task.RUN_ME

            # Generator does not need to run (SKIP_ME), but we have to fixup some attributes
            self.outputs = list(nodes)
            self.add_cxx_tasks(nodes)

        return ret

@feature('pypp')
@after_method('apply_link')
@before_method('process_use')
def create_pyplusplus(self):
    # Fixup pyplus plus compiler
    self.env.detach()
    self.env.CXX = self.env.CXX_PYPP
    self.use = self.to_list(getattr(self, 'use', []))
    self.use.extend(self.env[ENV_PYPP_USES])

    # Fetch link task
    try:
        self.pyext_task = self.link_task
    except AttributeError:
        self.bld.fatal('You have to use pypp with cxxshlib feature in %s' % str(self))

    # collect attributes
    if not getattr(self, 'script', None):
        self.bld.fatal('script file not set')
    module = getattr(self, 'module', self.target)
    out_dir = getattr(self, 'output_dir', module)
    out_dir = self.path.get_bld().make_node(out_dir)
    out_dir.mkdir()

    decl_db = out_dir.find_or_declare(module + '.exposed_decl.pypp.txt')

    headers = self.to_list(getattr(self, 'headers', []))
    inputs = self.to_nodes( [self.script] + headers )
    outputs = [decl_db]
    dep_nodes = self.to_nodes(getattr(self, 'depends_on_files', []))

    # create task
    self.pypp_task = self.create_task('pyplusplus', inputs, outputs)
    self.pypp_task.env.OUTPUT_DIR = out_dir.abspath()
    self.pypp_task.env.DEF_ST = ["-D"]
    self.pypp_task.env.INC_ST = ["-I"]
    self.pypp_task.env.DECL_DB_ST = ["--decl_db"]
    self.pypp_task.env.DEP_MODULE_ST = ["--dep_module"]
    self.pypp_task.env.DEP_MODULES = []
    self.pypp_task.env.DECL_DBS = []
    self.pypp_task.module = module
    self.pypp_task.output_dir = out_dir
    self.pypp_task.dep_nodes.extend(get_manual_module_dependencies(self.bld))
    self.pypp_task.dep_nodes.extend(dep_nodes)
    self.pypp_task.pyext_task = self.pyext_task

    self.pypp_task.pyext_task.set_run_after(self.pypp_task)

@feature('pypp')
@after_method('process_use')
def add_module_dependencies(self):
    t = self.pypp_task
    dep_modules = []
    decl_dbs = []
    for name in self.tmp_use_seen:
        task_gen = self.bld.get_tgen_by_name(name)
        pyext_task = getattr(task_gen, 'pyext_task', None)
        pypp_task  = getattr(task_gen, 'pypp_task', None)
        if pyext_task:
            dep_modules.append(task_gen.target)
        if pypp_task:
            t.dep_nodes.extend(pypp_task.outputs)
            decl_dbs.append(pypp_task.outputs[0].abspath())
    t.env.DEP_MODULES = dep_modules
    t.env.DECL_DBS = decl_dbs

    defines = self.to_list(getattr(self, 'gen_defines', []))
    t.env.append_value('DEFINES', defines)


@feature('c', 'cxx', 'd', 'fc', 'asm')
@after_method('process_use')
def fix_pyplusplus_linkage(self):
    """This methods allows python modules to be used in use of other libs"""
    clear = set()
    for name in self.tmp_use_seen:
        task_gen = self.bld.get_tgen_by_name(name)
        pyext_task = getattr(task_gen, 'pyext_task', None)
        if pyext_task:
            tgt = task_gen.target
            libname = tgt[tgt.rfind(os.sep) + 1:] # from ccroot.py
            clear.add(libname)

    self.env["LIB"] = [ x for x in self.env["LIB"] if not x in clear]





not_found_msg = """Could not import correct module %s

Please use the patched pygccxml and pyplusplus provided at:
ssh://gerrit.bioai.eu:29418/pygccxml
ssh://gerrit.bioai.eu:29418/pyplusplus

Use 'python -v waf configure' to find see where the loaded packages are located
"""


def configure(conf):
    conf.load('compiler_cxx')
    conf.load('python')
    conf.load('boost')
    conf.find_program('gccxml')
    conf.check_python_version(minver=(2,5))
    conf.check_python_headers()

    for mod in ['pygccxml', 'pyplusplus']:
        conf.pypp_add_module_path(os.path.join(base_dir, mod))
        conf.pypp_add_module_dependency(mod)

        test = 'import {0}; {0}.symap2ic_patched'.format(mod)
        try:
            conf.cmd_and_log(conf.env['PYTHON'] + ['-c', test], env=get_environ(conf))
        except Errors.WafError as e:
            print(e.stdout, e.stderr)
            conf.fatal(not_found_msg % mod)

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
        cc = conf.cmd_to_list(conf.find_program('g++', var='CXX'))
        conf.get_cc_version(cc, gcc=True)
        if old_CC_VERSION != conf.env.CC_VERSION:
            msg = "System compiler (%s) doesn't match CXX (%s)." % ('.'.join(conf.env.CC_VERSION), '.'.join(old_CC_VERSION))
            msg += "\nThis might cause problems (see gcc bugzilla #53455)."
            msg += "\nUse CXX_PYPP=g++-4.X to specify the boost library compiler."
            msg += "\nIf your boost library matches the rest of the OS, CXX_PYPP=g++ should suffice."
            raise Errors.WafError(msg)
        conf.env.revert()

    conf.env.CXX_PYPP = os.environ.get('CXX_PYPP', conf.env.CXX)
