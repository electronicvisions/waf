#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2012

"""
"""

import os, sys
import re
from waflib.TaskGen import feature, after_method, before_method
from waflib.Tools import ccroot
from waflib import Utils
from os.path import basename, join, splitext
import test_base

class pytest(test_base.TestBase):
    in_ext = [".py"]
    vars = ["PYTHON"]

    def run(self):
        """
        Execute the test. The execution is always successful, but the results
        are stored on ``self.generator.bld.utest_results`` for postprocessing.
        """
        for test in self.inputs:
            xml = self.getXMLFile(test)

            frickeling = "import sys; sys.path.append(r{0}{1}{0}); import nose; import nosepatch; nose.main()".format('"', str(os.path.dirname(os.path.abspath(__file__))))

            #self.env['PYNOSETESTS'],
            cmd = [ self.env.get_flat("PYTHON"),
                    '-c',
                    "'%s'" % frickeling,
                    test.abspath(),
                    '--with-xunit',
                    '--xunit-file="%s"' % xml.abspath() if xml else '',
                    ]
            self.runTest(test, cmd)

    def getXMLFile(self, test):
        return self.getOutputNode(test.name, self.xmlDir, "xml")

    def getOutputNode(self, name, d, ext):
        if d is None:
            return None
        result_file = d.find_or_declare(basename(name) + "." + ext);
        return result_file

@feature('pyext')
@after_method('apply_link')
@before_method('process_use')
def add_pyext_pytest(self):
    self.pyext_task = self.link_task

@feature("pytest")
@after_method("process_use")
def pytest_process_use(self):
    if not hasattr(self, "uselib"):
        ccroot.process_use(self)

@feature("pytest")
@after_method("pytest_process_use")
def pytest_create_task(self):
    if self.testsDisabled():
        return
    """Create the unit test task. There can be only one unit test task by task generator."""
    input_nodes = self.to_nodes(self.tests)

    # Set test name if not given by user
    if not getattr(self, 'name', None):
        fix = re.compile(r'(\.py$)?')
        self.name = "__and__".join(fix.sub('', n.name) for n in input_nodes)

    # Adding the value of pythonpath to test_env
    self.pythonpath = self.to_incnodes(getattr(self, "pythonpath", ""))
    for use in self.tmp_use_seen:
        tg = self.bld.get_tgen_by_name(use)
        pythonpath = getattr(tg, 'pythonpath', [])
        self.pythonpath.extend(self.to_incnodes(pythonpath))

    self.test_environ = getattr(self, "test_environ", {})
    self.test_environ["PYTHONPATH"] = os.pathsep.join(
            [n.abspath() for n in self.pythonpath] +
            self.test_environ.get("PYTHONPATH","").split(os.pathsep) +
            os.environ.get("PYTHONPATH", "").split(os.pathsep)
    )

    self.pytest_task = t = self.create_task('pytest', input_nodes)
    t.init(self)
    for use in self.tmp_use_seen:
        tg = self.bld.get_tgen_by_name(use)
        if hasattr(tg, "pyext_task"):
            t.dep_nodes.extend(tg.pyext_task.outputs)

    inst_to = getattr(self, 'install_path', None)
    if inst_to:
        self.bld.install_files(inst_to, input_nodes, chmod=getattr(self, 'chmod', Utils.O755))

def options(opt):
    test_base.options(opt)

def configure(ctx):
    test_base.configure(ctx)
    ctx.find_program('nosetests', mandatory=True, var='PYNOSETESTS')
