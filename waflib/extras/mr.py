#!/usr/bin/env python
# encoding: utf-8

"""
Dependencies system

A :py:class:`waflib.Dependencies.DependenciesContext` instance is created when ``waf dependencies`` is called, it is used to:

"""

import os, sys
from waflib import Utils, Logs, Context, Options, Configure, Errors
from pprint import pprint
import json
import tempfile
import re

import subprocess
from ConfigParser import RawConfigParser
from StringIO import StringIO

# will be set from symwaf2ic
get_repo_tool = lambda: None

class Repo_DB(object):
    def __init__(self, filepath):
        self.db = json.load(open(filepath, "r"))

    def get_init(self, name):
        return self.db[name]["init_cmds"]

    def get_type(self, name):
        return self.db[name]["type"]

    def get_url(self, name):
        return self.db[name]["url"]

    def get_description(self, name):
        return self.db[name].get("description") or "- n/a -"

    def get_manager(self, name):
        return self.db[name].get("manager")

    def list_repos(self):
        names = self.db.keys()
        return filter(lambda x: not x.startswith("_"), names)

class BranchError(Exception):
    pass

class Project(object):
    def __init__(self, name, node, branch = None):
        assert isinstance(name, basestring)
        assert node
        self._name = name
        self._node = node
        self._branch = branch
        self._real_branch = None
        self._mr_registered = False
        self.required = False

    def __str__(self):
        try:
            return self.name + " {" + self.required_branch + "}"
        except BranchError:
            return self.name + " {???}"

    def __eq__(self, another):
        return self.name == another.name

    def __hash__(self):
        return hash(self.name)

    @property
    def name(self):
        return self._name

    @property
    def mr_registered(self):
        return self._mr_registered

    @mr_registered.setter
    def mr_registered(self, value):
        self._mr_registered = value

    @property
    def required_branch(self):
        if self._branch is None:
            raise BranchError, "required branch unkown"
        return self._branch

    @required_branch.setter
    def required_branch(self, branch):
        if self._branch is None:
            self._branch = branch if branch is not None else self.default_branch
        elif branch is None:
            pass
        elif self._branch != branch:
            raise BranchError, "branch already set"
        else:
            pass

    @property
    def node(self):
        return self._node

    @property
    def real_branch(self):
        if self._real_branch is None:
            ret, stdout, stderr = self.exec_cmd(self.get_branch_cmd())
            if ret != 0:
                err = "{} returned {}\n{}{}".format(' '.join(self.get_branch_cmd()),
                        ret, stdout, stderr)
                raise RuntimeError(err)
            self._real_branch =  stdout.strip()
        return self._real_branch

    def update_branch(self):
        ret, stdout, stderr = self.exec_cmd(self.set_branch_cmd())
        if ret != 0:
            raise BranchError(stdout + stderr)
        self._real_branch = None

    def path_from(self, modules_dir):
        return self.node.path_from(modules_dir)

#    def set_real_branch(self):
#        self.exec_cmd(get_branch_cmd())
#        return self.get_branch()

    def exec_cmd(self, cmd, **kw):
        defaults = {
                'cwd'    : self.node.abspath(),
                'stdout' : subprocess.PIPE,
                'stderr' : subprocess.PIPE,
            }
        defaults.update(kw)
        p = subprocess.Popen(cmd, **defaults)
        stdout, stderr = p.communicate()
        return p.returncode, stdout, stderr

    # TO IMPLEMENT
    def mr_checkout_cmd(self, *k, **kw):
        raise AttributeError
    def mr_init_cmd(self, *k, **kw):
        raise AttributeError

