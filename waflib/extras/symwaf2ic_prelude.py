#!/usr/bin/env python
# encoding: utf-8

# Prelude of for symwaf2ic, doing the Monkey patching waf sources
# Please use:
# --prelude=$'\tfrom waflib.extras.symwaf2ic import prelude; prelude()'

import os
import shutil
import sys
from waflib import Build, Context, Logs, Options, Scripting, TaskGen
from waflib.extras import symwaf2ic
from waflib.extras import mr


def prepend_entry_point(func):
    "Prepend our entry point to function execution."
    def patched():
        # from waflib.extras.symwaf2ic import entry_point
        entry_point()
        func()
    return patched


def patch_parse_args(class_=Options.OptionsContext, funcname="parse_args"):
    func = getattr(class_, funcname)

    def parse_args(self):
        symwaf2ic.options(self)
        func(self)
    setattr(class_, funcname, parse_args)


def patch_build_context():
    def post_group(self):
        """
        Post the task generators from the group indexed by self.cur, used
        by :py:meth:`waflib.Build.BuildContext.get_build_iterator`
        """
        def post_tg(tg):
            try:
                f = tg.post
            except AttributeError:
                pass
            else:
                f()

        tg_filter = lambda tg: True
        ln = self.launch_node()
        if self.targets == '*':
            pass
        elif self.targets and self.cur >= self._min_grp:
            for tg in self._exact_tg:
                post_tg(tg)
            return
        elif ln.is_child_of(self.bldnode):
            Logs.warn('Building from the build directory, forcing --targets=*')
            tg_filter = lambda tg: tg.path.is_child_of(self.srcnode)
        elif not ln.is_child_of(self.srcnode):
            Logs.warn('CWD %s is not under %s, forcing --targets=* (run '
                      'distclean?)' % (ln.abspath(), self.srcnode.abspath()))
            tg_filter = lambda tg: tg.path.is_child_of(self.srcnode)
        else:
            toplevel = self.root.find_node(symwaf2ic.storage.toplevel)
            paths = [toplevel.find_dir(p.directory)
                     for p in symwaf2ic.get_projects()]
            # If no projects are set apply waf default behavior
            if not paths:
                paths = [ln]
            tg_filter = lambda tg: any(tg.path.is_child_of(p) for p in paths)

        for tg in self.groups[self.cur]:
            if tg_filter(tg):
                post_tg(tg)

    old_create_task = TaskGen.task_gen.create_task

    def create_task(self, name, src=None, tgt=None):
        """New create task"""
        task = old_create_task(self, name, src, tgt)
        task_list = self.to_list(getattr(self, "run_after", []))
        for task_name in task_list:
            for t in self.bld.get_tgen_by_name(task_name).tasks:
                task.set_run_after(t)
        return task

    Build.BuildContext.post_group = post_group
    TaskGen.task_gen.create_task = create_task


def patch_context():
    """Patch Context.Context.recurse to do the recursing on first invocation,
    since too many commands etc. tend to reimplement the execute method, but as
    of this writing none touched the recurse function.

    Furthermore, for every command executed a new Context-instance is created,
    it is therefore assured that the depdency paths will also be recursed.
    """

    orig_init = getattr(Context.Context, "__init__")
    orig_recurse = getattr(Context.Context, "recurse")

    def init(self, *k, **kw):
        # to find out if recurse has been run before or not
        self._first_recursion = True
        self.symwaf2ic_version = symwaf2ic.SYMWAF2IC_VERSION
        orig_init(self, *k, **kw)
    init.__name__ = "__init__"

    def recurse(self, paths, *k, **kw):
        if not self._first_recursion:
            # if we are not in the first run, run as normal
            orig_recurse(self, paths, *k, **kw)
        else:
            self._first_recursion = False

            # run all required dependencies (not mandatory)
            kwdep = kw.copy() # KHS: but don't overwrite default behaviour (./waf non-existing-command should fail)
            kwdep.update({'mandatory':False})
            dep_paths = symwaf2ic.get_required_paths()
            orig_recurse(self, dep_paths, *k, **kwdep)

            # and then the desired toplevel recurse..
            orig_recurse(self, paths, *k, **kw)

    setattr(Context.Context, "__init__", init)
    setattr(Context.Context, "recurse", recurse)


