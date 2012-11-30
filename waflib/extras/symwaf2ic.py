#!/usr/bin/env python
# encoding: utf-8

"Symwaf2ic package"

import os
import sys
import argparse
import shutil
from waflib import Context, Errors, Logs, Options, Scripting
from waflib.extras import mr

# Please use:
# --prelude=$'\tfrom waflib.extras.symwaf2ic import prelude; prelude()'

#########################
# Patching run_commands #
#########################

def prepend_entry_point(func):
    "Prepend our entry point to function execution."
    def patched():
        # from waflib.extras.symwaf2ic import entry_point
        entry_point()
        func()
    return patched


def _patched_execute(self):
    """Patched version of Context.Context.execute() so that not only the root
    wscript is recursed into but all required wscripts as well.

    """
    g_module = Context.g_module
    paths = [os.path.dirname(g_module.root_path)]
    paths += get_required_paths()
    self.recurse(paths)


def patch_parse_args(class_ = Options.OptionsContext, funcname = "parse_args"):
    func = getattr(class_,funcname)
    def patched(self):
        options(self)
        func(self)
    setattr(class_, funcname, patched)


def prelude():
    "Prelude function to invoke symwaf2ic before any waf commands."
    # patch run_commands-method  
    funcname = "run_commands"
    setattr(Scripting, funcname,
            prepend_entry_point(getattr(Scripting, funcname)))

    # patch default execute function of Context
    # so that all required wscripts will be recursed into
    setattr(Context.Context, "execute", _patched_execute)

    # Do not climb the directory when we set up the symwaf2ic top directory
    Scripting.no_climb_commands.append(SETUP_CMD)

    # Patch OptionsContext to include 
    patch_parse_args()

    assert_toplevel_wscript()


def assert_toplevel_wscript():
    # if there is no wscript and there is a setup command present, create the default wscript
    if Context.WSCRIPT_FILE not in os.listdir(os.getcwd()):
        if SETUP_CMD in sys.argv:
            with open(os.path.join(os.getcwd(), Context.WSCRIPT_FILE), "w") as wf:
                wf.write(_toplevel_wscript_contents)

        else:
            print "ERROR: No wscript present in current directory. In order to initialize"+\
                    " the symwaf2ic toplevel (and the corresponding wscript), please issue "+\
                    "the 'setup' command."
            sys.exit(1)




##################
# Regular Script #
##################


LOCKFILE = ".symwaf2ic.lock"
CFGFOLDER = ".symwaf2ic"

SETUP_CMD = "setup"

# configuration to be shared between commands of symwaf2ic
storage = None

def entry_point():
    "Entry point for symwaf2ic code execution before waf workflow."
    global storage
    storage = Storage(None)
    storage.paths = []
    storage.projects = set()

    Logs.debug("Reached entry point.")
    Scripting.run_command("symwaf2ic")
    Scripting.run_command("dependency_resolution")


class Symwaf2icError(Errors.WafError):
    pass

class Storage(object):
    def __repr__(self):
        return "[{0}]".format(", ".join(("{0}: {1}".format(
            name, repr(getattr(self, name))) for name in dir(self)
                                             if not name.startswith("_"))))

    def __init__(self, default):
        setattr(self,"_default", default)

    def __getattr__(self, name):
        setattr(self, name, getattr(self, "_default"))
        return getattr(self, name)


def add_required_path(path):
    if path not in storage.paths:
        storage.paths.append(path)


def get_required_paths():
    return storage.paths


def options(opt):
    gr = opt.add_option_group("Symwaf2ic options")
    gr.add_option(
            "--project", dest="projects", action="append",
            help="Declare the specified project as required build target "+\
                 "(Can be specified several times).")