class GitProject(Project):
    vcs = 'git'
    default_branch = 'master'

    def get_branch_cmd(self):
        return ['git', 'rev-parse', '--abbrev-ref', 'HEAD']

    def set_branch_cmd(self, branch = None):
        return ['git', 'checkout', branch if branch else self.required_branch]

    def __init__(self, *args, **kw):
        super(self.__class__, self).__init__(*args, **kw)

    def mr_checkout_cmd(self, base_node, url):
        path = self.node.path_from(base_node)
        cmd = ["git clone '{url}' '{target}'".format(url=url, target=os.path.basename(path))]
        return 'checkout=%s' % "; ".join(cmd)

    def mr_init_cmd(self, init):
        init_cmd = " ".join(self.set_branch_cmd()) + "; " + init
        return "post_checkout = cd {name} && {init}".format(
            name=os.path.basename(self.name), init=init_cmd)



class MR(object):
    MR         = "mr"
    MR_LOCAL_DIR = '.myrepos'
    # MR_CONFIG  = "repo.conf"
    MR_CONFIG  = ".symwaf2ic.repo.conf"
    MR_LOG     = "repo.log"
    DB_FOLDER  = "repo_db"
    DB_FILE    = "repo_db.json"
    # MODULE_DIR = "modules"
    CFGFOLDER  = "mr_conf"
    LOG_COLOR  = "BLUE"
    LOG_WARN_COLOR  = "ORANGE"

    project_types = {
            'git' : GitProject
    }

    def __init__(self, ctx, db_url="git@example.com:db.git", db_type="git", top=None, cfg=None, clear_log=False):
        self.ctx = ctx
        self.init_dirs(top, cfg)
        self.find_mr()
        self.projects = {}
        if clear_log:
            self.log.write("")

        self.mr_print('Using "%s" to manage repositories' % self.mr_tool.abspath())
        self.mr_print('commands are logged to "%s"' % self.log.path_from(self.base))

        self.setup_repo_db(db_url, db_type)

        self.init_mr()
        self.mr_print("Found managed repositories: " + str(self.pretty_projects() ))

    def init_dirs(self, top, cfg):
        # Find top node
        if not top:
            top = getattr(self.ctx, 'srcnode', None)
        if not top:
            top = self.ctx.path
        if not top:
            self.ctx.fatal("Could not find top dir")

        self.base = top
        if cfg is None:
            self.cfg_node = top.make_node(self.CONFIG_DIR)
            self.cfg_node.mkdir()
        else:
            self.cfg_node = cfg
        self.config = self.base.make_node(self.MR_CONFIG)
        self.log = self.cfg_node.make_node(self.MR_LOG)

    def load_projects(self):
        parser = self.load_config()
        projects = self.projects
        for name in parser.sections():
            projects[name] = self._get_or_create_project(name)
            projects[name].mr_registered = True

    def find_mr(self, mr_url="https://github.com/joeyh/myrepos.git"):
        mr_path = which("mr")
        if mr_path is None:
            # we didnt find the mr tool in path, just look in local directory
            self.mr_tool = self.base.find_node(self.MR)
            # ok, finally let's checkout from upstream
            if not self.mr_tool:
                if not self.base.find_node(self.MR_LOCAL_DIR):
                    Logs.pprint(self.LOG_COLOR, "'{mr}' tool not found, cloning from upstream".format(mr=self.MR))
                    cmd = "git clone '{url}' '{target}'".format(url=mr_url, target=self.MR_LOCAL_DIR)
                    subprocess.call(cmd, shell=True)
                try:
                    local_mr = self.base.find_node(self.MR_LOCAL_DIR).find_node(self.MR)
                except AttributeError, e:
                    local_mr = None
                if not local_mr:
                    self.ctx.fatal("Checking out {mr} tool from upstream failed".format(mr=self.MR))
                self.mr_tool = local_mr
        else:
            self.mr_tool = self.ctx.root.find_node(mr_path)
        if self.mr_tool is None:
            self.ctx.fatal("Could not find " + self.MR + " repo tool:\n" +
            "Please install " + self.MR + " on your machine or place mr in this folder")

    def setup_repo_db(self, db_url, db_type):
        # first install some mock object that servers to create the repo db repository
        class MockDB(object):
            def get_url(self, *k, **kw):
                return db_url
            def get_init(self, *k, **kw):
                return ""
            def get_type(self, *k, **kw):
                return db_type
        self.db = MockDB()

        db_node = self.cfg_node.make_node(self.DB_FOLDER)
        db_path = db_node.path_from(self.base)
        if db_type == "wget":
            # TODO: implement download via wget
            raise Errors.WafError("wget support not implemented yet. Poke obreitwi!")
        else:
            # see if db repository is already checked out, if not, add it
            # since we have not read all managed repositories, manually read the mr config
            parser = self.load_config()
            self.projects[db_path] = db_repo = self.project_types[db_type](name=db_path, node=db_node)
            db_repo.required_branch = None
            db_repo.required = True
            if db_path not in parser.sections() or not os.path.isdir(db_repo.node.abspath()):
                # we need to add it manually because if project isn't found we would look in the
                # not yet existing db
                self.mr_checkout_project(db_repo)

        self.db = Repo_DB(os.path.join(db_node.abspath(), self.DB_FILE))

    def init_mr(self):
        self.init_default_config()
        self.load_projects()
        not_on_filesystem = []
        for name, p in self.projects.iteritems():
            if not os.path.isdir(p.node.abspath()):
                not_on_filesystem.append(name)
        self.remove_projects(not_on_filesystem)

    def init_default_config(self):
        parser = self.load_config()
        parser.set('DEFAULT', 'git_log', 'git log -n1 "$@"')
        self.save_config(parser)

    def mr_log(self, msg, sep = "\n"):
        self.log.write(msg + sep, 'a')

    def mr_print(self, msg, color = None, sep = '\n'):
        self.mr_log(msg, sep = sep)
        Logs.pprint(color if color else self.LOG_COLOR, msg, sep = sep)

    def load_config(self):
        """Load mr config file, returns an empty config if the file does not exits"""
        parser = RawConfigParser()
        parser.read([self.config.abspath()])
        return parser

    def save_config(self, parser):
        tmp = StringIO()
        parser.write(tmp)
        self.config.write(tmp.getvalue())

    def format_cmd(self, *args, **kw):
        """ use _conf_file to override config file destination """
        env = kw.get('env', os.environ.copy())
        # if args and args[0] == 'register':
            # env["PATH"] = self.mr_tool.parent.abspath() + os.pathsep + env["PATH"]

        custom_conf_file = "_conf_file" in kw

        conf_file = self.config.path_from(self.base)\
            if not custom_conf_file else kw["_conf_file"]

        if custom_conf_file:
            del kw["_conf_file"]

        cmd = [self.mr_tool.abspath(), '-t', '-c', conf_file]
        cmd.extend(args)

        self.mr_log('-' * 80 + '\n' + str(cmd) + ':\n')

        kw['cwd']    = self.base.abspath()
        kw['env']    = env
        return cmd, kw


    def call_mr(self, *args, **kw):

        tmpfile = None

        if args and args[0] == "register":
            # because mr seems to have a bug not trusting any config file
            # during "register" we write the config to a tempfile and append manually .. ¬_¬

            # NOTE: we can be sure that register is only called if the project is not present
            # in the config file

            tmpfile = tempfile.NamedTemporaryFile()
            kw["_conf_file"] = tmpfile.name

        cmd, kw = self.format_cmd(*args, **kw)
        kw['quiet']  = Context.BOTH
        kw['output'] = Context.BOTH
        kw['env'] = self.get_mr_env()
        try:
            stdout, stderr = self.ctx.cmd_and_log(cmd, **kw)
        except Errors.WafError as e:
            stdout = getattr(e, 'stdout', "")
            stderr = getattr(e, 'stderr', "")
            # self.mr_log('stdout: "%s"\nstderr: "%s"\n' % (stdout, stderr))
            Logs.warn('stdout: \n"%s"\nstderr: \n"%s"\n' % (stdout, stderr))
            if stderr:
                e.msg += ':\n\n' + stderr
            if tmpfile is not None:
                tmpfile.close()
            raise e

        msg = 'stdout:\n"' + stdout + '"\n'
        msg += 'stderr:\n"' + stderr + '"\n'
        # self.mr_log(msg)
        if tmpfile is not None:
            # write config to repo conf
            tmpfile.seek(0)
            tmpfile_lines = tmpfile.file.readlines()
            tmpfile.close()

            # make sure path in header is relative (as if we had registered it without
            # all the 'security' shennanigans from mr)
            header_idx = 1
            path = tmpfile_lines[header_idx].strip()[1:-1]
            node = self.ctx.root.find_node(path)
            tmpfile_lines[header_idx] = "[{0}]\n".format(node.path_from(self.base))
            self.config.write("".join(tmpfile_lines), 'a')
        Logs.debug(msg)

        return cmd, stdout, stderr

    def get_mr_env(self):
        env = os.environ
        path = env["PATH"].split(os.pathsep)
        path.insert(0, self.mr_tool.parent.abspath())
        env["PATH"] = os.pathsep.join(path)


    def checkout_project(self, project, parent_path, branch = None, update_branch = False):
        p = self._get_or_create_project(project)
        p.required = True
        try:
            p.required_branch = branch
        except BranchError:
            self.mr_print('Project "%s" is already required on branch "%s", but "%s" requires branch "%s"'\
                    % ( project, p.required_branch, parent_path, branch), 'YELLOW')

        if p.mr_registered and os.path.isdir(p.node.abspath()) and os.listdir(p.node.abspath()):
            if update_branch and p.required_branch != p.real_branch:
                self.mr_print('Switching branch of repository %s from %s to %s..' % \
                        ( project, p.real_branch, p.required_branch), sep = '')
                try:
                    p.update_branch()
                except BranchError as e:
                    self.mr_print('')
                    self.ctx.fatal(str(e))
                self.mr_print('done', 'GREEN')
            return p.node.path_from(self.base)
        else:
            return self.mr_checkout_project(p)

    def mr_checkout_project(self, p):
        "Perform the actual mr checkout"
        path = p.node.path_from(self.base)
        do_checkout = False
        if '-h' in sys.argv or '--help' in sys.argv:
            Logs.warn('Not all projects were found: the help message may be incomplete')
            ctx = Context.create_context('options')
            ctx.parse_args()
            sys.exit(0)

        # Check if the project folder exists, in this case the repo
        # needs only to be registered
        if os.path.isdir(p.node.abspath()):
            self.mr_print('Register existing repository %s..' % p, sep = '')
            self.call_mr('register', path)
        else:
            do_checkout = True
            self.mr_print('Trying to check out repository %s..' % p, sep = '')

        args = ['config', p.name,
                p.mr_checkout_cmd(self.base, self.db.get_url(p.name)),
                p.mr_init_cmd(self.db.get_init(p.name))]
        self.call_mr(*args)

        if do_checkout:
            self.call_mr('checkout')

        p.mr_registered = True
        self.mr_print('done', 'GREEN')
        return path

    def remove_projects(self, projects):
        parser = self.load_config()
        for name in projects:
            if not name in self.projects:
                continue
            p = self.projects[name]
            self.mr_print("Remove repository %s from repo.conf" % p.name)
            parser.remove_section(p.path_from(self.base))
            del self.projects[name]

        self.save_config(parser)

    def clean_projects(self):
        names = [ p.name for p in self.projects.itervalues() if not p.required ]
        self.remove_projects(names)

    def get_wrong_branches(self):
        ret = []
        for name, p in self.projects.iteritems():
            try:
                if p.required_branch != p.real_branch:
                    ret.append( (name, p.real_branch, p.required_branch) )
            except BranchError:
                pass
        return ret

    def get_projects(self):
        return self.projects

    def pretty_projects(self):
        names = []
        for name, p in self.projects.iteritems():
            names.append(self.pretty_name(p))
        return ", ".join(names)

    def pretty_name(self, prj):
        out = prj.name + " {on " + prj.real_branch + "}"
        return out

    # def _repo_node(self, name):
        # """returns a a node representing the repo folder"""
        # node = self.base.make_node(name)
        # return node

    def _get_or_create_project(self, name):
        try:
            return self.projects[name]
        except KeyError:
            vcs = self.db.get_type(name)
            node = self.base.make_node(name)
            p = self.project_types[vcs](name = name, node = node)
            self.projects[name] = p
            return p


