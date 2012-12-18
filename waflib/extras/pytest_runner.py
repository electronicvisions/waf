#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2012

"""
"""

import argparse, os, sys
from os.path import splitext, basename
from imp import load_source
from unittest import TestLoader, TestCase
from xmlrunner import XMLTestRunner
from cStringIO import StringIO

def getTestSuite(filename):
    module_name = splitext(basename(filename))[0]
    m = load_source(module_name, filename)
    return TestLoader().loadTestsFromModule(m)

def runTests(filename, xml):
    suite = getTestSuite(filename)
    r = XMLTestRunner(verbose=True, output=xml).run(suite)
    return len(r.failures) + len(r.errors)

def openStream(name):
    if name:
        return open(name, "w")
    else:
        return StringIO()

if __name__ == '__main__':
    x, test, xml = sys.argv[:3]
    with openStream(xml) as f:
        print "pytest_runner.py: runTests(", test, ",", f, ")\n"
        result = runTests(test, f)
    exit(result)
























































