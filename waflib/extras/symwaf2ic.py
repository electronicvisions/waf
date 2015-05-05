#!/usr/bin/env python
# encoding: utf-8

"Symwaf2ic package"
# waf --zones=symwaf2ic, symwaf2ic_options, dependency

import os
import sys
import argparse
import shutil

import json
from collections import defaultdict, deque

from waflib import Build, Context, Errors, Logs, Utils, Options
from waflib.extras import mr

import symwaf2ic_misc as misc


#############
# CONSTANTS #
#############

SYMWAF2IC_VERSION = 1

FILEPREFIX = ".symwaf2ic"
CFGFOLDER = ".symwaf2ic"
LOCKFILE = FILEPREFIX + ".conf.json"

SETUP_CMD = "setup"
# upon which commands shall the config be written
STORE_CMDS = set([SETUP_CMD, "configure"])

# items to strip from command line before parsing with own parser
HELP_CMDS = "-h --help show_repos".split()
STRIP_FROM_PARSER = HELP_CMDS
# commands which will cause symwaf2ic to be disabled when specified
NO_EXECUTE_CMDS = "distclean".split()


# configuration to be shared between commands of symwaf2ic
storage = None


def init_storage():
    "Entry point for symwaf2ic code execution before waf workflow."
    global storage
    storage = Storage(None)
    storage.paths = []


def get_required_paths():
    return storage.paths

def get_projects():
    for p in storage.projects:
        yield Project(**p)


def count_projects():
    return len(storage.projects)


def get_toplevel_path():
    return storage.toplevel


def is_help_requested():
    return set(sys.argv) & set(HELP_CMDS)


class Symwaf2icError(Errors.WafError):
    pass


class Storage(object):
    def __repr__(self):
        tmp = ["{0}: {1}".format(name, repr(getattr(self, name)))
               for name in dir(self) if not name.startswith("_")]
        return "[{0}]".format(", ".join(tmp))

    def __init__(self, default):
        setattr(self, "_default", default)

    def __getattr__(self, name):
        setattr(self, name, getattr(self, "_default"))
        return getattr(self, name)


class Project(object):
    def __init__(self, project, branch, directory):
        self.project = project
        self.directory = str(directory)
        self.branch = branch

    def __str__(self):
        if self.project:
            ret = self.project
            if self.branch:
                ret += " {on " + self.branch + "}"
        else:
            ret = self.directory
        return ret

    @staticmethod
    def from_project_opt(arg):
        #if '/' in arg:
        #    Logs.warn("The project specification 'repo/branch' is deprecated, please use 'repo@branch' instead. I.e. no more slashes!") # \nYou can now even use repo@branch@subdir") Does not work
        #    arg=arg.replace('/','@')
        def splitprj(arg):
            r = arg.split('@') # prj, branch, dir
            if not r[0]: raise # default opt parse message
            if len(r) == 1: return r[0], None, r[0]
            if len(r) == 2: return r[0], r[1] or None , r[0]
            #if len(r) == 3: return r[0], r[1] or None, os.path.join(r[0], r[2]) # UNTESTED: specifying project and directory in one step is not jet implemented (dir option is ignored if project is set)
            raise Symwaf2icError("Bad argument to project: '{}', use repository@branch instead.".format(arg))

        p, b, d = splitprj(arg)
        return {'project' : p, "directory" : d, 'branch' : b}

    @staticmethod
    def from_dir_opt(arg):
        return {'project' : None, "directory" : arg, 'branch' : None}


