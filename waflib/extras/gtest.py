#!/usr/bin/env python
# encoding: utf-8
# Carlos Rafael Giani, 2006
# Thomas Nagy, 2010
# Christoph Koke, 2011

"""
Unit testing system for google test execution:

* in parallel, by using ``waf -j``
* partial (only the tests that have changed) or full (by using ``waf --test-execall``)
* to avoid problems with infinit loop tests can have a timeout

The tests are declared by adding the **gtest** feature to programs:

    def options(opt):
        opt.load('compiler_cxx gtest')
    def configure(conf):
        conf.load('compiler_cxx gtest')
        conf.env.CXXFLAGS_MYPROJECT = ["-g3"]


    def build(bld):
        from wafextra.gtest import buildGTestRunner
        # First create a runner, this ensures also to use the gtest source CODE, if available on the system
        # see http://code.google.com/p/googletest/wiki/V1_6_FAQ#Why_is_it_not_recommended_to_install_a_pre-compiled_copy_of_Goog
        # You can add everything as you can add to bld(...) as keywords
        buildGTestRunner(bld, 'gtestrunner.cpp', 'RUNNER', use = 'MYPROJECT' )

        bld(
            features='cxx cxxprogram test', 
            source='test.cpp', 
            target='app',
            skip_run=False,
            use = "MYPROJECT RUNNER",
            gtest_main="test-main.cpp",
            test_env={"DATA_PATH" : data.abspath() },
            )

parameters of the feature:
    target = name of the test executeable
    source = sources of the tests
    skip_run = True: the test is only excuted, when the --test-execall option is set

When the build is executed, the program 'test' will be built and executed without arguments.
The success/failure is detected by looking at the return code. The status and the standard output/error
are stored on the build context.


The results can be displayed by registering a callback function. Here is how to call
the predefined callback:

def build(bld):
    bld(
        ....
    )
    from wafextra.gtest import summary
    bld.add_post_fun(summary)

"""

import os, sys
from waflib.TaskGen import feature, after_method, before_method
from waflib import Build, Utils, Task, Logs, Options, Errors, Node
from waflib.Tools import ccroot
from os.path import basename, join
from time import time
import test_base as test

USE_GTEST = "GTEST"
_gtest_bundled_src = 'gtest-all.cc'

@feature('gtest')
@before_method('process_rule')
def gtest_disable(self):
    """Disable the task comptly"""
    if self.testsDisabled():
        self.meths[1:] = []

@feature('gtest')
@before_method('process_use')
def gtest_add_use(self):
    """Add GTEST to use of the task"""
    if self.testsDisabled():
        return

    self.use = self.to_list(getattr(self, "use", []))
    if not USE_GTEST in self.use:
        self.use.append(USE_GTEST)

@feature('gtest')
@after_method('apply_link', 'process_use', 'propagate_uselib_vars')
def gtest_add_test_runner(self):
    if self.testsDisabled():
        return

    if getattr(self, 'link_task', None) is None:
        return

    src = []
    if not "GTEST_MAIN_SRC" in  self.env: raise Errors.WafError, "env broken, please rerun configure"
    for f in self.to_list(getattr(self, "test_main", self.env.GTEST_MAIN_SRC)):
        if not f is None:
            r = self.path.find_resource(f) or self.bld.bldnode.find_resource(f)
            if r is None:
                raise Errors.WafError, "Source file for testrunner missing: %s" % f
            src.append(r)
    for f in getattr(self.env, "GTEST_GTEST_SRC", []):
        src.append(self.bld.root.find_node(f) or self.bld.bldnode.find_or_declare(f))
    cxx_env_hash = self.bld.hash_env_vars(self.env, ccroot.USELIB_VARS['cxx'])

    try:
        cache = self.bld.gtest_task_cache
        idx_cache = self.bld.gtest_idx_cache
    except AttributeError:
        cache = self.bld.gtest_task_cache = {}
        idx_cache = self.bld.gtest_idx_cache = set()

    for n in src:
        node_id = (n, cxx_env_hash)
        try:
            self.link_task.set_inputs(cache[node_id].outputs[0])
        except KeyError:
            while (n, self.idx) in idx_cache:
                self.idx += 1
            t = self.create_compiled_task("cxx", n)
            self.link_task.set_inputs([t.outputs[0]])
            cache[node_id] = t
            idx_cache.add((n, self.idx))

