#!/usr/bin/env python
# encoding: utf-8

#####################
# !!! ABANDONED !!! #
#####################

import os, sys, argparse
from waflib import Context, Logs, Errors

############################
# classes and architecture #
############################

# seperators for component names
# we encode components as <projectname>PRJSEP<component>CMPSEP<subcomponent>CMPSEP<subsubcomponent>[..]
PRJSEP = ":"
CMPSEP = "."

logger = None

class DependencyError(Errors.WafError):
    pass

class DependencyLogger(object):
    COLOR  = "BLUE"
    DEBUG_COLOR = "CYAN"
    WARN_COLOR  = "ORANGE"
    FATAL_COLOR  = "RED"

    LOGLEVELS = "debug info warn fatal".split()

    def __init__(self, node, level = "info", clear = True):
        self._log = node
        self._log.parent.mkdir()

        for i,lvl in enumerate(self.LOGLEVELS):
            exec("self.{lvl} = {value}".format(
                lvl = lvl.upper(), value = i))

        self.loglvl = eval("self.{lvl}".format(lvl = level.upper()))

        if clear:
            self._log.write("")

    def log(self, msg, sep = "\n"):
        self._log.write(msg + sep, 'a')

    def pprint(self, msg, color = None, sep = '\n'):
        self.log(msg, sep = sep)
        Logs.pprint(color if color else self.COLOR, msg, sep = sep)

    def debug(self, msg, sep = '\n'):
        if self.loglvl <= self.DEBUG:
            self.pprint(msg, color = self.DEBUG_COLOR, sep = sep)

    def info(self, msg, color = None, sep = '\n'):
        if self.loglvl <= self.INFO:
            self.pprint(msg, color, sep)

    def warn(self, msg, sep = '\n'):
        if self.loglvl <= self.WARN:
            self.pprint(msg, self.WARN_COLOR, sep)

    def fatal(self, msg, color = None, sep = '\n'):
        if self.loglvl <= self.FATAL:
            color = "RED" if color is None else self.FATAL_COLOR
            self.pprint(msg, color, sep)
        raise DependencyError(msg)


def make_logger(node, level = "debug", clear = True):
    global logger
    logger = DependencyLogger(node, level = level, clear = clear)


class ArgParseWrapper(object):
    "Wrapper around an argparser that scans options method of a wscript"

    def __init__(self, component):
        self._parser = argparse.ArgumentParser()
        self._component = component
        self._finished_parsing = False
        self._gather_options()
        logger.debug("Read options for {comp} ..".format(comp = self._component.absname))

    def add_option(self, *k, **kw):
        # fixes for optparse -> argparse compatability
        if "type" in kw:
            kw["type"] = eval(kw["type"])
        self._parser.add_argument(*k, **kw)

    # Since we are only interested in the arguments themselves and provide no output
    # in the depdency system, optparse's OptionGropus are irrelevent, since they only
    # serve to produce nicer help messages.
    def add_option_group(self, *k, **kw):
        return self

    def get_option_group(self, opt_str):
        return self

    def _gather_options(self):
        module = Context.load_module(self._component.node.abspath())

        if hasattr(module, "options"):
            module.options(self)

        self._options, leftover = self._parser.parse_known_args(sys.argv[1:])
        self._finished_parsing = True

    # We first want the wrapper to act as a PseudoContext that is passed
    # to the options method. After that we only want to provide access to the
    # parsed arguments; all other methods become meaningless.
    #
    # Furthermore, if an option is asked for, it might have been defined in another
    # wscript in the same project further up the tree -> look for those.
    # 
    # NOTE: Only wscripts that have a "provides" function will be considered!
    def __getattribute__(self, name):
        if name.startswith("_") or not self._finished_parsing:
            return object.__getattribute__(self, name)

        if hasattr(self._options, name):
            return getattr(self._options, name)

        if self._component.parent is not None:
            return getattr(self._component.parent.options, name)
        else:
            raise AttributeError("Option {opt} not set for project {prj}.".format(
                opt = name, prj = self._component.node.name))


