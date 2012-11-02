import os
from waflib import Build, Configure, Utils, Options, Logs
from waflib.extras import mr

MODULE_DIR = "modules"

#CACHE_DIR = os.path.join(self.build_path, Build.CACHE_DIR)


def options(opt):
    pass

def configure(ctx):
    ctx.mr = mr.MR(ctx)
    ctx.projects = set()
    ctx.mr.register_top()
    ctx.projects.add( ('..', None) )

def init(ctx):
    from pprint import pprint
    pprint(ctx)
    pprint(dir(ctx))
#    print ctx.env.get_merged_dict()
    ctx.mr = mr.MR(ctx)

@Configure.conf
def load_project(ctx, name, branch = None):
    path = ctx.mr.checkout_project(name, branch)
    ctx.projects.add( (name, branch) )
    ctx.recurse(path)


def setup(ctx):
    """Called by Context classes inherited from BuildContext"""
    ctx.init_dirs()
    ctx.mr = mr.MR(ctx)
    return
    init(ctx)
    if isinstance(Build.BuildContext):
        env = ConfigSet().load(ctx.cache_dir.xyz)
        m = Utils.to_list(env.MODULES)
        ctx.add_pre_fun(lambda ctx: ctx.recurse(m))

def patchConfigurationContex(ctx):
    old = ctx.store
    def new_store(ctx):
        old(ctx)
        old_projects = set(ctx.mr.get_projects()) - ctx.projects
        ctx.mr.remove_projects(old_projects)
    ctx.store = new_store

patchConfigurationContex(Configure.ConfigurationContext)