def distclean(ctx):
    # make sure no other commands are being run (otherwise: don't clean)
    if not Options.commands:
        cfg_folder = os.path.join(os.getcwd(), symwaf2ic.CFGFOLDER)
        shutil.rmtree(cfg_folder, ignore_errors=True)
        # try:
            # os.remove(os.path.join(os.getcwd(), LOCKFILE))
        # except OSError:
            # pass

        for f in os.listdir(os.getcwd()):
            if f.startswith(symwaf2ic.FILEPREFIX):
                try:
                    os.remove(os.path.join(os.getcwd(), f))
                except OSError:
                    pass


def patch_distclean(module=Scripting, name="distclean"):
    func = getattr(module, name)

    def patched(*k, **kw):
        distclean(*k, **kw)
        func(*k, **kw)
    # adjust name attribute (since waf operates on the .__name__ level)
    setattr(patched, "__name__", name)
    setattr(module, name, patched)


def assert_toplevel_wscript():
    # if there is no wscript and there is a setup command present, create
    # the default wscript
    if Context.WSCRIPT_FILE not in os.listdir(os.getcwd()):
        if (symwaf2ic.SETUP_CMD in sys.argv
                or symwaf2ic.is_help_requested() or len(sys.argv) == 1):
            wscipt = os.path.join(os.getcwd(), Context.WSCRIPT_FILE)
            with open(wscipt, "w") as wf:
                wf.write(_toplevel_wscript_contents)

        else:
            print "ERROR: No wscript present in current directory. In order "\
                  "to initialize the symwaf2ic toplevel (and the "\
                  "corresponding wscript), please issue the 'setup' command."
            sys.exit(1)


def entry_point():
    "Entry point for symwaf2ic code execution before waf workflow."
    symwaf2ic.init_storage()

    Logs.debug("Reached entry point.")

    Scripting.run_command("_symwaf2ic")
    Scripting.run_command("_dependency_resolution")


def run_symwaf2ic():
    "Return whether or not to run symwaf2ic."
    return not set(symwaf2ic.NO_EXECUTE_CMDS) & set(sys.argv)


def prelude():
    "Prelude function to invoke symwaf2ic before any waf commands."

    # patch default execute function of Context
    # so that all required wscripts will be recursed into
    # match the nameof the old function
    # setattr(_patched_execute, "__name__", "execute")
    # setattr(Context.Context, "execute", _patched_execute)
    # (now done via patch_execute())

    # Do not climb the directory when we set up the symwaf2ic top directory
    Scripting.no_climb_commands.append(symwaf2ic.SETUP_CMD)

    # Patch OptionsContext to include options for symwaf2ic
    patch_parse_args()

    # Patch distclean command to remove symwaf2ic files as well
    patch_distclean()

    # Patch the build context to post only nodes below the selected projects
    # and directoris
    patch_build_context()

    # patch mr config to get the repo_tool
    setattr(mr, "get_repo_tool", lambda: symwaf2ic.storage.repo_tool)

    # if the user specifies the help option, our own argparser
    # would catch that and only print the symwaf2ic help
    # Since the normal workflow will not be executed and we can omit everything
    if run_symwaf2ic():
        assert_toplevel_wscript()
        # patch run_commands-method
        funcname = "run_commands"
        setattr(Scripting, funcname,
                prepend_entry_point(getattr(Scripting, funcname)))

        # patch recurse mode of Context.Context to also recurse into
        #dependencies on first invocation
        patch_context()

    else:
        # make sure toplevel wscript is present if --help specified
        if symwaf2ic.is_help_requested():
            assert_toplevel_wscript()

_toplevel_wscript_contents = """
# default wscript
# can be modified/deleted if needed

def depends(dep):
    dep._recurse_projects()

def configure(cfg):
    pass

def build(bld):
    pass

def doc(dox):
    pass
"""