# TODO: KHS, this is not a build step, its a configure step if any specific step at all.
# Subclassing ConfigurationContext states the intention more clearly -
# and serves better my purpose

class MRContext(Configure.ConfigurationContext):
    '''check status of the repositories (using MR tool)'''
    cmd = 'repos-status'
    debug=False # set to True to print the command prior execution.

    # KHS: this is a noop
    #def __init__(self, **kw):
    #    super(MRContext, self).__init__(**kw)

    def execute(self):
        """
        See :py:func:`waflib.Context.Context.execute`.
        """
        self.mr = get_repo_tool()

        cmd, kw = self.mr.format_cmd(*self.get_args())
        if self.debug: Logs.info(cmd)
        subprocess.call(cmd, **kw)

    def get_args(self):
        return Utils.to_list(getattr(self, 'mr_cmd', self.cmd.replace('repos-','')))

class mr_run(MRContext):
    '''runs rargs in all repositories (./waf mr-run <your commands>)'''
    cmd = 'mr-run'
    mr_cmd = 'run'      # + Options.commands

    def get_args(self):
        #if not Options.commands:
        #    self.fatal("expecting further commands for mr run: ./waf mr-run -- <your commands>")
        ret = [ 'run' ] + Options.commands
        Options.commands = []
        self.mr_cmd = ' '.join(ret)
        return ret

