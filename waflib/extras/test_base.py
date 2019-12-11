#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2011

"""
Base tool for tests

# Enviroment variable handling:

The enviroment variables are copied from os.environ. These can be overwritten
by passing a dictionary via the test_environ keyword.

The variables PATH, DYLD_LIBRARY_PATH, LD_LIBRARY_PATH and PYTHONPATH are
specially handled. The following pathes are added there, in the given order:
 1. Any path given by prepend_to_path, prepend_to_pythonpath, ...
 2. Any path given via test_environ
 3. All output folders of all link_task recursivly found via use
 4. The value from os.environ

"""

import os
import signal
import sys
import traceback
import errno

from threading import Thread, Lock
from subprocess import Popen, PIPE, check_output, CalledProcessError
from collections import defaultdict
from xml.etree import ElementTree
from time import time, sleep
from copy import deepcopy

from waflib.TaskGen import taskgen_method
from waflib import Configure, Utils, Task, Logs, Options, Node, Errors

COLOR = 'CYAN'
resultlock = Lock()

DEFAULT_TEST_TIMEOUT = 30

SPECIAL_ENV_VARS = [
    "PATH", 'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH', 'PYTHONPATH']

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
    # Note: Default for timeout is set during configure, otherwise we can not
    # detect, if --test-timeout was given during build, e.g:
    #   waf build --test-timeout 60
    grp.add_option('--test-timeout', action='store',
                   dest="test_timeout",
                   help='Maximal runtime in seconds per test executable')


def configure(ctx):
    ctx.env.TEST_DISABLED = bool(getattr(Options.options, 'test_disabled', False))
    if ctx.tests_disabled():
        return False;

    txt_result_path =  getattr(Options.options, 'test_text_output_folder', None)
    ctx.env.TEST_TEXT_DIR = txt_result_path
    node = getDir(ctx, 'TEST_TEXT_DIR')
    ctx.start_msg('Test text summary directory')
    ctx.end_msg(node.path_from(ctx.srcnode))

    xml_result_path =  getattr(Options.options, 'test_xml_output_folder', None)
    ctx.env.TEST_XML_DIR = xml_result_path
    node = getDir(ctx, 'TEST_XML_DIR')
    ctx.start_msg('Test xml summary directory')
    ctx.end_msg(node.path_from(ctx.srcnode))

    # See TestBase.init
    ctx.start_msg('GoogleTest maximal runtime')
    timeout = getattr(Options.options, 'test_timeout', None)
    if timeout is not None:
        ctx.end_msg(str(timeout) + " seconds")
        ctx.env.TEST_TIMEOUT = timeout
    else:
        ctx.end_msg(str(DEFAULT_TEST_TIMEOUT) + " seconds (default)")


@Configure.conf
def tests_disabled(ctx):
    return ctx.env.TEST_DISABLED

def getLongestField(d, key):
    if d:
        item = max(d, key = lambda x: len(x[key]))
        return len(item[key])
    else:
        return 0

def formatStatisticsBrokenTests(results):
    total_none_excecuted = 0
    total_tests, total_errors, total_failures, total_skip = 0, 0, 0, 0
    for result in results:
        statistic = result["statistic"]
        if statistic is None:
            continue

        tests, errors, failures, skip = statistic
        total_tests += tests
        total_errors += errors
        total_failures += failures
        total_skip += skip

        if tests == 0:
            total_none_excecuted += 1

    # Count tests that are somehow broken, e.g. crashed or didn't run any
    # tests at all
    count = defaultdict(int)
    for item in results:
        count[item["status"]] += 1

    # Filter out failures and passes
    for key in (TestBase.PASSED, TestBase.FAILED):
        try:
            del count[key]
        except KeyError:
            pass

    if total_none_excecuted > 0:
        count['None executed'] = total_none_excecuted

    # Build messages
    if count:
        msg = "   {status:.<%i}: {no:>4}" % max(len(s) for s in count.keys())
        broken = ["Broken tests:"]
        for status, no in count.items():
            broken.append(msg.format(status=status, no=no))
    else:
        broken =[]

    statistics = [
        "Test Summary:",
        "   Errors...: {}".format(total_errors),
        "   Failures.: {}".format(total_failures),
        "   Skipped..: {}".format(total_skip),
        "   Total....: {}".format(total_tests),
    ]

    return os.linesep.join(statistics), os.linesep.join(broken)

