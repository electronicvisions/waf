#!/usr/bin/env python
# encoding: utf-8

"""
Dependencies system

A :py:class:`waflib.Dependencies.DependenciesContext` instance is created when ``waf dependencies`` is called, it is used to:

"""

import os, sys
from waflib import Utils, Logs, Context, Build, Errors
from pprint import pprint
import json

import subprocess
from ConfigParser import RawConfigParser
from StringIO import StringIO

# def gitviz(name, *init):
    # return ('git', 'git@gitviz.kip.uni-heidelberg.de:{name}'.format(name = name)) + init


# db = {
    # 'symap2ic':                    gitviz('symap2ic'),
    # 'spikeyhal':                   gitviz('spikeyhal'),
    # 'flyspi-fpga':                 gitviz('flyspi-fpga'),
    # 'fpgasystem':                  gitviz('fpgasystem'),
    # 'fpgasystem-projects':         gitviz('fpgasystem-projects'),
    # 'pynnhw':                      gitviz('pynn-hardware'),
    # 'systemsim-stage2':            gitviz('systemsim-stage2'),
    # 'mappingtool':                 gitviz('mappingtool.git'),
    # 'sctrltp':                     gitviz('sctrltp'),
    # 'demonstrator-ai-states':      gitviz('model-ai-states'),
    # 'demonstrator-kth-l23':        gitviz('model-kth-l23'),
    # 'demonstrator-locally':        gitviz('model-locally'),
    # 'demonstrator-microcircuit':   gitviz('model-microcircuit'),
    # 'demonstrator-quantitative':   gitviz('model-quantitative'),
    # 'demonstrator-synfire-ffi':    gitviz('model-synfire-ffi'),
    # 'hicann-system':               gitviz('hicann-system'),
    # 'ncf-hicann':                  gitviz('ncf-hicann'),
    # 'ncf-hicann-fc':               gitviz('ncf-hicann-fc'),
    # 'deb-pynn':                    gitviz('deb-pynn'),
    # 'calibration':                 gitviz('calibration'),
    # 'jenkins-techdemo':            gitviz('jenkins-techdemo'),
    # 'ester':                       gitviz('ester'),
    # 'pyhmf':                       gitviz('pyhmf'),
    # 'halbe':                       gitviz('halbe'),
    # 'lib-rcf':                     gitviz('lib-rcf'),
    # 'lib-boost-patches':           gitviz('lib-boost-patches'),
    # 'marocco':                     gitviz('marocco'),
    # 'pest':                        gitviz('pest'),
    # 'hicann-system2':              gitviz('hicann-system'),
    # 'pyplusplus':                  gitviz('pyplusplus'),
    # 'pygccxml':                    gitviz('pygccxml'),
    # 'ztl':                         ('git', 'https://github.com/ignatz/ztl.git'),
    # 'rant':                        ('git', 'https://github.com/ignatz/rant.git'),
    # 'bitter':                      ('git', 'https://github.com/ignatz/bitter.git'),
    # 'odeint-v2':                   ('git', 'https://github.com/headmyshoulder/odeint-v2.git'),
    # 'ztl_local':                   ('git', '/home/ckoke/Code/symap2ic/components/ztl', 'echo "Hallo"'),

    # # DEBUGGING
    # 'dummy_A':                     ('git', '/afs/kip.uni-heidelberg.de/user/obreitwi/git/symwaf2ic_test/dummy_A'),
    # 'dummy_B':                     ('git', '/afs/kip.uni-heidelberg.de/user/obreitwi/git/symwaf2ic_test/dummy_B'),
    # 'dummy_C':                     ('git', '/afs/kip.uni-heidelberg.de/user/obreitwi/git/symwaf2ic_test/dummy_C'),
# }


# will be set from symwaf2ic
get_repo_tool = lambda: None


class Repo_DB(object):
    def __init__(self, filepath):
        self.db = json.load(open(filepath, "r"))

    def get_data(self, name):
        return self.db[name][1:]

    def get_type(self, name):
        return self.db[name][0]