class mr_xrun(MRContext):
    '''create shell script from rargs and run this in every repository (./waf mr-xrun "line1" "line2" ...)'''
    cmd = 'mr-xrun'
    mr_cmd = 'run'      # run <path_to_mrcmd_node>
    mr_cmds = []        # ie. read from Options.commands, override this in subclasses

    def __init__(self, **kw):
        super(mr_xrun, self).__init__(**kw)

        # Node for mrcmd scripts (shell scripts to be called by mr for complex commands)
        self.init_dirs() # sets bldnode
        self.mrcmd_node = self.bldnode.make_node('.mrcmd')
        self.mrcmd_node.mkdir()

    def getMrCmdFile(self):
        if not self.mr_cmds:
            self.mr_cmds = Options.commands[:]
            Options.commands = []

        # name of the command file (with hash of the commands to specify)
        fn = self.cmd + '.' + Utils.to_hex(Utils.h_list(self.mr_cmds))

        # create the command file if it does not exist
        node = self.mrcmd_node.find_node(fn)
        if not node:
            node = self.mrcmd_node.make_node(fn)
            with open(node.abspath(),'w') as f:
                f.write("#!/bin/bash\n")
                f.write("# This file was generated by ./waf " + self.cmd + '.\n\n')
                f.write("# doc: " + self.__doc__.replace('\n', '\n# ')+'\n\n')
                f.write('\n'.join(self.mr_cmds))
                f.write('\n')
                os.chmod(node.abspath(), 0754)
                Logs.info("mrcmd-file created: " + node.abspath())

        assert node
        return node.abspath()

    def get_args(self):
        return ['run', self.getMrCmdFile()]

