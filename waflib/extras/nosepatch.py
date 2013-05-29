"""Monkeypatch nose to accept any callable as a method.

By default, nose's ismethod() fails for static methods.
Once this is fixed in upstream nose we can disable it.

Note: merely importing this module causes the monkeypatch to be applied."""

#-----------------------------------------------------------------------------
#  Copyright (C) 2009  The IPython Development Team
#
#  Distributed under the terms of the BSD License.  The full license is in
#  the file COPYING, distributed as part of this software.
#-----------------------------------------------------------------------------

#-----------------------------------------------------------------------------
# Imports
#-----------------------------------------------------------------------------

import functools
import unittest
import nose.loader
from inspect import ismethod, isfunction

#-----------------------------------------------------------------------------
# Classes and functions
#-----------------------------------------------------------------------------

def getTestCaseNames(self, testCaseClass):
    """Override to select with selector, unless
    config.getTestCaseNamesCompat is True
    """

    # ECM: everything shitty here... just force compat mode!
    return unittest.TestLoader.getTestCaseNames(self, testCaseClass)

##########################################################################
# Apply monkeypatch here
nose.loader.TestLoader.getTestCaseNames = getTestCaseNames
##########################################################################
