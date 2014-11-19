
#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2011

"""
"""

import os
import sys
import pprint
from waflib.TaskGen import taskgen_method
from waflib import Configure, Utils, Task, Logs, Options, Errors
from os.path import basename, join
from time import time, sleep
from threading import Thread, Lock
from subprocess import Popen, PIPE
from collections import defaultdict

COLOR = 'CYAN'
resultlock = Lock()

DEFAULT_TEST_TIMEOUT = 30

@Utils.run_once
def options(opt):
    """
    Provide options for gtest tests
    """
    grp = opt.add_option_group('Testing Options')
    grp.add_option('--disable-tests', action='store_true', default=False,
                   dest="test_disabled", help='Disable build and execution of test')
    grp.add_option('--test-exec', action='append', default=[],
                   help='Run a unit test', dest='test_run_by_name')
    grp.add_option('--test-execall', action='store_true', default=False,
                   help='Exec all unit tests', dest='test_run_all')
    grp.add_option('--test-execnone', action='store_true', default=False,
                   help='Do not execute unit tests automatically (overwrittes --test-execall)', dest='test_run_none')
    grp.add_option('--test-text-summary', action='store', default="test_results",
                   dest="test_text_output_folder",
                   help='Store test results as text in the given path relative to the build directory')
    grp.add_option('--test-xml-summary', action='store', default="test_results",
                   dest="test_xml_output_folder",
                   help='Store test results as junit-xml in the given path relative to the build directory')
    grp.add_option('--test-timeout', action='store', default=DEFAULT_TEST_TIMEOUT,
                   dest="test_timeout",
                   help='Maximal runtime in seconds per test executable')


@Utils.run_once
def configure(ctx):
    ctx.env.TEST_DISABLED = bool(getattr(Options.options, 'test_disabled', False))
    if ctx.tests_disabled():
        return False;

    txt_result_path =  getattr(Options.options, 'test_text_output_folder', None)
    if txt_result_path:
        ctx.env.TEST_TEXT_DIR = txt_result_path
        node = getDir(ctx, 'TEST_TEXT_DIR')
        ctx.start_msg('Test text summary directory')
        ctx.end_msg(node.path_from(ctx.srcnode))

    xml_result_path =  getattr(Options.options, 'test_xml_output_folder', None)
    if xml_result_path:
        ctx.env.TEST_XML_DIR = xml_result_path
        node = getDir(ctx, 'TEST_XML_DIR')
        ctx.start_msg('Test xml summary directory')
        ctx.end_msg(node.path_from(ctx.srcnode))

    timeout = int(getattr(Options.options, 'test_timeout', DEFAULT_TEST_TIMEOUT))
    ctx.start_msg('GoogleTest maximal runtime')
    ctx.end_msg(str(timeout) + " seconds")
    ctx.env.TEST_TIMEOUT = timeout

@Configure.conf
def tests_disabled(ctx):
    return ctx.env.TEST_DISABLED

def getLongestField(d, key):
    if d:
        item = max(d, key = lambda x: len(x[key]))
        return len(item[key])
    else:
        return 0

def scaleTime(d, factor):
    for item in d:
        item["time"] = item["time"] * factor

def statusSummary(d):
    msg = "\t{status:.<{status_len}}: {no:>4}\n"
    count = defaultdict(int)
    status_len = getLongestField(d, "status") + 3
    for item in d:
        count[item["status"]] += 1

    out = "Summary:\n"
    for status, no in count.iteritems():
        out += msg.format(**locals())
    out += "\n"
    return out


def removeDuplicates(seq):
    seen = set()
    return [ x for x in seq if x not in seen and not seen.add(x)]

def getStatusColor(results):
    st = results["status"]
    if st == TestBase.PASSED:
        return "GREEN"
    elif st == TestBase.TIMEOUT:
        return "YELLOW"
    else:
        return "RED"


@Utils.run_once
def summary(ctx):
    """
    Display an execution summary::

        def build(bld):
            bld(features='cxx cxxprogram gtest', source='main.c', target='app')
            bld.add_post_fun(summary)
    """

    if ctx.tests_disabled():
        return

    results = getattr(ctx, 'test_results', [])

    len_file = getLongestField(results, "file") + 3
    len_status = getLongestField(results, "status")
    scaleTime(results, 1000.0)

    result_line = (
            "{{:.<{len_file}}}:".format(len_file = len_file),
            "{{:<{len_status}}}".format(len_status = len_status),
            "(execution time: {:.2f}ms)"
    )

    Logs.pprint(COLOR, 'Test results:')
    for line in results:
        Logs.pprint(COLOR, result_line[0].format(line["file"]), sep=" ")
        Logs.pprint(getStatusColor(line), result_line[1].format(line["status"]), sep=" ")
        Logs.pprint(COLOR, result_line[2].format(line["time"]))

    Logs.pprint(COLOR, "\n" + statusSummary(results))

    txt_result_dir, xml_result_dir = getDir(ctx, "TEST_TEXT_DIR"), getDir(ctx, "TEST_XML_DIR")
    if not txt_result_dir is None:
        Logs.pprint(COLOR,
            "text results are stored in {}".format(txt_result_dir.abspath()))
    if not xml_result_dir is None:
        Logs.pprint(COLOR,
            "xml summaries are stored in {}".format(xml_result_dir.abspath()))

def getDir(ctx, key, sub_dir=None):
    if key in ctx.env:
        with resultlock:
            path = ctx.env.get_flat(key)
            if os.path.isabs(path):
                result_dir = ctx.root.make_node(path)
            else:
                result_dir = ctx.bldnode.make_node(path)
            if sub_dir is not None:
                result_dir = result_dir.make_node(sub_dir)
            result_dir.mkdir()
            return result_dir
    else:
        return None