class mr_origin_log(mr_xrun):
    """Get log messages from correspondant origin branch (does not fetch, ./waf repos-origin-log [-- <log-format-options>])"""

    cmd = "repos-origin-log"
    mr_cmds = [ "ref=`git symbolic-ref -q HEAD` # refs/heads/<branchname>",
                #"# upstream: The name of a local ref which can be considered “upstream” from the displayed ref (KHS: ie, origin)",
                "branch=`git for-each-ref --format='%(upstream:short)' $ref` # origin/<branchname>",
                "git log $@ $branch" # $@: commandline argument (logformat)
    ]

    def get_args(self):
        if Options.commands:
            logformat = ' '.join(Options.commands)
            Options.commands=[]
        else:
            logformat = "-n1 --pretty=oneline"

        return ['run', self.getMrCmdFile(), logformat]


class mr_fetch(MRContext):
    '''updates origin in all repositories (git fetch --no-progress)'''
    cmd = 'repos-fetch'
    mr_cmd = 'run git fetch --tags --no-progress'

class mr_up(MRContext):
    '''update the repositories (using MR tool)'''
    cmd = 'repos-update'

class mr_diff(MRContext):
    '''diff all repositories (using MR tool)'''
    cmd = 'repos-diff'

class mr_commit(MRContext):
    '''commit all changes (using MR tool)'''
    cmd = 'repos-commit'

