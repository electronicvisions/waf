#!/usr/bin/env python
# encoding: utf-8

"""
Dependencies system

A :py:class:`waflib.Dependencies.DependenciesContext` instance is created when ``waf dependencies`` is called, it is used to:

"""

import os, shlex, sys, time
from waflib import ConfigSet, Utils, Options, Logs, Context, Build, Errors, Node

from pprint import pprint

from ConfigParser import RawConfigParser
from StringIO import StringIO

def gitviz(name, *init):
    return ('git', 'git@gitviz.kip.uni-heidelberg.de:{name}'.format(name = name)) + init

db = {
    'symap2ic':                    gitviz('symap2ic'),
    'spikeyhal':                   gitviz('spikeyhal'),
    'flyspi-fpga':                 gitviz('flyspi-fpga'),
    'fpgasystem':                  gitviz('fpgasystem'),
    'fpgasystem-projects':         gitviz('fpgasystem-projects'),
    'pynnhw':                      gitviz('pynn-hardware'),
    'systemsim-stage2':            gitviz('systemsim-stage2'),
    'mappingtool':                 gitviz('mappingtool.git'),
    'sctrltp':                     gitviz('sctrltp'),
    'demonstrator-ai-states':      gitviz('model-ai-states'),
    'demonstrator-kth-l23':        gitviz('model-kth-l23'),
    'demonstrator-locally':        gitviz('model-locally'),
    'demonstrator-microcircuit':   gitviz('model-microcircuit'),
    'demonstrator-quantitative':   gitviz('model-quantitative'),
    'demonstrator-synfire-ffi':    gitviz('model-synfire-ffi'),
    'hicann-system':               gitviz('hicann-system'),
    'ncf-hicann':                  gitviz('ncf-hicann'),
    'ncf-hicann-fc':               gitviz('ncf-hicann-fc'),
    'deb-pynn':                    gitviz('deb-pynn'),
    'calibration':                 gitviz('calibration'),
    'jenkins-techdemo':            gitviz('jenkins-techdemo'),
    'ester':                       gitviz('ester'),
    'pyhmf':                       gitviz('pyhmf'),
    'halbe':                       gitviz('halbe'),
    'lib-rcf':                     gitviz('lib-rcf'),
    'lib-boost-patches':           gitviz('lib-boost-patches'),
    'marocco':                     gitviz('marocco'),
    'pest':                        gitviz('pest'),
    'hicann-system2':              gitviz('hicann-system'),
    'pyplusplus':                  gitviz('pyplusplus'),
    'pygccxml':                    gitviz('pygccxml'),
    'ztl':                         ('git', 'https://github.com/ignatz/ztl.git'),
    'rant':                        ('git', 'https://github.com/ignatz/rant.git'),
    'odeint-v2':                   ('git', 'https://github.com/headmyshoulder/odeint-v2.git'),
    'ztl_local':                   ('git', '/home/ckoke/Code/symap2ic/components/ztl'),
}

class Repo_DB(object):
    db = db
    co_cmd = {
        'git' : 'git clone {url} {target}',
        'svn' : 'svn co {url} {target}',
    }

    branch_cmd = {
        'git' : 'git checkout {branch}',
    }

    default_branch = {
        'git' : 'master',
    }

    def build_checkout_cmd(self, name, branch, target, extra_cmds=[]):
        entry = db[name]
        vcs, url, init = entry[0], entry[1], list(entry[2:])

        if not branch is None:
            if target in db:
                raise AttributeError(
                        "There is a specific target named '%s', cannot checkout"
                        "branch '%s' of '%s'" % (target, branch, name) )
            try:
                init.append(branch_cmd[vcs].format(branch = branch))
            except KeyError:
                raise AttributeError("Branching is not supported by %s." % vcs)

        co_cmd = self.co_cmd[vcs].format(url=url,target=target)
        cmd = [co_cmd] + init + extra_cmds
        return 'checkout=%s' % ";".join(cmd)