def runAll():
    return getattr(Options.options, 'test_run_all', False)

def runByName(name):
    task_names = getattr(Options.options, 'test_run_by_name', [])
    return name in task_names

def runNone():
    return getattr(Options.options, 'test_run_none', False)

@taskgen_method
def testsDisabled(self):
    ctx = self.bld
    return bool(ctx.env.TEST_DISABLED) or bool(getattr(Options.options, 'test_disabled', False))

class TestBase(Task.Task):
    """
    Execute a unit test
    """
    color = COLOR
    after = ['vnum', 'inst']

    FAILED = "failed"
    PASSED = "passed"
    TIMEOUT = "timeout"
    CRASHED = "crashed (return code: %i)"
    INTERNAL_ERROR = "waf error"

    def __init__(self, *args, **kwargs):
        super(TestBase, self).__init__(self, *args, **kwargs)

    def init(self, task_gen):
        self.cwd = task_gen.path.abspath()
        self.test_environ = getattr(task_gen, "test_environ", {})
        self.test_timeout = getattr(task_gen, "test_timeout",
                                    int(task_gen.env["TEST_TIMEOUT"]))
        self.skip_run = getattr(task_gen, "skip_run", False)

    def getXmlDir(self):
        gen = self.generator
        return getDir(gen.bld, "TEST_XML_DIR", gen.get_name())

    def getTxtDir(self):
        gen = self.generator
        return getDir(gen.bld, "TEST_TEXT_DIR", gen.get_name())

    def hasXmlStore(self):
        return not self.env.get_flat("TEST_XML_DIR")

    def hasTxtStore(self):
        bld = self.generator.bld
        return not self.env.get_flat("TEST_TEXT_DIR")

    def timeout(self):
        return int(getattr(Options.options, 'test_timeout', self.test_timeout))

    def storeResult(self, result):
        bld = self.generator.bld
        assert "time" in result and isinstance(result["time"], float)
        assert "status" in result
        assert "file" in result
        with resultlock:
            Logs.debug("test: %r", result)
            try:
                bld.test_results.append(result)
            except AttributeError:
                bld.test_results = [result]

    def runnable_status(self):
        """
        Always execute the task if `waf --test-execall` was used,
        but not if `waf --test-execnone` was used
        """
        ret = super(TestBase, self).runnable_status()
        if self.skip_run:
            ret = Task.SKIP_ME
        if (ret == Task.SKIP_ME and
                (runAll() or runByName(self.generator.name))):
            ret = Task.RUN_ME
        if runNone():
            ret = Task.SKIP_ME
        return ret

    def getEnviron(self):
        """Add dependency lib pathes to PATH, PYTHON_PATH and LD_LIBRARY_PATH
        Collects all link_task output and adds the pathes to the found outputs to the pathes
        """
        env = os.environ.copy()
        env.update(self.test_environ)

        pathes = set()
        for use in self.generator.tmp_use_seen:
            tg = self.generator.bld.get_tgen_by_name(use)
            if hasattr(tg, 'link_task'):
                pathes.add(tg.link_task.outputs[0].parent.abspath())

        # Env polution, hihi
        envvars =  ["PATH", 'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH', 'PYTHONPATH' ]
        for var in envvars:
            p = list(pathes) + env.get(var, "").split(os.pathsep)
            p = removeDuplicates(p)
            env[var] = os.pathsep.join(p)
        return env

    def runTest(self, name, cmd):
        environ = self.getEnviron()
        result = { "file" : name }
        def target():
            try:
                if Logs.verbose:
                    Logs.pprint('PINK', '   spawning test:', '%s' % cmd)
                self.proc = Popen('%s' % ' '.join(cmd),
                             cwd=self.cwd,
                             env=environ,
                             stderr=PIPE,
                             stdout=PIPE,
                             shell=True
                )
                result["stdout"], result["stderr"] = self.proc.communicate()
                if self.proc.returncode == 0:
                    result["status"] = self.PASSED
                elif self.proc.returncode < 0:
                    result["status"] = self.CRASHED % self.proc.returncode
                else:
                    result["status"] = self.FAILED
            except Exception, e:
                result["stdout"] = e.message
                result["status"] = self.INTERNAL_ERROR

        starttime = time()
        thread = Thread(target=target)
        thread.start()
        thread.join(self.timeout())
        if thread.is_alive():
            # killing processes is difficult (race conditions all over the place)...
            if hasattr(self, 'proc'):
                self.proc.terminate()
                sleep(0.5) # grace period
                try:
                    self.proc.kill()
                except OSError, e:
                    # ignore "process not found"
                    pass
            thread.join(0.5) # to avoid another hang...
            result["status"] = self.TIMEOUT
        result["time"] = time() - starttime
        self.storeResult(result)

        txt_result_dir = self.getTxtDir()
        if not txt_result_dir is None:
            result_file = txt_result_dir.find_or_declare(name + ".txt")
            result_file.write(result.get("stdout", ""))
            result_file = txt_result_dir.find_or_declare(name + ".err")
            result_file.write(result.get("stderr", ""))
            debug_script = ['cd ' + self.cwd]
            for var, value in environ.iteritems():
                debug_script.append('export {var}="{value}"'.format(
                    var=var, value=value))
            debug_script.append('%s' % ' '.join(cmd))
            result_file = txt_result_dir.find_or_declare(name + ".sh")
            result_file.write('\n'.join(debug_script))

        return result