def options(opt):
    is_symwaf2ic = isinstance(opt, OptionParserContext)

    gr = opt.add_option_group("Symwaf2ic options")
    gr.add_option(
            "--project", dest="projects", action="append", default=[],
            type=Project.from_project_opt if is_symwaf2ic else str,
            metavar="REPOSITORY[@BRANCH]",
            help="Declare the specified project (repository) as required build target . Branches can be specified by appending '@branch', e.g. --project halbe@dev. (Can be specified several times.)"
    )
    gr.add_option(
            "--directory", dest="projects", action="append",
            type=Project.from_dir_opt if is_symwaf2ic else str,
            metavar="PATH",
            help="Make waf to recurse into the given folders. (Can be specified several times.)"
    )

    # KHS wanted behaviour: but not supported by waf optparse legacy.
    #gr.add_option(
    #        "--update-branches", dest="update_branches", nargs='?',
    #        default=False, const=True, type=misc.bool_or_string, choices = [ False, True, 'force' ],
    #        help="Activate branch tracking (e.g., when updating repositories). Set 'force' to force branch update."
    #)
    gr.add_option(
            "--update-branches", dest="update_branches",
            default=False, type='choice', choices="soft force".split(), # false is not a choice, its the default and bool('false') is true
            help="Activate branch tracking (e.g., when updating repositories). If specified set to soft or force (the latter deletes local changes)."
    )

    gr.add_option(
            "--repo-db-url", dest="repo_db_url", action="store",
            help="URL for the repository containing the database with information about all other repositories.",
            default="git@gitviz.kip.uni-heidelberg.de:projects.git"
            )
    gr.add_option(
            "--repo-db-type", dest="repo_db_type", action="store",
            help="Type of the repository containting the repo DB (default: 'git'). Can also be 'wget'.",
            default="git"
            )
    gr.add_option(
            "--write-dot-file", dest="write_dot_file", action="store",
            help="Stores graph in a dot file",
            default=None
            )


class Symwaf2icContext(Context.Context):
    cmd = None

    def __init__(self, *k, **kw):
        super(Symwaf2icContext, self).__init__(*k, **kw)
        if storage.toplevel:
            self.toplevel = self.root.find_node(storage.toplevel)
        else:
            self.toplevel = None


# NOTE: This is only a dummy class to make setup show up in the help
class SetupContext(Symwaf2icContext):
    __doc__ = "set up symwaf2ic (execute in desired toplevel directory)"
    cmd = SETUP_CMD

    def execute(self):
        pass


