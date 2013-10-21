#! /usr/bin/env python
# encoding: UTF-8
# Kai Husmann 2013

# Integrates jenkins commands into symap2ic waf (symap2ic/src/jenkins)

from waflib import Logs, Context, Options
import os, re

TOOL            = "Jenkins Integration"

### new style (new flow)
# == trigger ==
# bash -ce "cd -P \"$WORKSPACE\";pwd;./waf jenkins trigger|mailtrigger" || exit 0; exit 42
# == build script preamble ==
# test -x waf || git clone git@gitviz.kip.uni-heidelberg.de:symap2ic.git -b symwaf2ic .waf-program .;make -C .waf-program; ln -s .waf-program/waf
# ### nope: test -f wscript || ./waf setup --project=<your-project-set>
# ./waf setup --project=<your-project-set> repos-update
# OR (planned): ./waf jenkins preamble --project=<your project set>
# OR (planned): ./waf jenkins auto # project set will be derived from JOB_NAME
# <continue as you like>


def options(opt):
    ws = os.getenv('WORKSPACE')
    jn = os.getenv('JOB_NAME')

    if not (ws and jn):
        return

    ws = opt.root.find_node(ws)
    if not ws == opt.path:
        Logs.debug("%s: WORKSPACE does not equal current dir" % TOOL)
        #opt.fatal
        return

    # Jenkins environment available
    JenkinsContext.jenkins_workspace    = ws
    JenkinsContext.jenkins_job_name     = jn
# TODO The subcommand class decorator should move into its own file

