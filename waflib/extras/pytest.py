#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2012

"""
"""

import os, sys
from waflib.TaskGen import feature, after_method, before_method
from waflib.Tools import ccroot
from waflib import Utils
from os.path import basename, join, splitext
import pytest_runner
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
            xml = self.getOutputNode(test.name, self.getXmlDir(), "xml")
            runner = pytest_runner.__file__
            if runner[-4:] == ".pyc":
                runner = runner[:-1]

            cmd = [ self.env.get_flat("PYTHON"),
                    runner,
                    test.abspath(),
                    xml.abspath() if xml else "",
                    ]
            result = self.runTest(test.name, cmd)

    def getOutputNode(self, name, d, ext):
        if d is None:
            return None
        result_file = d.find_or_declare(basename(name) + "." + ext);
        return result_file

@feature('pyext')
@after_method("apply_link")
def add_pyext(self):
    self.pyext_task = self.link_task

@feature("pytest")
@after_method("process_use")
def pytest_process_use(self):
    if not hasattr(self, "uselib"):
        ccroot.process_use(self)

@feature("pytest")
@after_method("pytest_process_use")
def pytest_create_task(self):
    """Create the unit test task. There can be only one unit test task by task generator."""
    input_nodes = self.to_nodes(self.tests)

    # Adding the value of pythonpath to test_env
    pythonpath = self.to_incnodes(getattr(self, "pythonpath", ""))
    self.test_environ = getattr(self, "test_environ", {})
    self.test_environ["PYTHONPATH"] = os.pathsep.join(
            [n.abspath() for n in pythonpath] +
            self.test_environ.get("PYTHONPATH","").split(os.pathsep) +
            os.environ.get("PYTHONPATH", "").split(os.pathsep)
    )

    self.pytest_task = t = self.create_task('pytest', input_nodes)
    t.skip_run = getattr(self, "skip_run", False)
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
