#! /usr/bin/env python
# encoding: UTF-8
# Thomas Nagy 2008-2010 (ita)



"""
Doxygen support

Variables passed to bld():
* doxyfile      -- the Doxyfile to use (optional)
* pars          -- Doxygen parameters with higher priority than the doxyfile (optional)
* doxyinput     -- list of pathes specifying input files and directories (required, replaces INPUT)
* doxyoutput    -- a path specifying the output folder (required, replaces OUTPUT_DIRECTORY)
* pdffile       -- if specified a pdf will be generated from the Doxygen generated latex source (needs GENERATE_LATEX)
* doxydebug     -- if True/path the final Doxygen parameters will be written to a file for debugging purposes

Waf options (see waf --help), can be used to disable Doxygen tasks completly or
to suppress the build of specific formats. They override the other parameters,

Parameters in the doxyfile are interpreted relative to that file, parameters
from the wscript (pars) are interpreted relative to the wscript. The format
outputs (e.g., LATEX_OUTPUT, HTML_OUTPUT) are interpreted relative to the
OUTPUT_DIRECTORY (doxyoutput) as the Doxygen specification says.

Note that the Doxygen parameters INPUT and OUTPUT_DIRECTORY are ignored coming
from the doxyfile or the pars parameter. Use the wscript taskgen parameters
doxyinput and doxyoutput instead. They are required.

The taskgen parameters doxyfile and doxyinput are interpreted relative to the
source directory and doxyoutput is relative to the build directory. The
parameters pdffile, doxydebug are then interpreted relative to doxyoutput.

If we speak of paths, they can generally be specified as strings or Node
instances.

Derived from (incomplete) Doxygen support from waf 1.5, Original author: Thomas
Nagy (see comment above).
# File:         documentation.py
# Author:       Kai Husmann <kai.husmann@kip.uni-heidelberg.de> (KHS)
# Changelog:    [2013-08-12 09:57:49]   created/released (KHS)
"""

from fnmatch import fnmatchcase
import os, os.path, re, stat, shlex
from waflib import Task, Utils, Node, Logs, Errors
from waflib.TaskGen import feature

DOXY_STR = '${DOXYGEN} - '

# available Doxygen output formats
DOXY_FMTS = 'html latex man rtf xml'.split()

# default Doxygen file patterns (for INCLUDE directories)
#DOXY_FILE_PATTERNS = '*.' + ' *.'.join('''
#c cc cxx cpp c++ java ii ixx ipp i++ inl h hh hxx hpp h++ idl odl cs php php3
#inc m mm py f90c cc cxx cpp c++ java ii ixx ipp i++ inl h hh hxx
#'''.split())
DOXY_FILE_PATTERNS ='''
*.c *.cc *.cxx *.cpp *.c++ *.d *.java *.ii *.ixx *.ipp *.i++ *.inl *.h *.hh
*.hxx *.hpp *.h++ *.idl *.odl *.cs *.php *.php3 *.inc *.m *.mm *.dox *.py *.f90
*.f *.for *.vhd *.vhdl
'''.split()

# keys for parameters in the default environment (ctx.env, all_envs[''])
DOXY_DEFAULT_KEY = 'DoxygenDefaultParameters'   # a dict, generated using `doxygen -g`
DOXY_VERSION_KEY = 'DoxygenVersion'             # a string containing the doxygen version number
DOXY_DISABLE_KEY = 'DoxygenDisable'             # list of doxygen options to be disabled, or True to disable everything

# find bash style newline escapes
re_nl = re.compile(r'\\\r*\n', re.MULTILINE)


# for method/execution-flow debugging
print_method_ind = 0
def print_method(f):
    # disable exexuction flow debugging:
    return f

    # disable print completely
    disable_print = set()
    disable_print.add('getInputNodes')
    disable_print.add('uid')

    # disable print of return value
    disable_ret = set()
    disable_ret.add('scan')


    def decorated(self, *args, **kwargs):
        global print_method_ind
        ind = "POI" + " " * print_method_ind
        print_method_ind += 1
        print ind, ">>" * print_method_ind, f.func_name, args, kwargs

        if args and kwargs:
            ret = f(self, args, kwargs)
        elif args:
            ret = f(self, args)
        else:
            ret = f(self)

        print ind, "<<" * print_method_ind, f.func_name,
        if f.func_name in disable_ret:
            print "(output suppressed)"
        # specialize print
        elif f.func_name == 'uid':
            print Utils.to_hex(ret)
        else:
            print ret
        print_method_ind -= 1

        return ret

    if f.func_name in disable_print:
        return f
    else:
        return decorated



