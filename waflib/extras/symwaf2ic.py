#!/usr/bin/env python
# encoding: utf-8

from waflib import Scripting

# Please use --prelude=$'\tfrom waflib.extras.symwaf2ic import prelude; prelude()'

#########################
# Patching run_commands #
#########################

def prepend_entry_point(func):
    def f():
        from waflib.extras.symwaf2ic import entry_point
        entry_point()
        func()
    return f

def prelude():
    print "Running prelude"
    # patch run_commands-method  
    funcname = "run_commands"
    setattr(Scripting, funcname, prepend_entry_point(getattr(Scripting, funcname)))


##################
# Regular Script #
##################

from waflib import Context, Logs

def entry_point():
    Logs.info("Entry point successfully patched.")


class UpgradeContext(Context.Context):
    "Download newest symwaf2ic and toplevel wscript."
    cmd = "upgrade"

    def execute(self):
        Logs.warn("Please implement the upgrader, ty!")