def removeDuplicates(seq):
    seen = set()
    return [ x for x in seq if x not in seen and not seen.add(x)]

def to_dirs(task_gen, paths):
    """
    Convert a list of string/nodes into a list of folders relative to path.
    """
    nodes = []
    for path in task_gen.to_list(paths):
        if isinstance(path, Node.Node):
            node = path
        elif os.path.isabs(path):
            node = task_gen.root.find_dir(path)
        else:
            node = task_gen.path.find_dir(path)

        if node is None:
            raise Errors.WafError("not found: %r in %r" % (path, task_gen))
        nodes.append(node)
    return nodes

def addSummaryMsg(results):
    for result in results:
        msg = []

        status = result["status"]
        statistic = result["statistic"]
        # If statistic is not None it must be a tuple of numbers:
        if statistic is not None:
            assert None not in statistic

        if status == TestBase.PASSED:
            color = "GREEN"
            if statistic is None:
                msg.append('successful (no statistics)')
            else:
                total, errors, failures, skip = statistic
                passed = total - (errors + failures + skip)
                msg.append('{} passed'.format(passed))
                if skip != 0:
                    msg.append('({} skipped)'.format(skip))
        elif status == TestBase.FAILED:
            color = "RED"
            if statistic is None:
                msg.append('failed (no statistics)')
            else:
                total, errors, failures, skip = statistic
                fail_sum = errors + failures
                if not fail_sum:  # Something went wrong, mark everything failed
                    fail_sum = total
                msg.append('{}/{} failed'.format(fail_sum, total))
        elif status == TestBase.TIMEOUT:
            color = "YELLOW"
            msg.append('timeout')
        else:
            color = "RED"
            msg.append(status)
            msg.append("({})".format(result.get('error_message')))

        result['msg'] = ' '.join(msg)
        result['color'] = color


def write_summary_xml(results, path):
    """
    Create a JUnit-parseable XML file wih all test-binaries that should have
    been run.
    """

    def remove_evil_chars(string):
        """
        Remove ANSI escape characters that cannot be handled by JUnit
        """
        escape_numbers = list(range(1, 32))   # all ANSI escape characters
        escape_numbers.remove(10)       # newline is fine
        escape_numbers.remove(13)       # carriage return is fine
        escapes = ''.join([chr(char) for char in escape_numbers])
        try:
            table = str.maketrans(dict.fromkeys(escapes))
            return string.translate(table)
        except AttributeError:  # python2 compatibility
            return str(string).translate(None, escapes)

    # JUnit XML root
    testsuites = ElementTree.Element('testsuites')

    # Find all tested projects and register them in a hashmap
    project_names = set([test_binary["project"] for test_binary in results])
    projects = {project_name: ElementTree.SubElement(testsuites, "testsuite",
                                                     dict(name=project_name))
                for project_name in project_names}

    for test_result in results:
        project = remove_evil_chars(test_result["project"])
        test_name = remove_evil_chars(test_result["file"])
        status = test_result["status"]
        test_time = remove_evil_chars(str(test_result["time"]))
        try:
            stdout_text = remove_evil_chars(test_result["stdout"])
        except KeyError:
            stdout_text = ""
        try:
            stderr_text = remove_evil_chars(test_result["stderr"])
        except KeyError:
            stderr_text = ""

        # Add test case to tree
        testcase = ElementTree.SubElement(projects[project], "testcase",
                                          dict(name=test_name, time=test_time))

        stdout = ElementTree.SubElement(testcase, "system-out")
        stdout.text = stdout_text
        stderr = ElementTree.SubElement(testcase, "system-err")
        stderr.text = stderr_text

        if status is TestBase.PASSED:
            continue
        elif status is TestBase.FAILED:
            ElementTree.SubElement(testcase, "failure")
            continue
        else:
            ElementTree.SubElement(testcase, "error")
            continue

    tree = ElementTree.ElementTree(testsuites)
    tree.write(path)