class DoxygenTask(Task.Task):
### class variables

    # env variables we depend on
    vars            = [ 'DOXYGEN', 'DOXYFLAGS', DOXY_DEFAULT_KEY, DOXY_VERSION_KEY, DOXY_DISABLE_KEY ]
    color           = 'BLUE'

    ### Doxygen parameters with handling
    # Note that further handling is also done in _mergeDoxygenParameters()


    # canonized parameters, i.e. relative pathes to absolute ones. (For simple one-value input parameters only)
    PARS_handled_relation       = [ 'LAYOUT_FILE' ] # i.e. relation of paths is handled.

    # TODO parameters probably need canonization, not jet implemented, a warning will be shown if they are found non-empty
    # --> (This list is not necessarily complete)
    PARS_warning                = [ 'HTML_EXTRA_FILES', 'CHM_FILE', 'QCH_FILE', 'TAGFILES', 'DOTFILE_DIRS', 'MSCFILE_DIRS' ]

    # these pars are loaded in advance and represented by instance variables
    PARS_handled_specifically   = [ 'OUTPUT_DIRECTORY', 'INPUT', 'PROJECT_NAME' ]

    # pars that can be specified using the generator directly, as such having highest priority
    PARS_convinience = {
            'doxyoutput'    : 'OUTPUT_DIRECTORY',
            'doxyinput'     : 'INPUT',
            'name'          : 'PROJECT_NAME',
    }


### instance variables

    pars = None             # avoid attribute error for if self.pars tests


### helper methods (static/class/instance)

    @staticmethod
    def getOutputKey(fmt):
        return fmt.upper() + '_OUTPUT'
    @staticmethod
    def getGeneratorKey(fmt):
        return 'GENERATE_' + fmt.upper()
    @staticmethod
    def _loadDoxygenParametersFromNode(node):
        txt = node.read()            # read file to string
        txt = re_nl.sub('', txt)         # replace nl escapes
        return Utils.str_to_dict(txt)    # WARN: doxyfile handles inline comments, but this does not!

    def getDoxygenDefaults(self, key = None):
        if key: return self.getDoxygenDefaults()[key]
        try:
            return DoxygenTask._doxygenDefaultParameters
        except AttributeError:
            d = self.generator.bld.all_envs['']
            d = d[DOXY_DEFAULT_KEY]
            assert type(d) == dict      # not a dict? bad config data, try rerunning ./waf configure and cfg.load(documentation).
            DoxygenTask._doxygenDefaultParameters = d
        return DoxygenTask._doxygenDefaultParameters

    def getDisableOptionValue(self, fmt):
        try:
            return fmt in self._cache_disabled_formats
        except AttributeError:
            v_opt = self.generator.bld.options.doxygen_disable  # this execution's disable options
            v_cfg = self.generator.bld.env[DOXY_DISABLE_KEY]    # disable options during last configure
            self._cache_disabled_formats = v_opt | v_cfg        # if any is True and not a set we should never arrive here
        return self.getDisableOptionValue(fmt)

    def getParameter(self, key, default=None, doxydefault=False):
        if doxydefault: default = self.getDoxygenDefaults(key) or default   # default overrides empty doxygen defaults
        if self.pars:
            return self.pars.get(key, default)                              # if merge has happend already use self.pars
        else:
            return self.wscript_pars.get(key, self.doxyfile_pars.get(key, default)) # otherwise perform a "quick-merge" <-- don't use that for relative paths

    def getBoolParameter(self, key, default=None, doxydefault=False):
        v = self.getParameter(key, default, doxydefault)
        if isinstance(v, bool):
            return v
        if v == "YES": return True
        if v == "NO" : return False
        return None # XXX or maybe throw?