class MainContext(Symwaf2icContext):
    __doc__ = "(Automatically executed on each invokation of waf.)"

    cmd = "_symwaf2ic"

    def __init__(self, *k, **kw):
        super(Symwaf2icContext, self).__init__(*k, **kw)

    def execute(self):
        Logs.debug("symwaf2ic: Starting up symwaf2ic")

        self.set_toplevel()
        self.get_config()
        self.setup_repo_tool()

    def get_config(self):
        """ Load the config from storage config
        """
        Logs.debug("symwaf2ic: load config from storage and superseed with commandline")

        storage.config_node = self.toplevel.make_node(CFGFOLDER)
        storage.config_node.mkdir()

        # projects are only set during setup phase
        options = OptionParserContext(parsername="Symwaf2icSetupParser")
        cmdopts = options.parse_args()

        if SETUP_CMD in sys.argv:
            # already write projects to store
            config = { "projects" : cmdopts.projects,
                       "preserved_options" : [],
                       "setup_argv" : options.get_unused_args(),
                       "setup_raw_argv" : sys.argv,
                       "setup_options" : vars(cmdopts),
                       "saved_paths" : None }
            storage.lockfile.write(json.dumps(config, indent=4))
        else:
            config = json.load(storage.lockfile)

        storage.save = config.keys()
        for k, v in config.iteritems():
            setattr(storage, k, v)

        if not SETUP_CMD in sys.argv:
            # TODO KHS shouldn't we compare with cmdopts instead of sys.argv, --verbose/-v for example?
            args = [o for o in storage.preserved_options if not o in sys.argv]
            if args:
                Logs.info("symwaf2ic: Using options from setup call: " + " ".join(args))
            sys.argv += args

        # TODO KHS: is this correct, what are the current options, those on the commandline, or the "total" of options?
        storage.current_options = vars(cmdopts)

        self.repo_db_url = cmdopts.repo_db_url
        self.repo_db_type = cmdopts.repo_db_type

    def init_toplevel(self):
        Logs.debug("symwaf2ic: Setting up symwaf2ic toplevel.")

        # Since we need the toplevel in several commands, only store the path
        storage.toplevel = self.path.abspath()
        self.toplevel = self.root.find_node(storage.toplevel)

        # create lockfile indicating the toplevel directory
        storage.lockfile = self.path.make_node(LOCKFILE)
        storage.lockfile.write("")

        # sys.argv.remove(SETUP_CMD)

    def set_toplevel(self):
        Logs.debug("symwaf2ic: Finding toplevel")
        if SETUP_CMD in sys.argv:
            self.init_toplevel()
        else:
            cur_dir = self.root.find_node(os.getcwd())
            while cur_dir.find_node(LOCKFILE) is None:
                cur_dir = cur_dir.parent
                if cur_dir is None:
                    self.init_toplevel()
                    cur_dir = self.root.find_node(os.getcwd())
                    sys.argv.append(SETUP_CMD)
                    #raise Symwaf2icError("Could not find symwaf2ic lockfile. Please run 'setup' first.")
            # be sure not to create new nodes
            self.toplevel = self.root.find_node(cur_dir.abspath())
            storage.toplevel = self.toplevel.abspath()
            storage.lockfile = self.toplevel.find_node(LOCKFILE)

        Logs.info("Toplevel set to: {0}".format(storage.toplevel))


    def setup_repo_tool(self):
        Logs.debug("symwaf2ic: Setup repo tool (mr)")
        repoconf = storage.config_node.make_node( "mr_conf" )
        repoconf.mkdir()
        storage.repo_tool = mr.MR(self, self.repo_db_url, self.repo_db_type, top=self.toplevel, cfg=repoconf, clear_log=True)