def addTimeMsg(results):
    field = "({:.1f}s)"
    for result in results:
        result['msg_time'] = field.format(result['time'])

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
    addSummaryMsg(results)
    addTimeMsg(results)

    len_file = getLongestField(results, "file") + 1
    len_status = getLongestField(results, "msg")
    len_time = getLongestField(results, "msg_time")

    project_line = "{}:"
    result_line = (
        "   {{:.<{}}}{{:.>{}}}:".format(len_file, len_time),
        "{{:<{len_status}}}".format(len_status = len_status),
    )

    # Collect all projects
    projects = sorted(set(r['project'] for r in results))
    for project in projects:
        project_results = sorted(
            (r['file'], r) for r in results if r['project'] == project)

        Logs.pprint(COLOR, project_line.format(project))

        for _, line in project_results:
            line_head = result_line[0].format(line["file"], line["msg_time"])
            line_tail = result_line[1].format(line["msg"])
            Logs.pprint(COLOR, line_head, sep=" ")
            Logs.pprint(line['color'], line_tail)

    statistics, broken = formatStatisticsBrokenTests(results)
    if broken:
        Logs.pprint("YELLOW", "")
        Logs.pprint("YELLOW", broken)

    Logs.pprint(COLOR, "")
    Logs.pprint(COLOR, statistics)
    Logs.pprint(COLOR, "")

    txt_result_dir, xml_result_dir = getDir(ctx, "TEST_TEXT_DIR"), getDir(ctx, "TEST_XML_DIR")
    if not txt_result_dir is None:
        Logs.pprint(COLOR,
            "text results are stored in {}".format(txt_result_dir.abspath()))
    if not xml_result_dir is None:
        write_summary_xml(results, os.path.join(xml_result_dir.abspath(),
                                              "summary.xml"))
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
    """TaskGen method to check, if tests are generally disabled"""
    ctx = self.bld
    return (bool(ctx.env.TEST_DISABLED) or
            bool(getattr(Options.options, 'test_disabled', False)))

@taskgen_method
def isTestExecutionEnabled(self):
    """TaskGen method to check, if we should create a test execution task"""
    # Should this test generally not be executed by setting skip_run=True in
    # the wscript?
    skip_run = getattr(self, 'skip_run', False)
    # Are they disabled for this run by the --test-execnone option?
    run_none = getattr(Options.options, 'test_run_none', False)
    # Is this specific test requested by the --test-exec <testname> option?
    run_this = runByName(self.name)
    return not ((skip_run and not run_this) or (run_none and not run_this))