### instance
    def __init__(self, *k, **kw):
        Task.Task.__init__(self, *k, **kw)

        gen     = self.generator
        path    = gen.path
        bld     = gen.bld

        # inputs is not available here! not from the feature task generation...
        if gen.doxynode:
            self.set_inputs(gen.doxynode)

        ### Check for necessary/ reasonable input!
        # we need lots of this data early enough!

        # name --> project_name handled in _mergeDoxygenParameters()

        # doxyfile --> inputs[0] @see process_doxy

        # load doxyfile pars once
        if self.inputs:
            self.doxynode = self.inputs[0]
            self.doxyfile_pars = DoxygenTask._loadDoxygenParametersFromNode(self.doxynode)
        else:
            self.doxyfile_pars = {}
            self.doxynode = None

        # pars --> wscript_pars
        self.wscript_pars = getattr(gen, 'pars', {})
        if type(self.wscript_pars) is not dict: bld.fatal("The task parameter pars should be a dictionary of Doxygen parameteres.")

        # update wscript_pars with convenience parameters
        for attribute, parameter in DoxygenTask.PARS_convinience.iteritems():
            try:
                v = getattr(gen, attribute)
                self.wscript_pars[parameter] = v
            except:
                pass

        # retrieve project name, empty if none given
        self.project_name = self.getParameter('PROJECT_NAME','').strip('"')

        # the doxyfile outputnode
        self.outputnode = self.getParameter('OUTPUT_DIRECTORY').strip('"')
        if (not self.outputnode) and self.doxynode:
            self.outputnode = self.doxynode.parent.get_bld()
        if not self.outputnode:
            bld.fatal('Please specify Doxygen OUTPUT_DIRECTORY using the task parameter doxyoutput or the equivalent wscript pars entry. It can only be omitted if a doxyfile is specified.')
        if not isinstance(self.outputnode, Node.Node):
            self.outputnode = path.get_bld().make_node(self.outputnode)
        assert (self.outputnode)
        #print "POI, out", self.outputnode, self.outputnode.abspath()

        if self.getDisableOptionValue('pdf') or self.getDisableOptionValue('latex'):
            self.pdfnode = None
        else:
            # pdffile --> pdfnode
            self.pdfnode = getattr(gen, 'pdffile', None)
            if self.pdfnode and not isinstance(self.pdfnode, Node.Node):
                self.pdfnode = self.outputnode.find_or_declare(self.pdfnode)
        #print "POI, pdf", self.pdfnode

        # doxydebug --> debugnode
        self.debugnode = getattr(gen, 'doxydebug', None)
        if self.debugnode == True: self.debugnode = 'doxypars.debug'
        if self.debugnode and not isinstance(self.debugnode, Node.Node):
            self.debugnode = self.outputnode.find_or_declare(self.debugnode)
        #print "POI, debugnode", self.debugnode

        # get explicit outputs (pdf, debug and Doxygen formats)
        self.explicitoutputs = [] # (for __str__)
        if self.pdfnode:    self.explicitoutputs.append(self.pdfnode)
        if self.debugnode:  self.explicitoutputs.append(self.debugnode)

        # add all generated formats to explicitoutputs (for __str__)
        for fmt in DOXY_FMTS:
            disabled = self.getDisableOptionValue(fmt)
            if disabled:
                self.wscript_pars[DoxygenTask.getGeneratorKey(fmt)] = False

            if self.getBoolParameter(DoxygenTask.getGeneratorKey(fmt), doxydefault=True):
                formatNode = self.outputnode.make_node(self.getParameter(DoxygenTask.getOutputKey(fmt), doxydefault=True))
                if getattr(formatNode, 'sig', None) and not os.path.isdir(formatNode.abspath()):
                    del formatNode.sig # hacky necessity to handle directory outputs (forces Task.RUN_ME)
                self.explicitoutputs.append(formatNode)
        self.set_outputs(self.explicitoutputs)  # adding directories as outputs!