# decorator for classes which offer subcommands (methods named "^sb_.*$")
def subcommand_class(klass):
    """
    This is a decorator for classes that handle waf sub-commands.

    Sub-commands are methods which match the pattern
    r'^((sb|subcommand)_)(?P<command>.*)$'
    One can override this pattern adding a variable named subcommand_pattern to
    the decorated class. Note that ?P<command> is a necessary named match group
    specifying how the command is named.

    A valid sub-command method should have the signature def method(self,
    rargs), where rargs represent the remaining commands (waf,
    Options.commands). If no method defines a help command a default one will
    be generated.

    If the Context method execute is not overridden a default one will be
    generated. The decorated class then needs the variable recurse_mandatory
    which defines if the command should recurse into the wscripts prior
    sub-command execution (True/False/None, None hereby represents
    do-not-recurse-at-all).
    If a default execute method was created it will run pre|post_execute
    methods if available (pre, recurse, subcommands, post).
    """

    # as of now, we expect this to be derived from Context.Context
    assert klass.__base__ == Context.Context
    # assert Context.Context in klass.__mro__ # weaker constraint


    ### parse for subcommands
    subcommands = {}    # command to function dict
    longest=5           # for formatting help (at least more than 'help' itself)

    import re
    p = getattr(klass, 'subcommand_pattern', None) or re.compile(r'^((sb|subcommand)_)(?P<command>.*)$')

    for attr in dir(klass):
        m = p.match(attr)
        if m:
            cmd = m.groupdict()['command']
            subcommands[cmd] = attr
            if len(cmd) > longest: longest = len(cmd)

    if longest > 25: longest = 25 # subcommand with over 25 letters: insert newline in help output
    longest += 1 # for the colon following a command in the help listing


    ### register help
    if not 'help' in subcommands: # or call sb_help if exists by subcommand_help?
        def subcommand_help(self, rargs=None):
            """Shows the command help, or run "./waf %s help <sub-command>" for details on a sub-command"""

            def split_doc(doc):
                doc = doc.__doc__
                if not doc:                 return None, None
                cmd_doc = doc.strip().split('\n')
                head = cmd_doc[0].strip()
                if len(cmd_doc) == 1:       return head, None
                tail = '\n'.join(cmd_doc[1:]).strip()
                return head, tail

            avail = self.getSubcommands()
            if rargs and rargs[0] in avail:
                cmd = rargs[0]
                f = getattr(self, avail[cmd])
                head, tail = split_doc(f)
                if not (head and tail):
                    print "No detailed documentation available for %s command %s\n" % (self.cmd, cmd)
                else:
                    print "=== Details of %s command: %s ===" % (self.cmd, cmd)
                    print
                    print "== %s ==" % head
                    print '\n%s\n' % tail
                    return 0 # and we quit

            #head, tail = split_doc(self)

            print "=== waf command: %s ===" % klass.cmd
            print
            klass.detailed_doc = getattr(klass, 'detailed_doc', None)
            if klass.detailed_doc:
                print klass.detailed_doc + '\n'

            print "== Available sub-commands =="
            print "(", ', '.join(avail.keys()),')'
            print

            repl = "  * %-"+str(longest)+"s %s"
            repl_l = "  * %s\n" + (' '*(5+longest)) + "%s"
            for cmd, func_name in avail.iteritems():
                f = getattr(self, func_name)
                head, tail = split_doc(f)
                head = head or "no information available, please turn to the code"
                cmd = cmd+":" # necessary for alignment
                if len(cmd) > longest:
                    print repl_l % (cmd, head)
                else:
                    print repl % (cmd, head)
            print

            for cmd, func_name in avail.iteritems():
                f = getattr(self, func_name)
                head, tail = split_doc(f)
                if not (head and tail):
                    continue # no detailed info available

                print "== %s: %s ==" % (cmd, head)
                print '\n%s\n' % tail

            return 1 # raise SystemExit(1)

        subcommand_help.__doc__ %= klass.cmd
        klass.subcommand_help = subcommand_help
        subcommands['help'] = 'subcommand_help'


    ### the handler is not optional!
    def subcmdhandler(self, rargs, allowed_commands=True, default_command="help"):
        if allowed_commands is True:
            allowed_commands = self.getSubcommands()

        assert isinstance(allowed_commands, dict), "The subcommands dictionnary must be a dict"
        assert isinstance(rargs, list), "The remaining arguments must be a list of strings"

        r = (rargs and rargs[0]) or None # ie. rargs[0] or None

        if r in allowed_commands:
            f = getattr(self, allowed_commands[r]) # it the dict is correct, this must not fail
            rargs.pop(0) # a command was found, swallow it, fails if None is a key in the dict
        elif default_command: # r is None or unknown, but default is set
            f = getattr(self, allowed_commands[default_command]) # run the default command (help)
        else:
            return # no command and no default, so we're finished here
        assert f

        # call the active command, passing the remaining commands
        r = f(rargs) # XXX: should subcommands also get the active list of allowed commands?

        if r is True:               # run again to search for further subcommands, but do not default anymore
            return self.subcmdhandler(rargs, default_command=None)
        elif r is False:            # no further options expected
            return
        elif isinstance(r, int):    # an int denotes a (controlled) system exit
            raise SystemExit(r)

        assert isinstance(r, dict), "function " + f + " did not return a valid remaining commands indicator (bool, int or dict)"
        return self.subcmdhandler(rargs, allowed_commands=r, default_command=None)

    klass.getSubcommands = staticmethod(lambda: subcommands.copy())
    klass.subcmdhandler = subcmdhandler


    ### the execute method (which makes the mayor command available!)
    # The execute method of the Context.Context class fails on a command which
    # has no function in the main wscript, but this is in most cases undesired
    # behaviour for a subcommand context, thats why the execute function is
    # overridden in that case. Implementation needs the attribute
    # recurse_mandatory, which can be one of:
    #   * None: do not recurse at all, just call the sub-command handler
    #   * False: recurse, but don't do this mandatory
    #   * True: recurse mandatory, the wscript must implement an equally named function (Context.Context default)

    #print "klass", klass.execute.__func__
    #print "Ctx", Context.Context.execute.__func__
    #print "base", klass.__base__.execute.__func__
    if klass.execute.__func__ == Context.Context.execute.__func__:
        # context execute method was __not__ overridden
        recurse_mandatory = getattr(klass, 'recurse_mandatory') # if you don't override execute you must specify the attribute recurse_mandatory, @see above
        def execute(self):
            """auto generated execute function for subcommand waf Contexts"""
            pre = getattr(self, 'pre_execute', None)
            if pre and (not pre() is True):
                return # if self.pre_execute() did not return True

            global g_module
            if isinstance(recurse_mandatory, bool):
                self.recurse([os.path.dirname(Context.g_module.root_path)], mandatory = recurse_mandatory)
            else: assert recurse_mandatory is None

            self.subcmdhandler(Options.commands)

            post = getattr(self, 'post_execute', None)
            if post: post()
        klass.execute = execute

    return klass

