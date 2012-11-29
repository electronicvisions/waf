#!/usr/bin/env python
# encoding: utf-8

from waflib import Context, Configure, Utils
from waflib.extras.mr import Project

dependency_checker = None

# @Configure.conf
# def get_dependency_checker(ctx):
    # "Make singleton dependency checker available"
    # global dependency_checker
    # if dependency_checker is None:
        # dependency_checker = DependencyContext()
    # return dependency_checker

# seperators for component names
CMPSEP = "."

class DependencyContext(Configure.ConfigurationContext):
    def get_component(self, name):
        "Allows components to be extracted by 'featureA.subfeature1'"
        return Component.__getitem__(self._components, name)



class Component(object):
    "Specific component of a project"
    def __init__(self, name, node, parent):
        self._name = name
        self._node = node
        self._parent = parent

        self._children = {}
        self._dependencies = []

    def __str__(self):
        return self.absname

    def __getitem__(self, name):
        if type(name) == str:
            name = name.split(CMPLVLSEP)

        try:
            if len(name) > 1:
                return comp[name[0]][name[1:]]
            else:
                return comp[name[0]]
        except KeyError e:
            raise KeyError( COMPLVLSEP.join(name))

    @property
    def name(self):
        return self._name

    @property
    def absname(self):
        absname = self._parent.name
        if type(self._parent) == Project:
            absname += PROJECTSEP
        else:
            absname += LVLSEP

        absname += self.name

        return absname

    @property
    def path(self):
        return self._node.abspath().replace(os.sep + "wscript", "")

    @property
    def node(self):
        return self._node

    @property
    def parent(self):
        return self._parent


class DependencyContext(Configure.ConfigurationContext):

	def __init__(self, components, **kw):
		super(DependencyContext, self).__init__(**kw)

        # reference to the components in the project
        self._components = components
        self._path_to_comp = {}

    def depends(self, component, project = None, branch = None):
        """
        Express dependency:
            project = None  expresses the same project
            branch = None   expresses the default branch
        """
        if not self.component_created:
            raise Exception("Dependencies specified before provision in {0}.".format(
                self.path.abspath()))

    def provides(self, component, relative = True):
        """
        Expresses that current wscript provides component

        The `relative` parameter governs whether the provision is relative
        or a new toplevel.
        """
        #TODO: Implement me

        self.component_created = True

    def pre_recurse(self, node):
        super(DependencyContext, self).pre_recurse(node)
        self.component_created = False

    def find_parent_wscript(self, node):
        while True:
            node = node.parent

            if node.find_node( 'wscript' ) is not None:
                break

        return node


    def scan_components(self):
        "Resolve dependencies one by one."
        pass


	def __init__(self, **kw):
		super(DependencyContext, self).__init__(**kw)


    def depends(self, component, project = None, branch = None):
        """
        Express dependency:
            project = None  expresses the same project
            branch = None   expresses the default branch
        """
        pass


    def provides(self, component, relative = True):
        """
        Expresses that current wscript provides component

        The `relative` parameter governs whether the provision is relative
        or a new toplevel.
        """
        pass


    def scan_components(self):
        "Resolve dependencies one by one."
        pass


class Project( object )
    def __init__( self ):
        self._components = {}
        self._required_components = []