### helpers for Doxygen parameters

    @print_method
    def handleInputRelation(self, path_str, rel_node):
        """
        Create a node representing the path path_str and return it.

        If path_str is an absolute path the node will be created from root,
        otherwise rel_node will be used. Generally the returned node is created
        using Node.find_or_declare() which is why one should not use this
        function for output pathes.
        The relativity node rel_node must specify a directory!
        """

        if path_str.startswith("/"):
            r = self.generator.bld.root # absolute path always relative to root!

        assert os.path.isdir(rel_node.abspath()) # XXX: not sure if we can assert this, it could be jet nonexisting?

        node = rel_node.find_or_declare(path_str)

        assert node # function is expected to always r#eturn a node
        return node                                   #
                                                      #
    def _mergeDoxygenParameters(self):                #
        """Must be called exactly once, prior any sign#ature() or uid() call. Combines the parameters from
        the doxyfile and the wscript into the self.par#s dictonary, throws if self.pars is not empty!"""
                                                      #
        assert not self.pars        # call this only o#nce
                                                      #
        # convenience only                            #
        gen     = self.generator    # get the generato#r
        bld     = gen.bld           # get the build co#ntext of the toplevel wscript
        path    = gen.path          # get the task generator path, i.e. the folder where the wscript resides which generated the task!


        ### merging doxyfile_pars and wscript_pars into pars

        # load the doxyfile pars, ignore parameters passed in from the wscript and handle some pathes
        pars = self.doxyfile_pars   # is an empty dict if no doxyfile was specified
        if pars:
            skip = DoxygenTask.PARS_handled_specifically + self.wscript_pars.keys()

            for k,v in pars.iteritems():
                if k in skip: continue  # handled elsewhere
                if not v: continue      # nothing to do

                if k in DoxygenTask.PARS_handled_relation: pars[k] = self.handleInputRelation(v, self.doxynode.parent).abspath()
                if k in DoxygenTask.PARS_warning: Logs.warn('The parameter "%s" (%s) in the Doxygen file (%s) is not handled by waf-doxy, you\'ve been warned.' % (k, v, doxynode.abspath()))

        # load wscript pars and update self.pars
        skip = DoxygenTask.PARS_handled_specifically
        for k,v in self.wscript_pars.iteritems():
            if k in skip: continue              # handled elsewhere

            if v == None or v == '':            # an explicit None or an empty string deletes doxyfile pars (ie. resets to default)
                pars[k] = ''
                continue

            if isinstance(v, bool):             # bool handling
                if v: pars[k] = "YES"
                else: pars[k] = "NO"
                continue

            if isinstance(v, Node.Node):        # Node handling
                pars[k] = v.abspath()
                continue

            if isinstance(v, list):             # handle lists as good as possible (expecting paths, str/Node)
                vret = []
                for val in v:
                    if isinstance(val, Node.Node):  val = val.abspath()     # canonize it.
                    if (len(val.split()) > 1):      val = '"%s"'%val        # quote it.
                    vret.append(val)
                v = ' '.join(vret)                  # rejoin and continue with default handling... (for possible remaining relative paths)

            assert isinstance(v, str)           # any other type is wierd - or?

            if k in DoxygenTask.PARS_handled_relation: v = self.handleInputRelation(v, path.find_resource('wscript').parent).abspath()
            if k in DoxygenTask.PARS_warning: Logs.warn('The parameter "%s" (%s) in the wscript pars is not handled by waf-doxy, you\'ve been warned.' % (k, v))

            # default:
            pars[k] = v


        ### specialized handling

        # retrieve project name from task generator (defaults to pars), and assure surrounding double quotes.
        if self.project_name:
            pars['PROJECT_NAME'] = '"%s"' % self.project_name

        # if a pdffile should be generated we need latex to be generated!
        if self.pdfnode:
            gl = pars.get('GENERATE_LATEX')
            if gl and gl == "NO":
                Logs.warn("The Doxygen parameter GENERATE_LATEX has explicitly been set to NO, but `pdffile` was specified. Turning on GENERATE_LATEX.")
            pars['GENERATE_LATEX'] = 'YES'

        # setup INPUT and OUTPUT_DIRECTORY
        inputlist = []
        for node in self.getInputNodes():
            inputlist.append(node.get_src().abspath())
        pars['INPUT'] = ' '.join(inputlist)

        pars['OUTPUT_DIRECTORY'] = self.outputnode.abspath()

        # set self.pars (once only!)
        assert not self.pars
        self.pars = pars

        # check that at leas one format is enabled
        for fmt in DOXY_FMTS:
            if self.getBoolParameter(DoxygenTask.getGeneratorKey(fmt), doxydefault=True):
                self.executeDoxygen=True
                break
        else: # not broken, ie. not one format is enabled!
            self.executeDoxygen=False


### display the task:
    def getInstanceName(self):
        cname = self.__class__.__name__.replace('Task', '')
        return cname + ' (%s)' % ( self.project_name or Utils.to_hex(self.uid()) )

    def __str__(self):
        src_str = ' '.join( [ a.nice_path() for a in self.inputs + self.getInputNodes() ] )
        tgt_str = ' '.join( [ a.nice_path() for a in self.explicitoutputs ] )
        sep = ' -> '

        return '%s: %s%s%s\n' % (self.getInstanceName(), src_str, sep, tgt_str)

# def __repr__