@subcommand_class
class JenkinsContext(Context.Context):
    """For easy Jenkins integration: run ./waf jenkins help for details"""
#
#    Symap2ic Jenkins integration
#
#    The command jenkins is for super cool things
#    """
    cmd = 'jenkins'
    recurse_mandatory   = None # None=>do not recurse at all

    jenkins_workspace   = None # options changes this value if WORKSPACE and JOB_NAME is available
    jenkins_job_name    = None

    exitcode_build      = 1 # crash also leads to build
    exitcode_dontBuild  = 0

    detailed_doc ="""\
The ./waf jenkins command only works in a Jenkins environment. The environment
is detected checking the variables WORKSPACE and JOB_NAME. If these are not
around during options.load("jenkins") the jenkins command is not available.

The jenkins command is a sub-command structure, ie., jenkins commands are
executed as such: ./waf jenkins [<subcommand> <parameters>]*

Jenkins build trigger usage example:
    bash -ce "cd -P \"$WORKSPACE\";pwd;./waf jenkins trigger|mailtrigger" || exit 0; exit 42

And as first statements in the build execution please run:
    test -f wscript || git clone git@gitviz.kip.uni-heidelberg.de:symap2ic.git .
    ./waf set_config <the_project_to_build>
    ./waf up

Finally add an "Editable Email Notification" to the job (if mailtrigger was used):
    Check that the "Pre-send Script" executes the groovy "src/jenkins/mailman.presend"
    (copy the code therein, or set it as default pre-send script). And set a trigger,
    sending to "Recipient List" on "Failure" only.
"""

    def pre_execute(self):
        if not JenkinsContext.jenkins_workspace:
            try:
                self.subcmdhandler(["help"])
            except SystemExit:
                pass

            self.fatal( """The 'jenkins' command only works in a Jenkins environment, ie. WORKSPACE and JOB_NAME must be set.
    A valid Jenkins environment is detected if the environment variables
    WORKSPACE and JOB_NAME are set, and the working directory must equal
    $WORKSPACE. To simulate a valid Jenkins environment run:

    WORKSPACE=$PWD JOB_NAME=test ./waf jenkins # or whatever your command(s)
            """)
            assert False # non-reachable code
        else:
            return True # continue normal execution...

    def sb_trigger(self, rargs):
        """\
Simple build trigger

This trigger just checks for upstream changes in the active project (head -1 repo.conf).
        """

        # minimal symap2ic test
        symwaf2ic_ok = os.path.isdir(".symwaf2ic") and os.path.isfile(".symwaf2ic.conf.json") and os.path.isfile(".symwaf2ic.repo.conf")
        if not symwaf2ic_ok:
            Logs.warn("jenkins trigger: symwaf2ic incomplete --> build")
            return self.exitcode_build

        # fetch origin
        errcode = self.exec_command('./waf repos-fetch')
        #errcode = self.exec_command('./waf mr-run "git fetch --no-progress"')
        #errcode = self.exec_command('./waf mr-run git fetch --no-progress') # this should work
        if errcode:
            Logs.error("Fetching origin updates failed!")
            return self.exitcode_build

        # check status
        errcode = self.exec_command('./waf mr-run git status 2>/dev/null | grep "^# Your branch is behind \'.*\'.*$"')
        if errcode: # grep failed
            print "No changes found!"
            return self.exitcode_dontBuild
        else:
            print "Changes found!"
            return self.exitcode_build

        assert False # unreachable code