class MainContext(Context.Context):
    "(Automatically executed on each invokation of waf.)"

    cmd = "symwaf2ic"

    def execute(self):
        Logs.info("Starting up symwaf2ic")

        self.set_toplevel()
        self.setup_repo_tool()

    def set_toplevel(self):
        Logs.debug("Finding toplevel")
        if SETUP_CMD in sys.argv:
            Logs.info("Setting up symwaf2ic toplevel.")
            storage.toplevel = self.path

            # create lockfile indicating the toplevel directory
            storage.lockfile = storage.toplevel.make_node(LOCKFILE)
            storage.lockfile.write("")

            sys.argv.remove(SETUP_CMD)

        else:
            cur_dir = self.path
            while cur_dir.find_node(LOCKFILE) is None:
                cur_dir = cur_dir.parent
                if cur_dir is None:
                    raise Symwaf2icError("Could not find symwaf2ic lockfile. Please run 'setup' first.")
            storage.toplevel = cur_dir
            storage.lockfile = storage.toplevel.find_node(LOCKFILE)

        Logs.info("Toplevel set to: {0}".format(storage.toplevel.abspath()))

        self.parse_command_line()
        # check if user supplied projects via command line
        if storage.projects is not None:
            # write them to lockfile
            storage.lockfile.write("\n".join(storage.projects))
        else:
            # no project specified, read them from lockfile
            storage.projects = [ line.strip()
                    for line in storage.lockfile.read().split("\n") if len(line) > 0 ]

        storage.config_node = storage.toplevel.make_node(CFGFOLDER)
        storage.config_node.mkdir()


    def setup_repo_tool(self):
        repoconf = storage.config_node.make_node( "mr_conf" )
        repoconf.mkdir()
        storage.repo_tool = mr.MR(self, top=storage.toplevel, cfg=repoconf, clear_log=True)


    def parse_command_line(self):
        """Parse command line to extract commands directed at symwaf2ic before
        the regular option-parsing by waf can be done.

        """
        self.parser = argparse.ArgumentParser()

        # parse command line options specified
        symwaf2ic_options(self)
        opts, unkown = self.parser.parse_known_args(sys.argv[1:])
        storage.projects = opts.projects

    # wrapper functions to use argparse even though waf still uses optparse
    def add_option(self, *k, **kw):
        # fixes for optparse -> argparse compatability
        if "type" in kw:
            kw["type"] = eval(kw["type"])
        self.parser.add_argument(*k, **kw)

    # Since we are only interested in the arguments themselves and provide no output
    # in the depdency system, optparse's OptionGropus are irrelevent, since they only
    # serve to produce nicer help messages.
    def add_option_group(self, *k, **kw):
        return self

    def get_option_group(self, opt_str):
        return self



class DependencyContext(Context.Context):
    "(Automatically executed on each invokation of waf.)"

    cmd = "dependency_resolution"
    fun = "depends"

    def __call__(self, project, subfolder="", branch=None):
        Logs.info("Required by {script}: {project}{branch}{subfolder}".format(
                project=project,
                subfolder="" if len(subfolder) == 0 else " ({0})".format(subfolder),
                branch="" if branch is None else "@{0}".format(branch),
                script=self.cur_script.path_from(storage.toplevel)
            ))

        # path = storage.repo_tool.checkout_project(project, branch)

    def execute(self):
        # Only recurse into the toplevel wscript because all dependencies will
        # be defined from there. Also it shall be possible to have no dependencies.
        self.recurse([os.path.dirname(Context.g_module.root_path)], mandatory=False)

    def _recurse_projects(self):
        "Recurse all currently targetted projects."
        Logs.info("Requiring toplevel projects: {0}".format( ", ".join(storage.projects)))
        if storage.projects is None or len(storage.projects) == 0:
            raise Symwaf2icError("Please specify target projects to build via --project.")


class DistcleanContext(Context.Context):
    cmd = "distclean"

    def execute(self):
        # make sure no other commands are being run
        if not Options.commands:
            shutil.rmtree(storage.config_node.abspath(), ignore_errors=True)
            os.remove(storage.lockfile.abspath())


_toplevel_wscript_contents = """
# default wscript
# can be modified/deleted if needed

def depends(dep):
    dep._recurse_projects()

"""