class mr_push(MRContext):
    '''push all changes (using MR tool)'''
    cmd = 'repos-push'

class mr_log(MRContext):
    '''push all changes (using MR tool)'''
    cmd = 'repos-log'


#### DEPRECATED code startsnip
# TODO [2013-09-17 15:08:56] old deprecated mr interface, will be deleted
# repos-mrcmd for standard mr commands
# mr-(x)run for special commands that expect mr understanding
# the old commands are marked as deprecated and will be removed anytime soon
# under discussion: leave some shortcut commands like up/st/diff
# rationale: better organized output of waf --help (its alphabetic sorting)

class mr_deprecated(MRContext):
    cmd=None
    newcmd=None
    def __init__(self, **kw):
        super(mr_deprecated, self).__init__(**kw)
        Logs.warn("This mr/repo-command interface is deprecated use ./waf repos-{command} instead.".format(command = self.newcmd or self.cmd))

class deprecated_mr_up(mr_deprecated):
    '''DEPRECATED update the repositories (using MR tool)'''
    cmd = 'up'
    mr_cmd = 'update'
    newcmd = 'update'

# FIXME, conflicts, @see ./waf --help | grep update (KHS)
class deprecated_mr_update(mr_deprecated):
    '''KHS: we never see this doc'''
    cmd = 'update'

class deprecated_mr_diff(mr_deprecated):
    '''DEPRECATED diff all repositories (using MR tool)'''
    cmd = 'diff'

class deprecated_mr_status(mr_deprecated):
    '''DEPRECATED check status of the repositories (using MR tool)'''
    cmd = 'st'
    mr_cmd = 'status'
    newcmd = 'status'

class deprecated_mr_status(mr_deprecated):
    '''DEPRECATED check status of the repositories (using MR tool)'''
    cmd = 'status'

class deprecated_mr_commit(mr_deprecated):
    '''DEPRECATED commit all changes (using MR tool)'''
    cmd = 'commit'

class deprecated_mr_push(mr_deprecated):
    '''DEPRECATED push all changes (using MR tool)'''
    cmd = 'push'

#class deprecated_mr_branch(mr_deprecated):
#    cmd = 'branch'
#
#class deprecated_mr_checkout(mr_deprecated):
#    cmd = 'checkout'
#### endsnip

def options(opt):
    gr = opt.add_option_group("show_repos")
    gr.add_option(
        "--manager", dest="show_repos_manager", action="store_true",
        help="Also list the managers of the repositories.",
        default=False
    )
    gr.add_option(
        "--url", dest="show_repos_url", action="store_true",
        help="Also list the urls of the repositories.",
        default=False
    )
    gr.add_option(
        "--full-description", dest="show_repos_fdesc", action="store_true",
        help="List the full description of the repositories, no matter what.",
        default=False
    )