### identify the task:

    @print_method
    def uid(self):
        """
        Return an identifier used to determine if tasks are up-to-date. Since the
        identifier will be stored between executions, it must be:

            - unique: no two tasks return the same value (for a given build context)
            - the same for a given task instance

        The pointer to the object (python built-in 'id') will change between build executions,
        and must be avoided in such hashes.

        # classname, inputs, explicitoutputs, inputnodes, outputnode, pars
        # the outputs of this task change as they are identified during post_run

        :return: hash value
        :rtype: string
        """
        try:
            return self.uid_
        except AttributeError:
            m = Utils.md5()
            up = m.update

            up(self.__class__.__name__.encode())
            up(self.hcode.encode())

            # this is all contained in self.pars, after _mergeDoxygenParameters()
            nodes = self.getInputNodes() + self.explicitoutputs + [ self.outputnode ]
            if self.doxynode: nodes.append(self.doxynode)

            for x in nodes:
                up(x.abspath().encode())

            up(str(self.wscript_pars).encode())

            self.uid_ = m.digest()
            return self.uid_
        assert False # unreachable code


    @print_method
    def getInputNodes(self):
        """"Returns the INPUT parameter as nodes"""

        try:
            return self.cache_inputnodes
        except AttributeError:
            pass

        relnode=None
        if self.wscript_pars.get('INPUT'):
            nodes = self.wscript_pars.get('INPUT')
            if isinstance(nodes, Node.Node): nodes = [ nodes ]
            if isinstance(nodes, str): nodes = shlex.split(nodes)
            relnode = self.generator.path.find_resource('wscript').parent # where the wscript pars come from
        elif self.doxyfile_pars.get('INPUT'):
            nodes = self.doxyfile_pars.get('INPUT')
            assert isinstance(nodes, str)   # you did something wierd if this throws!
            nodes = shlex.split(nodes)      # split, regarding quotes
            relnode = self.doxynode.parent  # where the doxyfile_pars have been loaded from
        else:
            self.generator.bld.fatal("No input spec found, doxygen default suppressed! Please specify doxyinput task parameter.")

        for idx, n in enumerate(nodes):
            if not isinstance(n, Node.Node):
                nodes[idx] = relnode.find_or_declare(n)  # if the node is not found it bld/src its expected to be created by another task in bld..

        self.cache_inputnodes = nodes
        return self.cache_inputnodes


    @print_method
    def runnable_status(self):
        '''based upon Task.Task.runnable_status'''

        if not self.explicitoutputs:
            return Task.SKIP_ME         # no outputs set!

        for t in self.run_after:
            if not t.hasrun:
                return Task.ASK_LATER

        bld     = self.generator.bld
        path    = self.generator.path

        # merge parameters once (this also takes care of relative paths)
        if not self.pars:
            self._mergeDoxygenParameters()


        # compute the signature
        try:
            new_sig = self.signature()
        except Errors.TaskNotReady:
            return Task.ASK_LATER

        # compare the signature to a signature computed previously
        key = self.uid()
        try:
            prev_sig = bld.task_sigs[key]
        except KeyError:
            Logs.debug("task: task %r must run as it was never run before or the task code changed" % self)
            return Task.RUN_ME

        if new_sig != prev_sig:
            return Task.RUN_ME

        # compare the signatures of the outputs
        for node in self.outputs:
            try:
                if node.sig != new_sig:
                    return Task.RUN_ME
            except AttributeError:
                Logs.debug("task: task %r must run as the output nodes do not exist" % self)
                return Task.RUN_ME

        return Task.SKIP_ME


    @print_method
    def scan(self):
        assert self.pars # must not be called prior _mergeDoxygenParameters()

        rec = self.getBoolParameter('RECURSIVE', doxydefault=True)

        # INPUT
        file_patterns = self.pars.get('FILE_PATTERNS', '').split()
        if not file_patterns:
            file_patterns = DOXY_FILE_PATTERNS

        exclude_patterns = [] # will be loaded later

        allnodes = self.getInputNodes()[:]  # copy!
        last_explicit_node = allnodes[-1]
        nodes = []

        for node in allnodes:
            if os.path.isdir(node.abspath()):
                allnodes.extend(node.ant_glob(file_patterns))                       # add matching files
                if rec: allnodes.extend(node.ant_glob("*",src=False, dir=True))     # if recursive, add all subdirs
            else:                                                                   # if node is a file
                for p in exclude_patterns:                                          # and there are exclude patterns
                    if fnmatchcase(node.abspath(), p): break                        # don't add nodes which match these
                else: # if break was not called and node is a file and recursion takes place!
                    nodes.append(node)                                              # otherwise append node to resultset (nodes)

            if node is last_explicit_node:
                exclude_patterns = self.pars.get('EXCLUDE_PATTERNS', '').split()    # from now on handle exclude patterns

        # LAYOUT_FILE
        layout = self.pars.get('LAYOUT_FILE')
        if layout:
            assert layout.startswith("/") # at this state it's expected to be absolute already...
            layout = self.generator.bld.root.search_node(layout)
            nodes.append(layout)

        return (nodes, self.pars)


    @print_method
    def run(self):

        # get context logger or use the global one
        lg = getattr(self.generator.bld, 'logger', None)
        if not lg: lg = Logs

        # doxypars to string
        doxypars = '\n'.join(['%s = %s' % (x, self.pars[x]) for x in self.pars])
        doxypars = doxypars.encode() # for python 3

        # helpers
        subminor=0
        if self.executeDoxygen: subminor = 1
        if self.pdfnode:        subminor += 2
        if self.debugnode:      subminor += 1

        if subminor:
            self.outputnode.mkdir()
        else:
            print self.__class__, "run called, though nothing needs to be executed, should have been skipped"
            return 0 # nothing to do - we should have been skipped actually

        subpos = [self.position[0], 0,  subminor] # mayor number, minor number, minor total
        def subminor(inc=True):
            if inc: subpos[1] += 1
            return "[%s-(%s/%s)] " % tuple(subpos) + self.getInstanceName() + ": "
        def logret():
            # if logret(ret): return ret
            if ret != 0:
                lg.debug(out)
                lg.error(err)
                return True
            elif not getattr(self.generator, 'quiet', None):
                lg.warn(err)
            else:
                lg.debug(err)
            return False # ret==0

        # write doxypars to file for debugging
        if self.debugnode:
            lg.info(subminor() + '"pars > %s"' % self.debugnode.nice_path())
            with open(self.debugnode.abspath(), 'w') as f:
                f.writelines(doxypars)

        ret = 0 # if nothing gets executed below thats considered allright!

        # run Doxygen
        if self.executeDoxygen:
            cmd = Utils.subst_vars(DOXY_STR, self.env)
            lg.info(subminor() + '"pars | %s"' % cmd)

            proc = Utils.subprocess.Popen(
                    cmd, shell = True,
                    stdin   = Utils.subprocess.PIPE,
                    stdout  = Utils.subprocess.PIPE,
                    stderr  = Utils.subprocess.PIPE
            )
            out, err = proc.communicate(doxypars)
            ret = proc.returncode
            if logret(): return ret

        # generate & copy pdf
        if self.pdfnode:
            assert self.executeDoxygen and self.getBoolParameter(DoxygenTask.getGeneratorKey('latex'), doxydefault=True)

            latexnode = self.getParameter('LATEX_OUTPUT', doxydefault=True)
            latexnode = self.outputnode.find_dir(latexnode)
            refman_makefile = latexnode.find_node('Makefile')

            if not latexnode:
                self.generator.bld.fatal(subminor(inc=False) + "No latex source found, check LATEX_OUTPUT and GENERATE_LATEX.")

            if not refman_makefile:
                self.generator.bld.fatal(subminor(inc=False) + 'No latex Makefile found check latex source: "%s"' % latexnode.nice_path())

            # run make
            cmd = ['make', '--directory', latexnode.abspath() , 'pdf']
            lg.info(subminor() + str(cmd))

            proc = Utils.subprocess.Popen(
                cmd,
                stdout    = Utils.subprocess.PIPE,
                stderr    = Utils.subprocess.PIPE
            )
            out, err = proc.communicate()
            ret = proc.returncode
            if logret(): return ret

            # and copy to pdfnode
            refman_node = latexnode.find_node('refman.pdf')

            if not refman_node:
                self.generator.bld.fatal(subminor(inc=False) + "make pdf failed, try 'cd %s; make pdf' to debug.")

            if refman_node == self.pdfnode: return ret # no copy necessary..
            cmd = ['cp', refman_node.abspath(), self.pdfnode.abspath()]
            lg.info(subminor() + str(cmd))
            ret = self.exec_command(cmd)

        return ret

    def post_run(self):
        #print "POI PostRun", self.generator.name
        # get the output nodes which we did not know prior execution
        # TODO -> deleting these nodes will not trigger a rebuild
        # TODO -> we could save the nodes as raw_deps?
        nodes = filter(lambda x: x not in self.outputs, self.outputnode.ant_glob('**/*', quiet=True))
        self.set_outputs(nodes)
        return super(DoxygenTask,self).post_run()

    #def install(self):
    #    if getattr(self.generator, 'install_to', None):
    #        update_build_dir(self.inputs[0].parent, self.env)
    #        pattern = getattr(self, 'instype', 'html/*')
    #        self.generator.bld.install_files(self.generator.install_to, self.generator.path.ant_glob(pattern, dir=0, src=0))



