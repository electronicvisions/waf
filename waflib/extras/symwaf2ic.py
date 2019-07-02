#!/usr/bin/env python
# encoding: utf-8

"Symwaf2ic package"
# waf --zones=symwaf2ic, symwaf2ic_options, dependency

import os
import sys
import argparse
import shutil
import subprocess

import json
from collections import defaultdict, deque

try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse

from waflib import Build, Context, Errors, Logs, Utils, Options
from waflib.extras import mr

from waflib.extras.symwaf2ic_misc import add_username_to_gerrit_url
from waflib.extras.symwaf2ic_misc import parse_gerrit_changes
from waflib.extras.symwaf2ic_misc import validate_gerrit_url


#############
# CONSTANTS #
#############

SYMWAF2IC_VERSION = 1

FILEPREFIX = ".symwaf2ic"
CFGFOLDER = ".symwaf2ic"
LOCKFILE = FILEPREFIX + ".conf.json"

SETUP_CMD = "setup"
DOC_CMD = "doc"
# upon which commands shall the config be written
STORE_CMDS = set([SETUP_CMD, "configure"])

# items to strip from command line before parsing with own parser
HELP_CMDS = "-h --help show_repos".split()
STRIP_FROM_PARSER = HELP_CMDS
# commands which will cause symwaf2ic to be disabled when specified
NO_EXECUTE_CMDS = "no_symwaf2ic distclean".split()


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
        def splitprj(arg):
            r = arg.split('@') # prj, branch, dir
            if not r[0]: raise # default opt parse message
            if len(r) == 1: return r[0], None, r[0]
            if len(r) == 2: return r[0], r[1] or None , r[0]
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

    gr.add_option(
            "--update-branches", dest="update_branches",
            default=False, type='choice', choices="soft force".split(), # false is not a choice, its the default and bool('false') is true
            help="Activate branch tracking (e.g., when updating repositories). If specified set to soft or force (the latter deletes local changes)."
    )
    gr.add_option(
            "--gerrit-changes", "--gerrit-changesets", default=[], action="store",
            type=parse_gerrit_changes if is_symwaf2ic else str,
            help="Comma-seperated list of gerrit query ids. Possible values "
                 "are changeset numbers, changeset ids or complex queries like "
                 "--gerrit-changes='topic:hicann_version status:open,change:925,926'. "
                 "Plain numbers are interpreted are automatically prefixed with 'change:'. "
                 "The resuling changesets are applied to the sources. If "
                 "multiple changeset are found for one repo, the repo is "
                 "resetted to the first and all others will be cherrypicked.\n"
                 "To remove gerrit changsets --update-branches can be used."
                 "Dependent changesets (listed as \"Depends-On:\" in the "
                 "commit message) will be collected and resolved after the "
                 "explicitely stated ones (breadth-first). Use "
                 "--gerrit-changes-ignored to exclude specific changesets "
                 "from this automatic resolution.")
    gr.add_option(
            "--gerrit-changes-ignored", default=[], action="store",
            type=(lambda x: [int(cs) for cs in x.split(",")]) if is_symwaf2ic else str,
            help="Comma-separated list of gerrit changeset numbers to be "
                 "excluded from being picked. Note that only integer "
                 "changeset numbers are allowed parameters. Use this option "
                 "to exclude changesets from being picked during the "
                 "automatic dependency resolution based on \"Depends-On:\" "
                 "keywords in commit messages.")
    gr.add_option(
            "--gerrit-url", action="store",
            type=validate_gerrit_url if is_symwaf2ic else str,
            default=validate_gerrit_url(
                "ssh://brainscales-r.kip.uni-heidelberg.de:29418"),
            help="URL for gerrit")
    gr.add_option(
            "--gerrit-username", action="store",
            type=str,
            default="",
            help="Username for gerrit")
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
    gr.add_option(
        "--clone-depth", dest="clone_depth", action="store",
        type=int, help="To clone the full history use -1 [default is full history]",
        default=-1
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
        super(MainContext, self).__init__(*k, **kw)

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
        for k, v in config.items():
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
        self.clone_depth= cmdopts.clone_depth
        self.gerrit_url = cmdopts.gerrit_url
        self.gerrit_username = cmdopts.gerrit_username

        if not self.gerrit_username and not urlparse(self.gerrit_url).username:
            # If there's a [gitreview] username, use that one
            git_p = subprocess.Popen(["git", "config", "gitreview.username"],
                                     stdout=subprocess.PIPE)
            review_user, _ = git_p.communicate()
            review_user = review_user.decode(sys.stdout.encoding or "utf-8")
            if git_p.returncode == 0:
                self.gerrit_username = review_user.strip()

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
        storage.repo_tool = mr.MR(
            self, self.repo_db_url, self.repo_db_type, top=self.toplevel,
            cfg=repoconf, clear_log=True, clone_depth=self.clone_depth,
            gerrit_url=add_username_to_gerrit_url(
                self.gerrit_url, self.gerrit_username))


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

        self.parser = argparse.ArgumentParser(add_help=False)
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
            if isinstance(kw["type"], str):
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
        self.gerrit_changes = {}
        if (SETUP_CMD in sys.argv) and storage.setup_options["gerrit_changes"]:
                self.gerrit_changes = storage.repo_tool.resolve_gerrit_changes(
                    self, storage.setup_options["gerrit_changes"],
                    ignored_cs=storage.setup_options["gerrit_changes_ignored"])
        self.write_dot_file = storage.current_options["write_dot_file"]
        self.clone_depth = storage.setup_options["clone_depth"]
        # Dependency graph
        self.dependencies = defaultdict(list)
        # Queue for breadth-first search
        self.to_recurse = deque()

    def __call__(self, project, subfolder="", branch=None, ref=None):
        self.call_impl(project, subfolder=subfolder, branch=branch, ref=ref,
                       predecessor=self.cur_script.parent.path_from(self.toplevel))

    def call_impl(self, project, subfolder="", branch=None, ref=None, predecessor=None):
        required_from = "project option" if predecessor is None else predecessor
        Logs.debug("dependency: Required by {script}: {project}{branch}{subfolder}".format(
                    project=project,
                    subfolder="" if len(subfolder) == 0 else " ({0})".format(subfolder),
                    branch="" if branch is None else "@{0}".format(branch),
                    ref="" if ref is None else "@ref:{0}".format(ref),
                    script=required_from,
                ))
        path = storage.repo_tool.checkout_project(
            self, project, required_from, branch=branch, ref=ref,
            update_branch=self.update_branches,
            gerrit_changes=self.gerrit_changes)

        if len(subfolder) > 0:
            path = os.path.join(path, subfolder)

        if not self.toplevel.find_dir(path):
            raise Symwaf2icError("Folder '{0}' not found in project {1}".format(subfolder, project))

        # For topology order of deps
        self._add_required_path(path, predecessor)

    def execute(self):
        # dont recurse into all already dependency directories again
        self._first_recursion = False

        info = [str(p) for p in get_projects()]
        Logs.debug("dependency: Required from toplevel: {0}".format( ", ".join(info)))
        Logs.debug("dependency: Required gerrit changes: {0}".format(self.gerrit_changes))

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
        gitnode = self.toplevel.find_dir('.git')
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
                # Topological order is not definite, compare sets
                and set(storage.saved_paths) != set(storage.paths)
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
            print(data)
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
                    self.call_impl(
                        project.project, branch=project.branch, predecessor=None)
                except KeyError as exc:
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
            for source, targets in self.dependencies.items():
                s = source[prefix:]
                for target in targets:
                    t = target[prefix:]
                    outfile.write('"{}" -> "{}";\n'.format(s, t))
            outfile.write("}")


# Add documentation command and set its context to BuildContext instead of a Context
class DocumentationContext(Build.BuildContext):
    cmd = DOC_CMD
    fun = DOC_CMD