class OptionParserContext(Symwaf2icContext):
    cmd = None
    fun = "options"

    def __init__(self, *k, **kw):
        super(OptionParserContext, self).__init__(*k, **kw)

        # KHS this is called multiple times... The following might help improving/debugging that.
        parsername=kw.get("parsername", "unnamed symwaf2ic parser")
        self.parsername = parsername
        self.parse_cnt = 0
        Logs.debug("symwaf2ic_options: initializing options parser: %s" % self.parsername)

        self.parser = argparse.ArgumentParser()
        self._add_waf_options()
        self._first_recursion = False # disable symwaf2ic recursion
        self.loaded = set()
        self.used_args = []
        self.unused_args = []

    def load(self, tool_list, *k, **kw):
        """
        Load a Waf tool as a module, and try calling the function named :py:const:`waflib.Context.Context.fun` from it.
        A ``tooldir`` value may be provided as a list of module paths.

        :type tool_list: list of string or space-separated string
        :param tool_list: list of Waf tools to use
        """
        tools = Utils.to_list(tool_list)
        for tool in tools:
            if tool in self.loaded:
                continue
            super(Symwaf2icContext, self).load(tool, *k, **kw)
            self.loaded.add(tool)

    def _parse_type(self, data_):
            if data_['type'] == 'string':
                data_['type'] = str
            elif data_['type'] == 'choice':
                del data_['type']
            else:
                data_['type'] = eval(data_['type'])

    # wrapper functions to use argparse even though waf still uses optparse
    def add_option(self, *k, **kw):
        # fixes for optparse -> argparse compatability (NOTE: Definitively not be complete)
        if "type" in kw:
            if isinstance(kw["type"], basestring):
                self._parse_type(kw)
        if "callback" in kw:
            Logs.warn("Option '{}' was ignored during setup call, because it used callback keyword".format(k[0]))
            #--disable-doxygen
            return
        if storage.options:
            opt = k[0]
            while opt.startswith(self.parser.prefix_chars):
                opt = opt[len(self.parser.prefix_chars):]
            if opt in storage.options:
                kw["default"] = storage.options[opt]
        self.parser.add_argument(*k, **kw)

    def add_withoption(self, *k, **kw):
        # just pass on
        self.parser.add_withargument(*k, **kw)

    # Since we are only interested in the arguments themselves and provide no output
    # in the dependency system, optparse's OptionGroups are irrelevent, since they only
    # serve to produce nicer help messages.
    def add_option_group(self, *k, **kw):
        return self

    def get_option_group(self, opt_str):
        return self

    def parse_args(self, path = None, argv=None):
        """Parse args from wscript path (or command line if path is None)

        This is done to extract commands directed at symwaf2ic before
        the regular option-parsing by waf can be done as well as have options
        affect the dependency resolution.

        """
        self.parse_cnt = self.parse_cnt + 1
        Logs.debug("symwaf2ic_options: parsing args for %s: %d" % (self.parsername, self.parse_cnt))

        if argv is None:
            argv = sys.argv

        if path is None:
            # parse command line options specified by symwaf2ic
            options(self)
        else:
            self.recurse([path])

        # avoid things like -h/--help that would only confuse the parser
        cmdline = [a for a in argv[1:] if not a in STRIP_FROM_PARSER]

        opts, unknown = self.parser.parse_known_args(cmdline)
        self.used_args = [a for a in cmdline if not a in unknown]
        self.unused_args = unknown
        return opts

    def get_used_args(self):
        return self.used_args

    def get_unused_args(self):
        return self.unused_args

    def _add_waf_options(self):
        Logs.debug("symwaf2ic_options: add waf options")
        ctx = Options.OptionsContext()
        opt = ctx.parser

        def copy_option(argparser, opt):
            args = dict((a, getattr(opt, a)) for a in opt.ATTRS if getattr(opt, a))
            if args.get('action', '') in ('version', 'help'):
                return
            if 'type' in args:
                self._parse_type(args)
            opt_names = opt._short_opts + opt._long_opts
            argparser.add_argument(*opt_names, **args)

        for option in opt.option_list:
            Logs.debug("symwaf2ic_options: waf opt: " + str(option))
            copy_option(self.parser, option)

        for group in opt.option_groups:
            Logs.debug("symwaf2ic_options: waf grp: " + str(group.title))
            arg_group = self.parser.add_argument_group(
                group.title, group.description)
            for option in group.option_list:
                copy_option(arg_group, option)

def topological_sort(dependencies):
    """Pseudo topological sort of dependencies, that allows cycles"""
    # Flags for topological sort of projects
    NOT_VISITED, ACTIVE, CYCLE, FINISHED = 0, 1, 2, 3

    result = []
    predecessor = dict()
    color = dict(((node, NOT_VISITED) for node in dependencies))

    def visit(node):
        color[node] = ACTIVE
        for dependency in dependencies[node]:
            c = color[dependency]
            if c == NOT_VISITED:
                predecessor[dependency] = node
                visit(dependency)
            elif c == ACTIVE:
                tmp = predecessor[node]
                cycle = [node, tmp]
                while tmp != dependency:
                    tmp = predecessor[tmp]
                    cycle.append(tmp)
                if Logs.verbose > 1:
                    Logs.info("Cyclic dependency between wscripts: " + ", ".join(cycle))

        color[node] = FINISHED
        result.append(node)

    for node in dependencies:
        if color[node] == NOT_VISITED:
            visit(node)

    assert len(result) == len(dependencies)
    return result