class tar(Task.Task):
    "quick tar creation"
    run_str = '${TAR} ${TAROPTS} ${TGT} ${SRC}'
    color   = 'RED'
    after   = ['doxygen']
    def runnable_status(self):
        for x in getattr(self, 'input_tasks', []):
            if not x.hasrun:
                return Task.ASK_LATER

        if not getattr(self, 'tar_done_adding', None):
            # execute this only once
            self.tar_done_adding = True
            for x in getattr(self, 'input_tasks', []):
                self.set_inputs(x.outputs)
            if not self.inputs:
                return Task.SKIP_ME
        return Task.Task.runnable_status(self)

    def __str__(self):
        tgt_str = ' '.join([a.nice_path() for a in self.outputs])
        return '%s: %s\n' % (self.__class__.__name__, tgt_str)



@feature('doxygen')
def process_doxygen(taskgen):
    """
    Process Doxygen generation.
    """
    # check for True explicitly, as a valid set denotes a partially disabled task, which will be handled by DoxygenTask.
    if taskgen.bld.options.doxygen_disable is True:
        return
    # otherwise it must be a set!
    assert isinstance(taskgen.bld.options.doxygen_disable, set)

    if taskgen.bld.env[DOXY_DISABLE_KEY] is True:
        return
    # otherwise it must be a set!
    assert isinstance(taskgen.bld.env[DOXY_DISABLE_KEY], set)


    # doxyfile: location of the doxyfile
    doxynode = None
    if getattr(taskgen, 'doxyfile', None):
        doxynode = taskgen.doxyfile
        if not isinstance(doxynode, Node.Node):
            doxynode = taskgen.path.find_resource(doxynode)
        if not doxynode:
            taskgen.bld.fatal('doxyfile: specified Doxygen file not found, None/string/Node allowed.')
    taskgen.doxynode = doxynode # XXX quick bug fix

    # the task instance
    dsk = taskgen.create_task('DoxygenTask') # XXX inputs is read from generator later, doxynode)


    if getattr(taskgen, 'doxy_tar', None):
        tsk = taskgen.create_task('tar')
        tsk.input_tasks = [dsk]
        tsk.set_outputs(taskgen.path.find_or_declare(taskgen.doxy_tar))
        if taskgen.doxy_tar.endswith('bz2'):
            tsk.env['TAROPTS'] = ['cjf']
        elif taskgen.doxy_tar.endswith('gz'):
            tsk.env['TAROPTS'] = ['czf']
        else:
            tsk.env['TAROPTS'] = ['cf']