class Project(object):
    def __init__(self, name, node, branch = None):
        assert isinstance(name, basestring)
        assert node
        self._name = name
        self._node = node
        self._branch = branch

    def __eq__(self, another):
        return self.name == another.name

    def __hash__(self):
        return hash(self.name)

    @property
    def name(self):
        return self._name

    @property
    def branch(self):
        return self._branch

    def set_branch(self, branch):
        if self._branch is None:
            self._branch = branch if branch else self.default_branch
        else:
            raise RuntimeError, "branch already set"

    @property
    def node(self):
        return self._node

    @property
    def real_branch(self):
        stdout, stderr = self.exec_cmd(self.set_branch_cmd())
        return stdout

    def path_from(self, modules_dir):
        return self.node.path_from(modules_dir)

#    def set_real_branch(self):
#        self.exec_cmd(get_branch_cmd())
#        return self.get_branch()

    def exec_cmd(self, cmd, **kw):
        defaults = {
                'pwd'    : self.node.abspath(),
                'stdout' : subprocess.PIPE,
                'stderr' : subprocess.PIPE,
            }
        defaults.update(kw)
        subprocess.check_call(cmd, **defaults)
        return subprocess.communicate()


class GitProject(Project):
    vcs = 'git'
    default_branch = 'master'

    def get_branch_cmd(self):
        return ['git', 'rev-parse', '--abbrev-ref', 'HEAD']

    def set_branch_cmd(self, branch = None):
        return ['git', 'checkout', branch if branch else self.branch]

    def __init__(self, *args, **kw):
        super(self.__class__, self).__init__(*args, **kw)

    def mr_checkout_cmd(self, base_node, url, init_cmds=""):
        path = self.node.path_from(base_node)
        cmd = ["git clone '{url}' '{target}'".format(url=url, target=os.path.basename(path))]
        cmd.append( "cd {target}".format(target=os.path.basename(path)))
        cmd.extend(Utils.to_list(init_cmds))
        if self.branch != self.default_branch:
            cmd.append(" ".join(self.set_branch_cmd()))

        return 'checkout=%s' % "; ".join(cmd)


