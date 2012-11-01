#!/usr/bin/env python
# encoding: utf-8

"""
Dependencies system

A :py:class:`waflib.Dependencies.DependenciesContext` instance is created when ``waf dependencies`` is called, it is used to:

"""

import os, shlex, sys, time
from waflib import ConfigSet, Utils, Options, Logs, Context, Build, Errors

from pprint import pprint

from ConfigParser import RawConfigParser

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
    MODULE_DIR = "modules"

    def __init__(self, ctx):
        self.ctx = ctx
        self.init_dirs()

        # TODO make it better
        self.mr_tool = self.base.find_or_declare(self.MR)
        self.db = Repo_DB()
        self.update_projects()

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

    def load_config(self):
        """Load mr config file, returns an empty config if the file does not exits"""
        parser = RawConfigParser()
        parser.read([self.config.abspath()])
        return parser

    def save_config(self, parser):
        parser.write(self.config)

    def project_node(self, name, branch):
        """returns a tuple of project name (for the mr config) and node representing the project folder"""
        if branch:
            name = name + '__' + branch
        node = self.modules.make_node(name)
        return node

    def call_mr(self, *args, **kw):
        #if not os.path.exists('mr'):
        #    raise IOError('mr does not exist (maybe non-distcleaned builds in components?)')

        cmd = [self.mr_tool.abspath(), '-t', '-c', self.config.path_from(self.base) ]
        cmd.extend(args)

        kw['output'] = Context.BOTH
        kw['cwd']    = self.base.abspath()
        kw['quiet']  = Context.BOTH
        stdout, stderr = self.ctx.cmd_and_log(cmd, **kw)
        return cmd, stdout, stderr

    def update_projects(self):
        self.projects = self.load_config().sections()

    def register_top(self):
        master = '..'
        if master in self.projects:
            return
        try:
            self.call_mr('register', master)
        except Errors.WafError as e:
            if not (hasattr(e, 'stderr') and e.stderr == "mr register: unknown repository type\n"):
                raise e
        self.update_projects()

    def has_project(self, node, branch = None):
        if isinstance(node, basestring):
            node = self.project_node(node, branch)
        return node.name in self.projects

    def checkout_project(self, name, branch = None):
        node = self.project_node(name, branch)
        path = node.path_from(self.base)

        if self.has_project(node):
            return path

        # Check if the project folder exists (in this case the repo)
        # should be checked out there
        if os.path.isdir(node.abspath()):
            self.call_mr('register', node.name)
        else:
            co = self.db.build_checkout_cmd(name, branch, node.name)
            args = [ 'config', node.name, co]
            self.call_mr(*args)
            self.call_mr('checkout')
        self.update_projects()
        return path

    def remove_project(self, name, branch = None):
        assert(false)
        path = self.module_path(name, folder)
        parser = self.parseConfig()
        parser.remove_section(path)
        self.writeConfig(parser)
        self.update_projects()


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