class show_repos_context(Context.Context):
    __doc__ = '''lists all available repositories'''
    cmd = 'show_repos'
    def __init__(self, **kw):
        super(show_repos_context, self).__init__(**kw)


    def build_repo_info(self, r):
        info = {"name" : r,
                "used" : '*' if (r in self.used) else ' ', #str(r  in self.used),
                "desc" : self.db.get_description(r),
                "url"  : self.db.get_url(r),
                "man"  : self.db.get_manager(r) or '- n/a -',
        }
        return info

    def get_longest_field(self, d, key):
        if d:
            item = max(d, key = lambda x: len(x[key]))
            return len(item[key])
        else:
            return 0

    def truncate_field(self, data, field, length):
        cut = max(length - 3, 0)
        for k in data:
            f = k[field]
            if len(f) > length:
                k[field] = f[:cut] + "..."

    def truncate_statistical(self, data, field, sd_factor=1.3, length = None):
        """truncate field on one sd from mean"""
        # KHS: naja... hab mich ein bischen verkünstelt...
        sm = 0
        for k in data: sm += len(k[field])
        mv = sm / float(len(data))
        sd = 0
        for k in data: sd+=(mv - len(k[field]))**2
        sd = (sd/len(data))**0.5
        l = int( mv + sd_factor * sd )
        if length:
            length=min(l, length)
        else:
            length=l
        return self.truncate_field(data, field, length)

    def execute(self):
        """
        See :py:func:`waflib.Context.Context.execute`.
        """
        self.mr = get_repo_tool()
        self.db = self.mr.db

        self.repos = sorted(self.db.list_repos())
        self.used = set(self.mr.get_projects().keys())

        try:
            columns = int(os.popen('stty size', 'r').read().split()[1]) # 0 are the rows.
        except:
            Logs.warn("Could not determine console width ('stty size' failed), defaulting to 80.")
            columns = 80 # very basic size uh...

        data = [ self.build_repo_info(r) for r in self.repos ]

        strip = Options.options.show_repos_url + Options.options.show_repos_manager # 0,1,2
        if (not Options.options.show_repos_fdesc) and strip:
            self.truncate_statistical(data, "desc", 2.7-strip, 57-(10*strip))

        field = "{{{name}: <{len}}}"
        fields = [ ("name", self.get_longest_field(data, "name")),
                 #  ("used", 6),
                   ("desc", self.get_longest_field(data, "desc")),
        #           ("url", self.get_longest_field(data, "url")),
        #           ("man", self.get_longest_field(data, "man")),
        ]

        if Options.options.show_repos_url:
            fields.append( ("url", self.get_longest_field(data, "url")) )
        if Options.options.show_repos_manager:
            fields.append( ("man", self.get_longest_field(data, "man")) )

        line = "| {used} " + " | ".join([field.format(name = n, len = l) for n, l in fields]) + " |"

        header = line.format(name = "Repository", used = " ", desc = "Description", url = "url", man = "Manager")

        if len(header)>columns:
            Logs.info("Your console width is not wide enough for a beautiful output or 'stty size' failed...")
            line = " {used} " + "\n   ".join([field.format(name = n, len = l) for n, l in fields]) + "\n"
            header = line.format(name = "Repository", used = " ", desc = "Description", url = "url", man = "Manager")
            header += "-" * columns
        else:
            header += '\n' + "-" * len(header)

        print header
        for d in data:
            print line.format(**d)



def which(program):
    import os
    def is_exe(fpath):
       return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
       if is_exe(program):
           return program
    else:
       for path in os.environ["PATH"].split(os.pathsep):
           exe_file = os.path.join(path, program)
           if is_exe(exe_file):
               return exe_file

    return None