class MR(object):
    MR         = "mr"
    MR_CONFIG  = "repo.conf"
    MR_LOG     = "repo.log"
    MODULE_DIR = "modules"
    LOG_COLOR  = "BLUE"

    def __init__(self, ctx, clear_log = False):
        self.ctx = ctx
        self.init_dirs()
        self.find_mr()
        self.db = Repo_DB()
        if clear_log:
            self.log.write("")

        self.mr_print('Using "%s" to manage repositories' % self.mr_tool.abspath())
        self.mr_print('commands are logged to "%s"' % self.log.path_from(self.base))

        self.init_mr()
        self.mr_print("Found managed repositories: " + str(self.pretty_projects() ))

    def init_dirs(self):
        # Find top node
        # TODO place config file to find top node from dependend repositories
        top = None
        if not top:
            top = getattr(self.ctx, 'srcnode', None)
        if not top:
            top = self.ctx.path
        if not top:
            self.ctx.fatal("Could not find top dir")

        self.base = top
        self.modules = top.make_node(self.MODULE_DIR)
        self.modules.mkdir()
        self.config = self.modules.make_node(self.MR_CONFIG)
        self.log = self.modules.make_node(self.MR_LOG)

    def find_mr(self):
        # TODO make it better
        self.mr_tool = self.base.find_node(self.MR)

    def init_mr(self):
        self.update_projects()
        not_on_filesystem = []
        for p in self.projects:
            n = self.repo_node(*p)
            if not os.path.isdir(n.abspath()):
                not_on_filesystem.append(p)
        self.remove_projects(not_on_filesystem)

    def mr_log(self, msg):
        self.log.write(msg, 'a')

    def mr_print(self, msg, color = None, sep = '\n'):
        self.mr_log(msg)
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

    def call_mr(self, *args, **kw):
        #if not os.path.exists('mr'):
        #    raise IOError('mr does not exist (maybe non-distcleaned builds in components?)')

        # mr bug?
        env = kw.get('env', os.environ.copy())
        if args and args[0] == 'register':
            env["PATH"] = self.mr_tool.parent.abspath() + os.pathsep + env["PATH"]


        cmd = [self.mr_tool.abspath(), '-t', '-c', self.config.path_from(self.base) ]
        cmd.extend(args)

        self.mr_log('-' * 80 + '\n' + str(cmd) + ':\n')

        kw['output'] = Context.BOTH
        kw['cwd']    = self.base.abspath()
        kw['quiet']  = Context.BOTH
        kw['env']    = env
        try:
            stdout, stderr = self.ctx.cmd_and_log(cmd, **kw)
        except Errors.WafError as e:
            stdout = getattr(e, 'stdout', None)
            stderr = getattr(e, 'stdout', None)
            self.mr_log('stdout: "%s"\nstderr: "%s"\n' % (stdout, stderr))
            if stderr:
                e.msg += ':\n\n' + stderr
            raise e

        msg = 'stdout:\n"' + stdout + '"\n'
        msg += 'stderr:\n"' + stderr + '"\n'
        self.mr_log(msg)
        return cmd, stdout, stderr

    def update_projects(self):
        parser = self.load_config()
        self.projects = [ self.split_path(p) for p in parser.sections() ]

    def register_top(self):
        master = '..'
        if (master, None) in self.projects:
            return
        try:
            self.call_mr('register', master)
        except Errors.WafError as e:
            if not (hasattr(e, 'stderr') and e.stderr == "mr register: unknown repository type\n"):
                raise e
        self.update_projects()

    def has_project(self, node, branch = None):
        return (node.name, branch) in self.projects

    def checkout_project(self, name, branch = None):
        node = self.repo_node(name, branch)
        path = node.path_from(self.base)

        if self.has_project(node):
            return path

        repo = name
        if branch:
            repo += " (branch: " + branch + ")"

        # Check if the project folder exists, in this case the repo 
        # needs only to be registered
        if os.path.isdir(node.abspath()):
            self.mr_print('Register existing repository %s:' % repo)
            self.call_mr('register', path)
        else:
            self.mr_print('Trying to checkout repository %s:' % repo, sep = '')
            co = self.db.build_checkout_cmd(name, branch, node.name)
            args = [ 'config', node.name, co]
            self.call_mr(*args)
            self.call_mr('checkout')

        self.mr_print('done', 'GREEN')
        self.update_projects()
        return path

    def remove_projects(self, projects):
        parser = self.load_config()
        for p in projects:
            name, branch = p
            node = self.repo_node(name, branch)
            if not self.has_project(node):
                continue

            repo = name
            if branch:
                repo += " (branch: " + branch + ")"

            self.mr_print("Remove repository %s from repo.conf" % repo)
            parser.remove_section(node.name)

        self.save_config(parser)
        self.update_projects()

    def get_projects(self):
        return self.projects

    def pretty_projects(self):
        names = []
        for p in self.projects:
            name, branch = p
            if branch:
                name += " {" + branch + "}"
            names.append(name)
        return ", ".join(names)

    @staticmethod
    def split_path(name):
        if isinstance(name, Node.Node):
            name = name.name
        tmp = name.split('__') + [None]
        return tmp[0], tmp[1]
        return [ f(p)for p in self.projects ]

    def repo_node(self, name, branch):
        """returns a a node representing the repo folder"""
        if branch:
            name = name + '__' + branch
        node = self.modules.make_node(name)
        return node


class MRContext(Build.BuildContext):
    '''lists the targets to execute'''
    cmd = 'status'
    def __init__(self, **kw):
        super(MRContext, self).__init__(**kw)

    def execute(self):
        """
        See :py:func:`waflib.Context.Context.execute`.
        """
        self.init_dirs()
        self.restore()
        if not self.all_envs:
            self.load_envs()

        self.mr = getattr(self, 'mr', MR(self))
        args = self.get_args()
        cmd, stdout, stderr = self.mr.call_mr(*args)
        if stderr:
            self.to_log(cmd)
            self.to_log(stderr)

        self.to_log(stdout)
        #try:
        #        conf.cmd_and_log(['which', 'someapp'], output=waflib.Context.BOTH, env=env)
        #except Exception as e:
        #        print(e.stdout, e.stderr)

    def get_args(self):
        return [getattr(self, 'mr_cmd', self.cmd)]


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