class DependencyContext(Symwaf2icContext):
    __doc__ = "(Automatically executed on each invokation of waf.)"

    cmd = "_dependency_resolution"
    fun = "depends"

    def __init__(self, *k, **kw):
        super(DependencyContext, self).__init__(*k, **kw)
        self.options_parser = OptionParserContext(parsername="DependencyParser")
        self.update_branches = SETUP_CMD in sys.argv and storage.setup_options["update_branches"]
        self.write_dot_file  = storage.current_options["write_dot_file"]
        # Dependency graph
        self.dependencies = defaultdict(list)
        # Queue for breadth-first search
        self.to_recurse = deque()

    def __call__(self, project, subfolder="", branch=None):
        Logs.debug("dependency: Required by {script}: {project}{branch}{subfolder}".format(
                    project=project,
                    subfolder="" if len(subfolder) == 0 else " ({0})".format(subfolder),
                    branch="" if branch is None else "@{0}".format(branch),
                    script=self.cur_script.path_from(self.toplevel)
                ))

        required_from = self.cur_script.parent.path_from(self.toplevel)
        path = storage.repo_tool.checkout_project(project, required_from, branch, self.update_branches)

        if len(subfolder) > 0:
            path = os.path.join(path, subfolder)

        if not self.toplevel.find_dir(path):
            raise Symwaf2icError("Folder '{0}' not found in project {1}".format(subfolder, project))

        # For topology order of deps
        self._add_required_path(path, required_from)

    def execute(self):
        # dont recurse into all already dependency directories again
        self._first_recursion = False

        info = [str(p) for p in get_projects()]
        Logs.debug("dependency: Required from toplevel: {0}".format( ", ".join(info)))

        # Color map for topological sort
        self.visited = defaultdict(lambda: self.NOT_VISITED)
        # Helper to print cycles nicely
        self.predecessors = {}

        # If we are running from a subfolder we have to add this folder to
        # required scripts list
        self._add_required_path(self.path.path_from(self.toplevel))

        self._recurse_projects()

        # KHS: changes self.path to arbitrary value, now back it up
        path_prior_recurse = self.path
        while self.to_recurse:
            rpath = self.to_recurse.popleft()
            self.recurse([rpath], mandatory=False)
        self.path=path_prior_recurse

        storage.paths = topological_sort(self.dependencies)

        # KHS: get top directories/repos of dependencies to add them to
        # .git/info/exclude in case toplevel is under version control
        gitnode = self.toplevel.find_node('.git')
        if gitnode:
            self.writeDotGitInfoExclude(gitnode, self.toplevel.abspath(), storage.paths)

        unused_args = [x for x in
                       self.options_parser.get_unused_args() if x[0] == '-']
        if unused_args:
            raise Symwaf2icError("Unkown options: %s" % ", ".join(unused_args))

        if self._shall_store_config():
            if SETUP_CMD in sys.argv:
                storage.preserved_options = self.options_parser.get_used_args()
                self._clear_config_cache()
            storage.saved_paths = storage.paths
            self._store_config()
        elif (storage.saved_paths is not None
                and storage.saved_paths != storage.paths
                and not is_help_requested()):
            raise Symwaf2icError("Dependency information changed. Please rerun "
                                 "'setup' or 'configure' before continuing!")

        storage.repo_tool.clean_projects()
        self._print_branch_missmatches()

        if self.write_dot_file:
            self._dump_dot_file(self.write_dot_file)

    #[2014-06-24 10:42:01] KHS
    def writeDotGitInfoExclude(self, gitnode, toplevel, paths):
        '''if there is a toplevel git repo we want to exclude repos checked out by waf'''
        # this means all subfolders of toplevel which contain dependencies

        # the dependency pathes all begin with 'toplevel/'
        lentop=len(toplevel) + 1 # toplevel does not end with /
        ignores=set()
        for p in paths:
            p = p[lentop:]              # make it relative to toplevel (remove toplevel/abspath part)
            p = p.split('/',1)[0]       # we want to exclude subfolders containing deps completely
            if p: ignores.add(p + '/')  # they are all directories

        # some more symwaf2ic generated stuff
        ignores.update([
            '.waf-*',
            '.lock-waf_*_build',
            '.symwaf2ic*',
            'build/',
        ])
        ignores_avail=set()

        # get already existant ignores
        git_info_exclude_node = gitnode.find_node("info/exclude")
        if git_info_exclude_node:
            for line in git_info_exclude_node.read().split('\n'):
                if not line: continue
                if line.startswith('#'): continue
                ignores_avail.add(line)
        else:
            git_info_exclude_node = gitnode.make_node("info/exclude")

        # add missing ignores
        ignores = ignores - ignores_avail
        data = '\n'.join(ignores)
        if data:
            Logs.info("Appending git exclude rules to '{}'".format(git_info_exclude_node.abspath()))
            data=data+'\n'
            print data
            git_info_exclude_node.write(data,'a')

    def pre_recurse(self, node):
        super(DependencyContext, self).pre_recurse(node)
        self.options = self.options_parser.parse_args(
                self.path.abspath(), argv=storage.setup_argv)

    def post_recurse(self, node):
        super(DependencyContext, self).post_recurse(node)

    def _print_branch_missmatches(self):
        for x in storage.repo_tool.get_wrong_branches():
            Logs.warn('On-disk project "%s" on branch "%s", '
                      'but requiring "%s".' % x)

    def _clear_config_cache(self):
        out_dir = self.root.find_dir(Context.out_dir)
        if out_dir:
            cache_dir = out_dir.find_dir(Build.CACHE_DIR)
            if cache_dir:
                shutil.rmtree(cache_dir.abspath())

    def _add_required_path(self, path, predecessor=None):
        path = self.toplevel.find_node(path).abspath()
        self.dependencies[path]
        if not predecessor is None:
            predecessor = self.toplevel.find_node(predecessor).abspath()
            self.dependencies[predecessor].append(path)
        self.to_recurse.append(path)

    def _recurse_projects(self):
        "Recurse all currently targetted projects."
        if len(storage.paths) == 0 and count_projects() == 0:
            Logs.warn("Please specify target projects to build during"
                      "'setup' via --project or --directory.")
            return

        for project in get_projects():
            if project.project is None:
                self._add_required_path(project.directory)
            else:
                try:
                    path = storage.repo_tool.checkout_project(
                            project=project.project,
                            parent_path="project option",
                            branch=project.branch,
                            update_branch = self.update_branches)
                    self._add_required_path(path)
                except KeyError:
                    Logs.warn("Project '{!s}' not found and will be ignored".format(project))

    def _shall_store_config(self):
        "Determines if the config shall be written"
        return not STORE_CMDS.isdisjoint(set(sys.argv))

    def _store_config(self):
        config = {}
        for k in storage.save:
            config[k] = getattr(storage, k, None)
        storage.lockfile.write(json.dumps(config, indent=4) + "\n")


    def _dump_dot_file(self, filename):
        prefix = len(os.path.commonprefix(self.dependencies.keys()))
        with open(filename, 'w') as outfile:
            outfile.write("digraph {\n")
            for source, targets in self.dependencies.iteritems():
                s = source[prefix:]
                for target in targets:
                    t = target[prefix:]
                    outfile.write('"{}" -> "{}";\n'.format(s, t))
            outfile.write("}")