class DependencyNode(object):
    SEP = CMPSEP
    def __init__(self, name, parent, node):
        self._name = name
        self._parent = parent
        self._children = {}
        self._node = node

    def print_tree(self, level = 0, **kw):
        params = { "indentation": 2 }
        params.update(kw)

        print "{indent}{arrow} {name}".format(
                indent = " "*(level-1)*params["indentation"],
                arrow = "o" if level == 0 else "└─>", name = self.name)
        for child in self.children.values():
            child.print_tree(level = level+1, **kw )

    @property
    def parent(self):
        return self._parent

    @property
    def children(self):
        return self._children

    @property
    def node(self):
        return self._node

    @property
    def name(self):
        return self._name

    @property
    def name_sep(self):
        return self.absname + self.SEP

    @property
    def absname(self):
        parent_name = "" if self.parent is None\
            else self.parent.name_sep
        return parent_name + self.name

    @property
    def path(self):
        return self.node.abspath()

    @property
    def root(self):
        if self.parent is not None:
            return self.parent.root
        else:
            return self

    def get_component(self, name):
        """Get component from the dependency tree.

        This method allows to specify components further down.
        E.g. 'compA.subcomp2.subsubcomp4' etc.

        If the component cannot be found a KeyError is raised.
        """
        if type(name) == str:
            name = name.split(CMPSEP)
        try:
            if len(name) > 1:
                return self.children[name[0]].get_component(name[1:])
            else:
                return self.children[name[0]]
        except KeyError:
            raise KeyError(CMPSEP.join(name))

    def add_component(self, name, node, component_type = None, **kw):
        if component_type is None:
            component_type = type(self)
        self.children[ name ] = component\
                = component_type(name, self, node, **kw)
        return component

    def get_full_name(self, project, component):
        full_name  = self.root.name if project is None else project
        full_name += PRJSEP + component
        return full_name


class Project(DependencyNode):
    "Container for a subproject in the dependency tree."
    SEP=PRJSEP

    def __init__(self, name, parent, node, manager):
        super(Project, self).__init__(name, parent, node)
        self.manager = manager

    def add_component(self, name, node, **kw):
        return super(type(self), self).add_component(
                name, node, component_type = Component, **kw)


class Component(DependencyNode):
    def __init__(self, *arg, **kw):
        super(Component, self).__init__(*arg, **kw)
        self._dependencies = set()
        self._required = False
        self.options = ArgParseWrapper(self)

        logger.debug("Created component {comp} ..".format(comp = self.absname))

    def is_required(self):
        return self._required

    def sub_provision(self, provision_name):
        "Add another provision for the same wscript."
        self._children[provision_name] = subprovision\
                = self.add_component(provision_name, self.node)
        return subprovision

    def add_component(self, name, node, **kw):
        return super(type(self), self).add_component(
                name, node, component_type = type(self), **kw)

    def add_dependency(self, name, project = None ):
        # if one wscript provides more dependencies
        # each might call the depends method but we only
        # want to track dependencies of components that are actually
        # required
        if self.is_required:
            full_name = self.get_full_name(project, name)

            if not full_name in self._dependencies:
                self._dependencies.add(full_name)
                self.root.manager.register_dependency(full_name)

    def require(self):
        self._required = True
        self.scan_dependencies()

    def scan_dependencies(self):
        module = Context.load_module(self.node.abspath())

        if hasattr(module, "depends"):
            dep = DependencyContext(self)
            module.depends(dep)



# Note: these are not actual Contexts because `provides` as well as `depends`
#       are NOT waf commands.
class ProvisionContext(object):
    "Pseudo-Context to be executed with provision-methods."
    def __init__(self, parent, node):
        self._parent = parent
        self._node = node
        self._component = None

    def provides(self, component, relative = True):
        """
        If called for the first time inside a provides-method of a wscript it specifies
        the main component to be provided by this wscript. Further calls allow the specifications
        of subcomponents inside the same wscript. A reference to the ProvisionContext of the
        (Sub)Provision is returned.

        component: Name of the component to be provided by this wscript.

        relative: Governs if the provision is at toplevel (False)
        is a subprovision to the main provision of the next higher wscript.
        (Only relevant for the toplevel provision component)

        Further provisions can be specified by calling also_provides(..).
        """
        if self._component is None:
            if relative:
                self._component = self._parent.add_component(component, self._node)
            else:
                self._component = self._parent.root.add_component(component, self._node)
            return self
        else:
            # the main provision has already been specified -> create new child
            component = self._component.add_component(component, self._node)
            return ProvisionContext(None, self._node, component)