@feature('gtest')
@after_method('apply_link', 'process_use', 'propagate_uselib_vars')
def gtest_run_task(self):
    """Create the unit test task. There can be only one unit test task by task generator."""
    if self.testsDisabled():
        return
    if getattr(self, 'link_task', None):
        t = self.create_task('gtest', self.link_task.outputs)
        t.init(self)

class gtest(test.TestBase):
    """
    Execute a goole unit test
    """
    def run(self):
        """
        Execute the test. The execution is always successful, but the results
        are stored on ``self.generator.bld.utest_results`` for postprocessing.
        """

        filename = self.inputs[0].abspath()
        name = basename(filename)
        cmd = [ filename ]

        xml_result_dir = self.getXmlDir()
        if not xml_result_dir is None:
            xml_result_file = xml_result_dir.find_or_declare( name + ".xml")
            cmd.append( "--gtest_output=xml:" + xml_result_file.abspath() )

        result = self.runTest(self.inputs[0].name, cmd)


summary = test.summary


def options(opt):
    test.options(opt)
    opt.add_option('--with-gtest-src', action='store', default = [],
                   dest="gtest_src", 
                   help='Location of the bundled google test source (%s)' % _gtest_bundled_src)


def configure(ctx):
    """From 1.6 on gtest recommends to install the sources and compile gtest with the
same setting as your main project. So what we do:
1) Check for gtest sources in /usr/src/gtest, /usr/src/gtest/src and gtest and try to compile:
    gtest-all.cc  gtest.h into a test
2) As fallback we look for the regular gtest.h"""
    test.configure(ctx)
    
    if ctx.tests_disabled():
        ctx.start_msg('Checking for GoogleTest')
        ctx.end_msg( "disabled", "RED" )
        return

    if not ctx.env.CC and not ctx.env.CXX:
        ctx.fatal('Load a C/C++ compiler first')

    kwargs = {
            'header_name' : 'gtest/gtest.h',
            'uselib_store' : 'GTEST',
            'define_name' : 'HAVE_GTEST',
            }

    search_folders = gtest_src_search_pathes(ctx.env)
    gtest_main     = makeDefaultTestRunner(ctx)
    try:
        gtest_src = ctx.find_file(_gtest_bundled_src, search_folders)
        gtest_src = ctx.root.find_node(gtest_src) or ctx.path.find_node(gtest_src)
        gtest_inc = gtest_src.parent.parent # Folder containing gtest/gtest-all.cc
        gtest_src_path = gtest_src.srcpath() if gtest_src.is_src() else gtest_src.abspath()
        gtest_inc_path = gtest_inc.srcpath() if gtest_inc.is_src() else gtest_inc.abspath()

        ctx.check_cxx(
                msg = "Checking for GoogleTest sources",
                okmsg = gtest_src_path,
                lib = ['pthread'],
                includes = [gtest_inc_path],
                sources  = [gtest_src, gtest_main],
                **kwargs)
        ctx.env.GTEST_GTEST_SRC = [gtest_src_path]
        if not gtest_src.is_src():
            ctx.env.append_unique(Build.CFG_FILES, [gtest_src.abspath()])
    
    except Errors.ConfigurationError as e:
        ctx.check_cxx(
            msg = "Checking for GoogleTest library",
            lib = ['gtest', 'pthread'],
            **kwargs)

def makeDefaultTestRunner(ctx):
    runner = ctx.bldnode.make_node("gtest-default-runner.cpp")
    runner.write("""
#include <gtest/gtest.h>

int main(int argc, char *argv[])
{
    testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
""")
    ctx.env.GTEST_MAIN_SRC = [runner.bldpath()]
    ctx.env.append_unique(Build.CFG_FILES, [runner.abspath()])
    return runner


def gtest_src_search_pathes(env):
    """
    Returns a list of pathes to search for gtest bundled sources

    Order to resolve
    1. configure option: --with-gtest-src XYX
    2. env.GTEST_SRC = XYZ
    3. '/usr/src/gtest', '/usr/src/gtest/src'
"""
    l = Utils.to_list(getattr(Options.options, 'gtest_src', []))
    l += Utils.to_list(getattr(env, 'GTEST_SRC', []))
    l += ['/usr/src/gtest', '/usr/src/gtest/src']
    return l
    

def buildGTestRunner(bld, runner, target, **kwargs):
    """Build the GTestLib or uses the precompiled, if no sources are available
    """
    raise Errors.WafError, """buildGTestRunner is gone, use instead:
bld(
    feature = "gtest",
    test_main = "runner.cpp",
    ...
)\n"""