# Currently only kept for posterity
# import types
# import inspect


# TODO: Delete Me
# # which cmds should not have their execute patched
# NO_PATCH_CMDS = "dependeny_resolution".split()

# # utils for `patch_execute`
# def find_indent(s):
    # i = 0
    # while s[:(i+1)].isspace():
        # i += 1
    # return i


# def remove_indent(lines):
    # n_indent = find_indent(lines[0])
    # indent = lines[0][:n_indent]
    # newlines = [s[n_indent:] for s in lines]
    # return newlines, indent

# _execute_insertion="""
# # the rest of the wscripts do not have to include the specified
# paths = get_required_paths()
# self.recurse(paths, mandatory = False)
# print 'PATCHED EXECUTE'

# """.split("\n")

# def patch_context_meta():
    # """Monkey patch store_context to modify the sourcecode of execute()
    # method whenever a class is generated.

    # """
    # meta        = Context.store_context
    # method_name = "execute"
    # insertion   = _execute_insertion

    # class new_meta(meta):
        # def __new__(cls, name, bases, dct):
            # perform_patching = not ("cmd" in dict and dict["cmd"] in NO_PATCH_CMDS)
            # perform_patching = perform_patching and method_name in dict

            # if perform_patching:
                # method = dict[method_name]
                # sourcelines = inspect.getsource(method).split("\n")

                # # remove indent so that we can recompile without error
                # sourcelines, indent = remove_indent(sourcelines)

                # # NOTE: We assume the first argument to be called 'self'
                # #       Which is reasonable
                # #       Also we assume the header to be contained in one line,
                # #       which for execute is also reasonable since it should
                # #       always be invoked with no arguments
                # header = sourcelines[0]
                # content = sourcelines[1:]

                # for i, l in enumerate(content):
                    # if "self.recurse(" in l:
                        # # we found the recurse statement, insert the other statements below
                        # i += 1
                        # for insertline in reversed(insertion):
                            # content.insert(i, insertline)
                        # break

                # new_source = "\n".join([header] + content)
                # exec compile(new_source, '<string>', 'exec') in globals(), locals()

                # dict[method_name] = eval(method_name)
                # dict["symwaf2ic_patched"] = True

            # return super(new_meta,meta).__new__(cls, name, bases, dict)

    # # # NOTE: Reimplementation of waf code (hack)
    # # created_classes = []
    # # while Context.classes.count() > 0:
        # # created_classes.append(Context.classes.pop())

    # # Context.ctx = new_meta('ctx', (object,), {})