#####
# waf "programs"

def doc(ctx): # executed by: def doc(dcx): dcx.load('documentation')
    print "Loading doc is a noop atm."
    # TODO this could load a logger?
    # ctx.logger = Logs.make_logger or something..


def options(opt):

    extended_formats=set(['pdf'] + DOXY_FMTS)

    def optparse_csv(option, opt_str, value, parser):
        assert value is None

        disabled_fmts = set()
        if parser.rargs and not parser.rargs[0].startswith('-'):
            val = parser.rargs[0].lower().split(',') # csv-list (lower case)

            # check if rargs[0] belongs to the disable-doxygen option
            for v in val:
                if v in extended_formats:
                    disabled_fmts.add(v)
                else:
                    disabled_fmts = None # not all values are correct -> assuming that rargs[0] did not belong here.
                    break

        if disabled_fmts:           # optional csv-list was found and accepted
            parser.rargs.pop(0)
            ret = disabled_fmts
        else:                       # no acceptanble csv list found --> default to: disable complete doxygen task
            ret=True

        setattr(parser.values, option.dest, ret)

    doxy_opts = opt.add_option_group("Doxygen Options")
    doxy_opts.add_option(
            '--disable-doxygen',
            help        = 'Disables the Doxygen feature, optionally ${default} followed by a csv-list of formats to disable (%s).' % ','.join(extended_formats),
            action      = 'callback',
            default     = set(), # nothing disabled, True = task disabled completely, set of formats: partially disabled.
            callback    = optparse_csv,
            dest        = 'doxygen_disable'
    )


def configure(cfg):
    cfg.find_program('doxygen', var='DOXYGEN')
    cfg.find_program('tar', var='TAR')
    cfg.find_program('dot')

    # did you load the options?
    try:
        cfg.env[ DOXY_DISABLE_KEY ] = cfg.options.doxygen_disable
    except AttributeError:
        cfg.fatal("Add options(opt): opt.load('%s')" % __name__)

    # check Doxygen version for compatibility
    supportedVersions=['1.8.1.2']
    version=None

    try:
        cfg.start_msg('Checking Doxygen version')
        version = cfg.cmd_and_log("doxygen -h  | awk '/Doxygen/ {print $3;}'").strip()
    except:
        cfg.fatal('could not evaluate Doxygen version')
        version = "na" # not available
    finally:
        cfg.all_envs['']['DOXYGEN_VERSION'] = version

    if version in supportedVersions:
        cfg.end_msg(version)
    else:
        cfg.end_msg('Doxygen version "%s" not tested with waf-doxygen' % version, color="YELLOW")
        version = None

    # load Doxygen default parameters into env
    try:
        cfg.start_msg('Loading the Doxygen defaults')
        fn = DOXY_DEFAULT_KEY + "." + (version or "cfg")

        doxynode = cfg.cachedir.find_node(fn)
        if not doxynode:
            doxynode = cfg.cachedir.make_node(fn)
            cfg.cmd_and_log(['doxygen', '-g', doxynode.abspath()])
        # more secure to access the default env ('') explicitly?
        #cfg.env[DOXY_DEFAULT_KEY] = DoxygenTask._loadDoxygenParametersFromNode(doxynode)
        cfg.all_envs[''][DOXY_DEFAULT_KEY] = DoxygenTask._loadDoxygenParametersFromNode(doxynode)
    except:
        cfg.fatal('could not load Doxygen defaults')
    else:
        cfg.end_msg(True)


#####
# Context for "doc" command
# To have the DocumentationContext available one must load this tool in wscript
# options(opt). Directly importing the DocumentationContext is not advised.

