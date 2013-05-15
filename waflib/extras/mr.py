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
        return self.db[name].get("description",
                "- No description available -")

    def list_repos(self):
        names = self.db.keys()
        return filter(lambda x: not x.startswith("_"), names)


class Project(object):
    def __init__(self, name, node, branch = None):
        assert isinstance(name, basestring)
        assert node
        self._name = name
        self._node = node
        self._branch = branch
        self._real_branch = None
        self._mr_registered = False

    def __str__(self):
        try:
            return self.name + " {" + self.required_branch + "}"
        except RuntimeError:
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
            raise RuntimeError, "required branch unkown"
        return self._branch

    @required_branch.setter
    def required_branch(self, branch):
        if self._branch is None:
            self._branch = branch if branch is not None else self.default_branch
        elif branch is None:
            pass
        elif self._branch != branch:
            raise RuntimeError, "branch already set"
        else:
            pass

    @property
    def node(self):
        return self._node

    @property
    def real_branch(self):
        if self._real_branch is None:
            stdout, stderr = self.exec_cmd(self.get_branch_cmd())
            self._real_branch =  stdout.strip()
        return self._real_branch

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
        return p.communicate()

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

    def find_mr(self):
        mr_path = which("mr")
        if mr_path is None:
            # we didnt find the mr tool in path, just look in local directory
            self.mr_tool = self.base.find_node(self.MR)
        else:
            self.mr_tool = self.ctx.root.find_node(mr_path)
        if self.mr_tool is None:
            self.ctx.fatal("Could not find mr repo tool:\n" +
            "Please install mr on your machine or place mr in this folder")

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
            if db_path not in parser.sections() or not os.path.isdir(db_repo.node.abspath()):
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


    def checkout_project(self, project, branch = None):
        p = self._get_or_create_project(project)
        p.required_branch = branch
        if p.mr_registered and os.path.isdir(p.node.abspath()):
            return p.node.path_from(self.base)
        else:
            return self.mr_checkout_project(p)

    def mr_checkout_project(self, p):
        "Perform the actual mr checkout"
        path = p.node.path_from(self.base)
        do_checkout = False

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

    def get_wrong_brachnes(self):
        ret = []
        for name, p in self.projects.iteritems():
            if p.required_branch != p.real_branch:
                ret.append( (name, p.required_branch, p.real_branch) )
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

class show_repos_context(Build.BuildContext):
    __doc__ = '''lists all available repositories'''
    cmd = 'show_repos'
    def __init__(self, **kw):
        super(Build.BuildContext, self).__init__(**kw)

    def build_repo_info(self, r):
        info = {"name" : r,
                "used" : str(r  in self.used),
                "desc" : self.db.get_description(r),
                "url"  : self.db.get_url(r),
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

    def execute(self):
        """
        See :py:func:`waflib.Context.Context.execute`.
        """
        self.mr = get_repo_tool()
        self.db = self.mr.db

        self.repos = sorted(self.db.list_repos())
        self.used = set(self.mr.get_projects().keys())

        data = [ self.build_repo_info(r) for r in self.repos ]

        self.truncate_field(data, "desc", 50)

        field = "{{{name}: <{len}}}"
        fields = [ ("name", self.get_longest_field(data, "name")),
                   ("used", 6),
                   ("desc", self.get_longest_field(data, "desc")),
                   ("url", self.get_longest_field(data, "url")),
        ]
        line = "| " + " | ".join([field.format(name = n, len = l) for n, l in fields]) + " |"

        header = line.format(name = "repo", used = "used", desc = "description", url = "url")
        print header
        print "-" * len(header)
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