class TestBase(Task.Task):
    """
    Execute a unit test
    """
    color = COLOR
    after = ['vnum', 'inst']

    FAILED = "failed"
    PASSED = "passed"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    INTERNAL_ERROR = "(waf) error"

    def __init__(self, *args, **kwargs):
        super(TestBase, self).__init__(self, *args, **kwargs)
        self.timeout = DEFAULT_TEST_TIMEOUT # For __str__, overwriten in init

    def __str__(self):
        "string to display to the user"
        return '%s (timeout: %is)' % (
            Task.Task.__str__(self), self.timeout)

    def init(self, task_gen):
        """Common initialisation of Test tast, should be called by task_gen
        methods for derived tests
        """
        self.cwd = task_gen.path.abspath()

        # One task generator might be used for multiple tasks, protect others
        # from in-place modifications made by this specific task.init().
        self.test_environ = deepcopy(getattr(task_gen, "test_environ", {}))

        # Evalutate enviroment variables, see module docstring
        for var in SPECIAL_ENV_VARS:
            key = "prepend_to_" + var.lower()
            # Adding the value of pythonpath to test_env
            pathes = []
            pathes = [n.abspath() for n in
                      to_dirs(task_gen, getattr(task_gen, key, ""))]
            setattr(task_gen, key, pathes)
            for use in task_gen.tmp_use_seen:
                tg = task_gen.bld.get_tgen_by_name(use)
                pathes.extend(getattr(tg, key, []))
            if var in self.test_environ:
                pathes += os.environ.get(var).split(os.pathsep)
            self.test_environ[var] = os.pathsep.join(pathes)

        self.skip_run = getattr(task_gen, "skip_run", False)
        src_dir = task_gen.path.srcpath()
        self.project = task_gen.path.relpath().split(os.sep)[0]
        self.xmlDir = getDir(task_gen.bld, "TEST_XML_DIR", src_dir)
        self.txtDir = getDir(task_gen.bld, "TEST_XML_DIR", src_dir)

        # Get timeout for test execution, order is:
        #   1. command line argument given during execution, e.g. build --test-timeout 20
        #   2. command line argument given during configure, e.g. build --test-timeout 30
        #   3. timeout specified in task: e.g.: bld(features='pytest', test_timeout=60)
        #   4. default timeout
        timeout = getattr(Options.options, 'test_timeout', None)
        if timeout is None:
            timeout = task_gen.env["TEST_TIMEOUT"]
            if timeout != 0 and not timeout:
                timeout = None
        if timeout is None:
            timeout = getattr(task_gen, "test_timeout", None)
        if timeout is None:
            timeout = DEFAULT_TEST_TIMEOUT
        self.timeout = int(timeout)

    def storeResult(self, result):
        bld = self.generator.bld
        result['project'] = self.project
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
        Always execute the task if `waf --test-execall` or `--test-exec` was set
        """
        ret = super(TestBase, self).runnable_status()
        if (ret == Task.SKIP_ME and
                (runAll() or runByName(self.generator.name))):
            ret = Task.RUN_ME
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
            if 'py' in tg.features:
                # py thingy, lets add the paths to the build folder
                if hasattr(tg, 'relative_trick'):
                    if tg.relative_trick:
                        if tg.install_from is not None:
                            pathes.add(tg.install_from.abspath())
                        else:
                            pathes.add(tg.path.get_src().abspath())
                    else:
                        for sf in tg.source:
                            pathes.add(sf.parent.abspath())
                else:
                    for sf in tg.source:
                        pathes.add(sf.parent.abspath())
            if hasattr(tg, 'link_task'):
                pathes.add(tg.link_task.outputs[0].parent.abspath())

        # Env polution, hihi
        for var in SPECIAL_ENV_VARS:
            # Evalutate enviroment variables, see module docstring
            p = []
            p.extend(env.get(var, "").split(os.pathsep))
            p.extend(pathes)
            if var in os.environ:
                p.extend(os.environ[var].split(os.pathsep))
            env[var] = os.pathsep.join(removeDuplicates(p))
        return env

    def getXMLFile(self, test):
        xml_file = test.change_ext(".xml")
        return self.xmlDir.find_or_declare(xml_file.name)

    def readTestResult(self, test):
        """
        Extract the test result from the xml file
        """
        try:
            xmlfile = self.getXMLFile(test)
            tree = ElementTree.parse(xmlfile.abspath())
            root = tree.getroot()
            return [int(root.attrib.get(attr, 0))
                    for attr in ('tests', 'errors', 'failures', 'skip')]
        except IOError as e:
            if e.errno != errno.ENOENT:
                raise
        except ElementTree.ParseError:
            pass
        return None

    def runTest(self, test, cmd, cwd=None):
        if cwd is None: cwd = self.cwd

        environ = self.getEnviron()
        name = test.name
        result = {"file" : name, "statistic": None}
        def target():
            try:
                if Logs.verbose:
                    Logs.pprint('PINK', '   spawning test:', '%s' % cmd)
                self.proc = Popen('%s' % ' '.join(cmd),
                             cwd=cwd,
                             env=environ,
                             stderr=PIPE,
                             stdout=PIPE,
                             shell=True
                )
                stdout, stderr = self.proc.communicate()
                stdout = stdout.decode(sys.stdout.encoding or "utf-8")
                stderr = stderr.decode(sys.stderr.encoding or "utf-8")
                result["stdout"], result["stderr"] = stdout, stderr
                if self.proc.returncode == 0:
                    result["status"] = self.PASSED
                    result["statistic"] = self.readTestResult(test)
                elif self.proc.returncode < 0:
                    result["status"] = self.CRASHED
                    result["error_message"] = "return code: {}".format(
                        self.proc.returncode)
                else:
                    result["status"] = self.FAILED
                    result["statistic"] = self.readTestResult(test)
            except Exception as e:
                result["stderr"] = traceback.format_exc(e)
                result["status"] = self.INTERNAL_ERROR
                result["error_message"] = e.message

        starttime = time()
        thread = Thread(target=target)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            # killing processes is difficult (race conditions all over the place)...
            # for all children (recusive!) of the test process:
            #   * first try to terminate
            #   * then try to kill to be safe
            #   * (try/except as processes could have finished in the meantime)
            def kill_proc_recursively(self, thread, result):
                if hasattr(self, 'proc'):
                    assert isinstance(self.proc.pid, int)
                    Logs.debug("Trying to kill_proc_recursively, pid: %d", self.proc.pid)

                    # expected to be newline-separated list of self.proc.pid and
                    # all its children
                    try:
                        out = check_output('pstree -pn {}'
                                           '| grep -o "([[:digit:]]*)"'
                                           '| grep -o "[[:digit:]]*"'.\
                                           format(self.proc.pid), shell=True).\
                                           decode(sys.stdout.encoding or 'utf-8')
                        Logs.debug("pstree output: '%s'", out)
                    except CalledProcessError as e:
                        # non-zero exit code => process not found (possible due to race)
                        Logs.warn("Process {} is already gone; children and the process" \
                                  " itself won't be killed.".format(self.proc.pid))
                        result["status"] = self.TIMEOUT
                        return # nothing to do, return early
                    out = out.split()
                    pids = []
                    for v in out:
                        assert v.isdigit(), "String is not a number: '{}'".format(v)
                        pids.append(int(v))

                    # we'll try it two times, reversing will kill directly spawned process last
                    pids = list(reversed(pids + pids))
                    assert (len(pids) > 0) and pids[-1] == self.proc.pid

                    Logs.debug("will kill pids: %s", pids)
                    for pid in pids:
                        try:
                            Logs.debug("terminating {}".format(pid))
                            os.kill(pid, signal.SIGTERM)
                            sleep(0.5) # grace period
                            Logs.debug("killing {}".format(pid))
                            os.kill(pid, signal.SIGKILL)
                            sleep(0.5) # grace period
                        except OSError as e:
                            # ignore "process not found"
                            pass
                thread.join(0.5) # to avoid another hang...
                result["status"] = self.TIMEOUT

            kill_proc_recursively(self, thread, result)

        result["time"] = time() - starttime
        self.storeResult(result)

        txt_result_dir = self.txtDir
        if not txt_result_dir is None:
            result_file = txt_result_dir.find_or_declare(name + ".txt")
            result_file.write(result.get("stdout", ""))
            result_file = txt_result_dir.find_or_declare(name + ".err")
            result_file.write(result.get("stderr", ""))
            debug_script = ['cd ' + self.cwd]
            for var, value in environ.items():
                debug_script.append('export {var}="{value}"'.format(
                    var=var, value=value))
            debug_script.append('%s' % ' '.join(cmd))
            result_file = txt_result_dir.find_or_declare(name + ".sh")
            result_file.write('\n'.join(debug_script))

        return result