class MR(object):
    MR         = "mr"
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

    def find_mr(self):
        mr_path = which("mr")
        if mr_path is None:
            # we didnt find the mr tool in path, just look in local directory
            self.mr_tool = self.base.find_node(self.MR)
        else:
            self.mr_tool = self.ctx.root.find_node(mr_path)

    def setup_repo_db(self, db_url, db_type):
        # first install some mock object that servers to create the repo db repository
        class MockDB(object):
            def get_data(self, *k, **kw):
                return [db_url]
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
            db_repo.set_branch(None)
            if db_path not in parser.sections():
                # we need to add it manually because if project isn't found we would look in the
                # not yet existing db
                self.mr_checkout_project(db_repo)

        self.db = Repo_DB(os.path.join(db_node.abspath(), self.DB_FILE))

    def init_mr(self):
        self.load_projects()
        not_on_filesystem = []
        for name, p in self.projects.iteritems():
            if not os.path.isdir(p.node.abspath()):
                not_on_filesystem.append(name)
        self.remove_projects(not_on_filesystem)

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
        """ """
        env = kw.get('env', os.environ.copy())
        if args and args[0] == 'register':
            env["PATH"] = self.mr_tool.parent.abspath() + os.pathsep + env["PATH"]


        cmd = [self.mr_tool.abspath(), '-t', '-c', self.config.path_from(self.base)]
        cmd.extend(args)

        self.mr_log('-' * 80 + '\n' + str(cmd) + ':\n')

        kw['cwd']    = self.base.abspath()
        kw['env']    = env
        return cmd, kw


    def call_mr(self, *args, **kw):
        cmd, kw = self.format_cmd(*args, **kw)
        kw['quiet']  = Context.BOTH
        kw['output'] = Context.BOTH
        try:
            stdout, stderr = self.ctx.cmd_and_log(cmd, **kw)
        except Errors.WafError as e:
            stdout = getattr(e, 'stdout', "")
            stderr = getattr(e, 'stderr', "")
            # self.mr_log('stdout: "%s"\nstderr: "%s"\n' % (stdout, stderr))
            Logs.warn('stdout: \n"%s"\nstderr: \n"%s"\n' % (stdout, stderr))
            if stderr:
                e.msg += ':\n\n' + stderr
            raise e

        msg = 'stdout:\n"' + stdout + '"\n'
        msg += 'stderr:\n"' + stderr + '"\n'
        # self.mr_log(msg)
        Logs.debug(msg)
        return cmd, stdout, stderr


    def register_top(self):
        # TODO we need the name of the master repo...
        # NOT USED!
        master = '..'
        if master in self.projects:
            return
        try:
            self.call_mr('register', master)
            self._get_or_create_project(master)
        except Errors.WafError as e:
            if not (hasattr(e, 'stderr') and e.stderr == "mr register: unknown repository type\n"):
                raise e

    def checkout_project(self, name, branch = None):
        if name in self.projects:
            p = self.projects[name]
            if branch is not None and p.branch != branch:
                raise AttributeError, "Project %s is required with different branches '%s' and '%s'" % (p.name, p.branch, branch)
            return p.node.path_from(self.base)
        else:
            return self.mr_checkout_project(self._get_or_create_project(name, branch))

    def mr_checkout_project(self, p):
        "Perform the actual mr checkout"
        repo = self.pretty_name(p.name, p.branch)
        path = p.node.path_from(self.base)

        # Check if the project folder exists, in this case the repo 
        # needs only to be registered
        if os.path.isdir(p.node.abspath()):
            self.mr_print('Register existing repository %s..' % repo, sep = '')
            self.call_mr('register', path)
        else:
            self.mr_print('Trying to check out repository %s..' % repo, sep = '')
            args = ['config', p.name,
                    p.mr_checkout_cmd(self.base, *self.db.get_data(p.name))]
            self.call_mr(*args)
            self.call_mr('checkout')

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

    def get_projects(self):
        return self.projects

    def pretty_projects(self):
        names = []
        for name, p in self.projects.iteritems():
            names.append(self.pretty_name(p.name, p.branch))
        return ", ".join(names)

    def pretty_name(self, name, branch):
        if branch:
            name += " {" + branch + "}"
        return name

    # def _repo_node(self, name):
        # """returns a a node representing the repo folder"""
        # node = self.base.make_node(name)
        # return node

    def _get_or_create_project(self, name, branch=None):
        try:
            return self.projects[name]
        except KeyError:
            vcs = self.db.get_type(name)
            node = self.base.make_node(name)
            p = self.project_types[vcs](name = name, node = node)
            p.set_branch(branch)
            self.projects[name] = p
            return p


class MRContext(Build.BuildContext):
    '''lists the targets to execute'''
    cmd = 'status'
    def __init__(self, **kw):
        super(MRContext, self).__init__(**kw)

    def execute(self):
        """
        See :py:func:`waflib.Context.Context.execute`.
        """
        self.mr = get_repo_tool()

        cmd, kw = self.mr.format_cmd(*self.get_args())
        subprocess.call(cmd, **kw)

    def get_args(self):
        return Utils.to_list(getattr(self, 'mr_cmd', self.cmd))


class mr_up(MRContext):
    cmd = 'up'
    mr_cmd = 'update'

class mr_update(MRContext):
    cmd = 'update'

class mr_diff(MRContext):
    cmd = 'diff'

class mr_status(MRContext):
    cmd = 'st'
    mr_cmd = 'status'

class mr_status(MRContext):
    cmd = 'status'

class mr_commit(MRContext):
    cmd = 'commit'

class mr_push(MRContext):
    cmd = 'push'

#class mr_branch(MRContext):
#    cmd = 'branch'
#
#class mr_checkout(MRContext):
#    cmd = 'checkout'

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