# # TODO: DELETEME
# def patch_execute(
        # meta=Context.store_context,
        # meta_method="__new__",
        # method_name="execute",
        # insertion=_execute_insertion
    # ):
    # """Monkey patch store_context to modify the sourcecode of execute()
    # method whenever a class is generated.

    # """
    # # make sure only undefined methods are overwritten
    # if getattr(meta, meta_method) != getattr(type, meta_method):
        # raise Symwaf2icError("FATAL: Would overwrite defined waf method with unkown consquences!")

    # def new_meta(cls, cls2, name, bases, dict):
        # perform_patching = not ("cmd" in dict and dict["cmd"] in NO_PATCH_CMDS)
        # perform_patching = perform_patching and method_name in dict

        # if perform_patching:
            # method = dict[method_name]
            # sourcelines = inspect.getsource(method).split("\n")

            # # remove indent so that we can recompile without error
            # sourcelines, indent = remove_indent(sourcelines)

            # # NOTE: We assume the first argument to be called 'self'
            # #       Which is reasonable
            # #       Also we assume the header to be contained in one line,
            # #       which for execute is also reasonable since it should
            # #       always be invoked with no arguments
            # header = sourcelines[0]
            # content = sourcelines[1:]

            # for i, l in enumerate(content):
                # if "self.recurse(" in l:
                    # # we found the recurse statement, insert the other statements below
                    # i += 1
                    # for insertline in reversed(insertion):
                        # content.insert(i, insertline)
                    # break

            # new_source = "\n".join([header] + content)
            # print new_source
            # exec compile(new_source, '<string>', 'exec') in globals(), locals()

            # dict[method_name] = eval(method_name)

        # return type.__new__(cls, name, bases, dict)

    # new_meta.__name__ = meta_method
    # setattr(meta, meta_method, types.MethodType(new_meta, meta, meta.__class__))


# def _patched_execute(self):
    # """Patched version of Context.Context.execute() so that not only the root
    # wscript is recursed into but all required wscripts as well.

    # """
    # # first recurse main g_module mandatorily
    # self.recurse([os.path.dirname(Context.g_module.root_path)])

    # # the rest of the wscripts do not have to include the specified
    # paths = get_required_paths()
    # self.recurse(paths, mandatory = False)