class DependencyContext(object):
    "Pseudo-Context to be executed with depends-methods."
    def __init__(self,  comp):
        self._component = comp
        self.options = comp.options

    def depends(self, component, project = None):
        """
        Specify a dependency for the *main* provision of this wscript

        project == None indicates a dependency in the same project.
        """
        self._component.add_dependency(component, project)

    def get_provision(self, provision):
        """
        Get a subprovision called `provision` so that its dependencies may be specified.
        """
        return DependencyContext(self._component.get_component(provision))


class DependencyManager(object):
    LOGFILE = "modules/dependency.log"

    def __init__(self, ctx, loglevel):
        self._projects = {}
        self.ctx = ctx
        self._unmet = set()
        self._deps = set()
        self.find_top_node()

        make_logger(self.base.make_node(self.LOGFILE), level = loglevel)

    def find_top_node(self):
        # TODO: Same as mr.py this is a hack
        # Find top node
        top = None
        if not top:
            top = getattr(self.ctx, 'srcnode', None)
        if not top:
            top = self.ctx.path
        if not top:
            logger.fatal("Could not find top dir")
        self.base = top

    @property
    def projects(self):
        return self._projects

    @property
    def unmet_dependencies(self):
        return self._unmet

    @property
    def unmet_projects(self):
        return [c.split(PRJSEP)[0] for c in self.unmet_dependencies]

    @property
    def dependencies(self):
        return self._deps

    def add_project(self, projectname, path):
        logger.info("Adding {prj} under: {path}".format(
            prj = projectname, path = path))
        node = self.ctx.root.find_node(path)
        if node == None:
            logger.fatal("Project {prj} not found under: {path}".format(
                prj = projectname, path = path))
        project = Project(projectname, None, node, self)
        self.projects[projectname] = project
        self.scan_provisions(project)

    def scan_provisions(self, project):
        logger.debug("Scanning provision of project {prj}".format(prj = project.name))
        stack = []
        stack.append(( project, project.node ))

        while len( stack ) > 0:
            comp, node = stack.pop()

            wscript = node.find_node( "wscript" )
            if wscript is not None:
                # wscript was found, load it and execute provides method
                module = Context.load_module(wscript.abspath())
                if hasattr( module, 'provides' ):
                    prv = ProvisionContext(comp, wscript)
                    module.provides(prv)

                    # update component to the newly created one
                    comp = prv._component

            # scan the node directory for other directories and add them to stack
            # -> depth first search
            folders = (fld for fld in node.listdir()
                    if os.path.isdir(os.path.join(node.abspath(), fld)))
            for fld in folders:
                stack.append((comp, node.find_node(fld)))

    def register_dependency(self, dependency):
        if dependency not in self.dependencies:
            self._unmet.add(dependency)
            self._deps.add(dependency)

    def get_component(self, component):
        """Get component from the dependency tree.

        This method allows to specify components further down.
        E.g. 'projectXY:compA.subcomp2.subsubcomp4' etc.

        If the component cannot be found a KeyError is raised.
        """
        project, comp = component.split(PRJSEP)
        try:
            return self.projects[project].get_component(comp)
        except KeyError:
            raise KeyError(component)


###################
# waf integration #
###################

dep_mngr = None

def options(ctx):
    global dep_mngr
    dep_mngr = DependencyManager(ctx, loglevel = "debug")
    ctx.__class__.get_dependency_manager = get_dependency_manager


def get_dependency_manager(ctx):
    assert dep_mngr
    return dep_mngr


if __name__ == "__main__":
    # Testing
    project = Project( "testing", None, None )
    testcomponent = project.add_component("testcomponent", None)
    anothertest = testcomponent.add_component( "anothertest", None )
    anothertest.add_component( "and yet again", None )
    testsubcomponent = testcomponent.sub_provision( "testsubcomponent" )

    print testsubcomponent.absname
    project.print_tree()