from waflib.Build import BuildContext
class DocumentationContext(BuildContext):
    cmd = 'doc'
    fun = 'doc'

    testing = False

    def getDoxygenDefaults(self):
        return self.all_envs[''][DOXY_DEFAULT_KEY]

    common_doxygen_pars = {      # symap2ic specific
        'OUTPUT_LANGUAGE'        : 'English',
        'EXTRACT_ALL'            : 'YES',
        'EXTRACT_PRIVATE'        : 'YES',
        'EXTRACT_STATIC'         : 'YES',
        'EXTRACT_LOCAL_CLASSES'  : 'YES',
        'HIDE_UNDOC_MEMBERS'     : 'NO',
        'HIDE_UNDOC_CLASSES'     : 'NO',
        'BRIEF_MEMBER_DESC'      : 'YES',
        'REPEAT_BRIEF'           : 'YES',
        'ALWAYS_DETAILED_SEC'    : 'NO',
        'INLINE_INHERITED_MEMB'  : 'NO',
        'FULL_PATH_NAMES'        : 'NO',
        'INTERNAL_DOCS'          : 'YES',
        'STRIP_CODE_COMMENTS'    : 'YES',
        'CASE_SENSE_NAMES'       : 'YES',
        'SHORT_NAMES'            : 'NO',
        'HIDE_SCOPE_NAMES'       : 'NO',
        'VERBATIM_HEADERS'       : 'YES',
        'SHOW_INCLUDE_FILES'     : 'YES',
        'JAVADOC_AUTOBRIEF'      : 'YES',
        'INHERIT_DOCS'           : 'YES',
        'INLINE_INFO'            : 'YES',
        'SORT_MEMBER_DOCS'       : 'YES',
        'DISTRIBUTE_GROUP_DOC'   : 'NO',
        'TAB_SIZE'               : '4',
        'GENERATE_TODOLIST'      : 'YES',
        'GENERATE_TESTLIST'      : 'YES',
        'GENERATE_BUGLIST'       : 'YES',
        'MAX_INITIALIZER_LINES'  : '30',
        'OPTIMIZE_OUTPUT_FOR_C'  : 'NO',
        'SHOW_USED_FILES'        : 'YES',
        'QUIET'                  : 'NO',
        'WARNINGS'               : 'YES',
        'WARN_IF_UNDOCUMENTED'   : 'YES',
        'RECURSIVE'              : 'NO',
        'FILTER_SOURCE_FILES'    : 'NO',
        'SOURCE_BROWSER'         : 'YES',
        'INLINE_SOURCES'         : 'YES',
        'REFERENCED_BY_RELATION' : 'YES',
        'REFERENCES_RELATION'    : 'YES',
        'ALPHABETICAL_INDEX'     : 'YES',
        'COLS_IN_ALPHA_INDEX'    : '4',
        'GENERATE_HTML'          : 'YES',
        'HTML_ALIGN_MEMBERS'     : 'YES',
        'GENERATE_HTMLHELP'      : 'YES',
        'GENERATE_CHI'           : 'NO',
        'BINARY_TOC'             : 'NO',
        'TOC_EXPAND'             : 'YES',
        'DISABLE_INDEX'          : 'NO',
        'ENUM_VALUES_PER_LINE'   : '4',
        'GENERATE_TREEVIEW'      : 'YES',
        'TREEVIEW_WIDTH'         : '250',
    }

    # grep usageExample -A99 src/waf/documentation.py
    def usageExample(dcx): # dcx == self
        """
        should work in halbe repo!

        def doc(dcx):
            dcx.usageExample() # or copy and paste the below
        """

        print "DocumentationContext: getDoxygenDefaults()", dcx.getDoxygenDefaults()
        print "DocumentationContext: common_doxygen_pars", dcx.common_doxygen_pars

        dcx(
                features    = 'doxygen',                   # the feature to use
                name        = "Testing Doxygen Halbe",     # overrides doxy-par: PROJECT_NAME

                doxyfile    = 'doc/doxyfile',              # a doxyfile, use doxygen -g to generate a template
                pars        = {
                    'STRIP_FROM_PATH'   : dcx.path.get_src().abspath(),
                },                                         # a dict of doxy-pars: overrides doxyfile pars

                doxyinput   = "hal",                       # overrides doxy-par: INPUT (list of paths)
                doxyoutput  = "documentation-test",        # overrides doxy-par: OUTPUT_DIRECTORY, (a path)
                pdffile     = 'HMF_HALbe-manual-test.pdf', # a pdf file to generate, relative to OUTPUT_DIRECTORY
                doxydebug   = True,                        # generate debug output (the final pars to OUTPUT_DIRECTORY/doxypars.debug)
                quiet       = True                         # suppress all make and doxygen output (if it does not fail)
        )

# The doxy-pars from the doxyfile are least important and overridden by the
# pars parameter. However, highest relevance have name, doxyinput and
# doxyoutput.

# If name is not specified the task name will be derived from doxy-par PROJECT_NAME.
# If no OUTPUT_DIRECTORY is specified, doxyfile_as_node.parent.get_bld() will be tried

# * Input parameters (i.e. not only INPUT, but also LAYOUT_FILE) from the
# doxyfile are interpreted relative to that using find_or_declare()
# * Input parameters from the wscript (pars and doxyinput) are interpreted
# relative to the containing wscript
# * Output parameters are interpreted relative to OUTPUT_DIRECTORY, as doxygen does it and OUTPUT_DIRECTORY itself is interpreted relative to bld_path.
