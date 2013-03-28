#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2012

"""
"""

import os, sys
from waflib.TaskGen import feature, after_method, before_method
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

            env = self.getEnviron()
            env["PYTHONPATH"] = os.pathsep.join(
                    [ n.abspath() for n in self.pythonpath ] +
                    env.get("LD_LIBRARY_PATH", "").split(os.pathsep) +
                    env.get("PYHTONPATH", "").split(os.pathsep) )

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


@feature("pytest")
def create_pytest_task(self):
    """Create the unit test task. There can be only one unit test task by task generator."""
    input_nodes = self.to_nodes(self.tests)
    pythonpath = self.to_incnodes(getattr(self, "pythonpath", ""))

    t = self.create_task('pytest', input_nodes)
    t.pythonpath = pythonpath
    t.skip_run = getattr(self, "skip_run", False)
    self.pytest_task = t
    try:
        t.test_timeout = self.timeout
    except AttributeError:
        pass

    inst_to = getattr(self, 'install_path', None)
    if inst_to:
        self.bld.install_files(inst_to, input_nodes, chmod=getattr(self, 'chmod', Utils.O755))

@feature("pytest")
@after_method("create_pytest_task")
def process_pytest_use(self):
    t = self.pytest_task
    for name in self.to_list(getattr(self, 'use', [])):
        dep_task = self.bld.get_tgen_by_name(name)
        dep_task.post()
        try:
            t.set_run_after( dep_task.link_task )
        except AttributeError:
            pass

def options(opt):
    test_base.options(opt)

def configure(ctx):
    test_base.configure(ctx)
