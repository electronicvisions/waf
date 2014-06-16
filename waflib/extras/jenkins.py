#! /usr/bin/env python
# encoding: UTF-8

# Kai Husmann 2013

# Integrates jenkins commands into symap2ic waf (symap2ic/src/jenkins)

from waflib import Logs, Context, Options
from waflib.extras import mr
import os, re, subprocess, platform

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
    pass


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
                Logs.debug("env: pre_execute did not return true, stopping execution of {}".format(klass.cmd))
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
    jenkins_build_number= None
    jenkins_log_dir     = "jenkins.log"

    exitcode_doNotBuild         = 0     # normal execution -> no build, we need to turn around the exitcode in the jenkins build trigger script
    exitcode_build              = 42    # crash also leads to build, thats why we use non-zero to indicate a build
    exitcode_buildDueFailure    = 101   # something unexpected, trigger a build in the hope of a jenkins admin registering it...
    exitcode_buildDueOldFlow    = 102   # components directory in workspace found

    # exitcodes outside a build trigger...
    exitcode_OK                 = 0
    exitcode_Failure            = 11    # failure

    logformat                   = '-n1 --pretty=oneline'

    detailed_doc ="""\
The ./waf jenkins command only works in a Jenkins environment. The environment
is detected checking the variables WORKSPACE and JOB_NAME. If these are not
around during options.load("jenkins") the jenkins command is not available.

The jenkins command is a sub-command structure, ie., jenkins commands are
executed as such: ./waf jenkins [<subcommand> <parameters>]*

Jenkins build trigger usage example:
    bash -ce "cd -P \\"$WORKSPACE\\";pwd;./waf jenkins trigger|mailtrigger" || exit 0; exit 42

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
        print # separate jenkins from waf "default" output.
        if (len(Options.commands) < 1 or Options.commands[0]=="help"):
            return True

        ws = os.getenv('WORKSPACE')
        jn = os.getenv('JOB_NAME') or "test"
        bn = os.getenv('BUILD_NUMBER') or "1"

        if not (ws and jn and bn):
            print "Could not load jenkins environment..."
            print "WS: {}, JN: {}, BN: {}".format(ws, jn, bn)
            self.fatal("""\
The 'jenkins' command only works in a Jenkins environment, ie. the environment variable WORKSPACE must be set.
For testing purposes JOB_NAME and BUILD_NUMBER default to "test" and "1".

To simulate a valid Jenkins environment run:

    WORKSPACE=$PWD ./waf jenkins {opts} # or whatever your command(s)
    or
    export WORKSPACE="$PWD"
    ./waf jenkins {opts}
""".format(opts=" ".join(Options.commands)))
            assert False

        ws = self.root.find_node(ws)
        if not ws == self.path:
            self.fatal("env: %s: WORKSPACE does not equal current dir" % TOOL)

        # Jenkins environment available
        JenkinsContext.jenkins_workspace    = ws # is a waf node!
        JenkinsContext.jenkins_job_name     = jn
        JenkinsContext.jenkins_build_number = bn

        return True

    def old_flow_check(self):
        """returns True if a directory named "components" is found in the workspace, i.e. old flow!"""

        # TODO this is just a hack for now... someday it should be removed, at least when a components folder is added to the new flow!
        oldflow = self.jenkins_workspace.find_dir('components')

        if oldflow:
            Logs.warn("Old flow found (directory 'components' in workspace.")
            return True
        else:
            return False

    def minimal_symwaf2ic_test(self):
        """returns False if no symwaf2ic checkout was found"""

        symwaf2ic_ok = os.path.isdir(".symwaf2ic") and os.path.isfile(".symwaf2ic.conf.json") and os.path.isfile(".symwaf2ic.repo.conf")
        if not symwaf2ic_ok:
            Logs.warn("jenkins trigger: symwaf2ic incomplete --> build")
            return False
        #else
        return True

    def fetch_upstream(self):
        """Fetches upstream changes (git fetch) and returns False if an error occurs"""
        try:
            print("Fetching upstream..."),
            self.cmd_and_log(['./waf', 'repos-fetch'], quiet=Context.BOTH)
            # TODO filter stderr for basic output? (output of fetch goes to stderr!)
            print("OK.")
        except Exception as e:
            print("FAILURE!")
            Logs.error("Fetching origin updates failed --> build due failure!")
            print(e.stdout, e.stderr)
            return False
        # else:
        return True



    ############################
    ### new flow trigger system


    def sb_BuildTrigger(self, rargs):
        """\
Jenkins build trigger that checks for new commits in the upstream branches

I.e. it checks if the last commit of the upstream branch resp. to the local
checkout differs from the last local commit. Also triggers on local changes,
but such should not occur in a Jenkins environment, anyways.
        """
        print
        Logs.info("Executing Symwaf2ic Jenkins: BuildTrigger")

        if self.old_flow_check():
            Logs.warn("Old flow detected!")
            return self.exitcode_buildDueOldFlow

        ### Acquiring data: check symwaf2ic and
        print # make output a bit human readable..
        Logs.info("Acquiring data...")
        if not self.minimal_symwaf2ic_test():
            return self.exitcode_buildDueFailure

        # design notes:
        #  Buildtrigger fetches, but does not merge (no pull!)
        #  A triggered build might be executed on another machine
        #  -> next check will still find differences b/n local and fetch
        #  -> so we must compare prefetch and postfetch, but not local!
        #  -> the build step then changes local->recentfetch to get changes and authors.

        print("Parsing pre_fetch origin..."),
        pre_fetch=self.getOriginCommits()
        print("OK.")

        if not self.fetch_upstream():
            return self.exitcode_buildDueFailure

        print("Parsing post_fetch origin..."),
        post_fetch=self.getOriginCommits()
        print("OK.")

        # assert dependencies (both commands should return the same set of repositories)
        # (we've not jet run any --update-repos)
        okeys = set(pre_fetch.keys())
        lkeys = set(post_fetch.keys())
        assert okeys == lkeys, "if this fails we probably must change this assertion and instead trigger a build."
        del okeys, lkeys
        print # make output a bit human readable..


        ### Comparing pre and post fetch
        Logs.info("Looking for changes...")
        build_required = False
        for repo in pre_fetch:
            pre     =   pre_fetch[repo]
            post    =   post_fetch[repo]

            if pre == post:
                print "Unchanged:", pre.shortstring()
                continue

            # else:
            build_required=True # we could break here, but we want a nice and complete output...
            Logs.warn("Changed: {}".format(pre.getCommitRange(post, nice=True)))
        print # make output a bit human readable..


        ### Conclusion
        hostname = platform.node()

        print "The test was performed on host '{}' (workspace: '{}')".format(hostname, self.jenkins_workspace.abspath())
        if build_required:
            Logs.info("Changes have been found (exitcode: {})!".format(self.exitcode_build))
            return self.exitcode_build
        else:
            Logs.info("No changes found (exitcode: {})!".format(self.exitcode_doNotBuild))
            return self.exitcode_doNotBuild

        assert False, "unreachable code"



    def sb_BuildPreamble(self, rargs):
        """\
Simple tests to check if the workspace is in a good mood today.

Failes if there is a bad wscript (e.g. old flow) in the workspace, or in general if a clean up of the workspace is necessary =>

Usage: ./waf jenkins BuildPreamble || rm -rf *; exit 1 # to delete the bad workspace and fail the build
"""
        build_number = JenkinsContext.jenkins_build_number
        if not build_number:
            Logs.error("Could not load BUILD_NUMBER from the environment - are we run by a Jenkins build script?!")
            return self.exitcode_Failure

        if self.old_flow_check():
            Logs.error("Old flow directory 'components' found!")
            return self.exitcode_Failure

        return self.exitcode_OK


    def sb_getAuthors(self, rargs):
        """
Creates authors and changelog file in jenkins.log/BUILD_NUMBER

The authors and the changelog are deduced from the git log 'diff' of the origin (last fetched upstream) and the active branch.
"""
        Logs.info("Executing Symwaf2ic Jenkins: getAuthors")
        build_number = JenkinsContext.jenkins_build_number

        if not build_number:
            Logs.error("Could not load BUILD_NUMBER from the environment - are we run by a Jenkins build script?!")
            return self.exitcode_Failure

        if self.old_flow_check():
            Logs.error("Old flow detected!")
            return self.exitcode_Failure
        print # make output a bit human readable..


        ### Acquiring data: check symwaf2ic and fetch upstream TODO load manager
        Logs.info("Acquiring data...")
        if not self.minimal_symwaf2ic_test():
            return self.exitcode_Failure
        if not self.fetch_upstream():
            return self.exitcode_Failure

        local_commits, origin_commits = self.getLatestCommits()

        # preparing the file system
        jenkins_log = self.jenkins_workspace.make_node(self.jenkins_log_dir)
        #jenkins_log = jenkins_log.make_node(build_number)
        jenkins_log.mkdir()

        fn_authors      = jenkins_log.make_node(build_number.zfill(4)+".authors").abspath()
        fn_changelog    = jenkins_log.make_node(build_number.zfill(4)+".changelog").abspath()
        assert not ( os.path.exists(fn_authors) or os.path.exists(fn_changelog) ), "Old authors or changelog file found in recent build number WHAT!!!"
        workspace_path  = self.jenkins_workspace.abspath()


        ### Calculating changes (commit-diff, authors, chlog...)
        Logs.info("Retrieving authors and changelog...")
        authors=set()

        cwd = os.getcwd()
        for repo in origin_commits:
            local = local_commits[repo]
            origin = origin_commits[repo]

            if local == origin:
                print "Unchanged:", origin.shortstring()
                continue

            # else:
            print "Changed:  ", local.getCommitRange(origin, nice=True)

            with open(fn_changelog, "a") as f:
                f.write('# {} #\n'.format('#'*62))
                f.write("# {:>62} #\n\n".format(local.getCommitRange(origin, nice=True)))

            # retrieve authors and remove redundant entries (multiple commits)
            os.chdir(os.path.join(workspace_path, repo))
            p = ProcessPipe('git', 'log', local.getCommitRange(origin))
            p.add( 'tee', '-a', fn_changelog )
            p.add( 'grep', '^Author:' )
            p.add( 'sed', 's/^Author: //' ) # remove author
            #p.add( 'sort' )
            #p.add( 'uniq' )
            #p.add( 'tee', '-a', fn_authors ) # we append from each repo
            # print p # the pipe...
            p = p.execute() # returns the final process (Popen)

            for line in p.stdout:
                authors.add(line) # newline at the end of each author is kept...
            p.wait()

            # end changelog with a newline to separate it from the following one.
            with open(fn_changelog, "a") as f:
                f.write('\n')
        # done: for repo in origin_commits
        os.chdir(cwd)
        print # make output a bit human readable..


        # TODO also load repo managers? -> but only for those with changes?!

        # checking project managers
        prj = os.getenv("SYMWAF2IC_PROJECT") # TODO any better option to pass the SYMWAF2IC_PROJECT info to waf?
        managers = []
        if prj:
            pdb = mr.Project_DB(self.path.find_node('.symwaf2ic/mr_conf/repo_db/project_db.json'))
            managers = pdb.getManagers(prj)

        if not authors:
            Logs.info("No authors found.")
            assert not ( os.path.exists(fn_authors) or os.path.exists(fn_changelog) ), "WIERD: No authors found but authors/changelog files created?"
            with open(fn_changelog) as f:
                f.write("No specific changes, triggered for external reasons.\n")
            if (managers):
                Logs.info("Adressing the managers only...")
            else:
                return self.exitcode_OK


        # Add managers to authors list
        if managers:
            print "Adding the managers of '{}':".format(prj)
            for m in managers:
                authors.add(m+'\n')
                print ', '.join(managers)


        # else: Authors available/ CHANGES HAVE BEEN FOUND and/or managers


        ### Filter out external mails and stuff
        authors = self.filterAuthors(authors) #  returns a list
        if not authors:
            Logs.info("All authors have been filtered!")
            return self.exitcode_OK


        ### Conclusion
        print "The //potential// vandals:"
        with open(fn_authors, 'w') as f:
            for a in authors:
                print a,
                f.write(a)

        assert( os.path.isfile(fn_authors) )    # must have been created at this point!
        assert( os.path.isfile(fn_changelog) )  # like above

        # say goodby
        Logs.info("""
            Beware, the vandals responsible for this build are known.
            Pray that you did not introduce a regression!

            Let the build commence!
            """
        )
        return self.exitcode_OK


    ###################
    ### Helper methods

    def getLocalCommits(self):
        # find latest local commits
        cmd = (
                './waf',
                'mr-xrun',
                '--',
                'git log {logformat}'.format(logformat=self.logformat)
        )
        local_commits = parseLog(cmd, self.jenkins_workspace.abspath())
        return local_commits

    def getOriginCommits(self):
        # find according (same branch) upstream (last fetch) commits
        cmd = (
                "./waf",
                "mr-xrun",
                "--",
                "ref=`git symbolic-ref -q HEAD` # refs/heads/<branchname>",
                #"# upstream: The name of a local ref which can be considered “upstream” from the displayed ref (KHS: ie, origin)",
                "branch=`git for-each-ref --format='%(upstream:short)' $ref` # origin/<branchname>",
                "git log {logformat} $branch".format(logformat=self.logformat)
        )
        origin_commits = parseLog(cmd, self.jenkins_workspace.abspath())
        return origin_commits


    ### returns latest local and origin commit of the current checked out branch for every mr-managed repo.
    def getLatestCommits(self):
        # git log format, latest and a format thats understood by parseLog

        local_commits=self.getLocalCommits()
        origin_commits=self.getOriginCommits()

        # assert dependencies (both commands should return the same set of repositories)
        okeys = set(origin_commits.keys())
        lkeys = set(local_commits.keys())
        assert okeys == lkeys
        del okeys, lkeys

        return ( local_commits, origin_commits )


    ### recieves a list/set of unique author lines and filteres them according to the rules below
    def filterAuthors(self, authors):
        Logs.info("Filtering the emails")

        ### filter authors that are not internal ones
        # specify regex patterns to be matched against the authors email addresses
        our_authors = [
            '^.*@(.*\.)*tu-dresden\.de$',
            '^.*@kip\.uni-heidelberg\.de$'
        ]

        exclude_anyway = [
            '^root@kip\.uni-heidelberg\.de$',
            '^postmaster@kip\.uni-heidelberg\.de$',
            '^none@kip\.uni-heidelberg\.de$',
            '.*\$.*'
        ]


        # to extract the mail address from the "My name is somebody <mail@provider.cc>\n"
        mailmatcher=re.compile('^.*<(?P<mail>.*)>$')

        # precompile the author-mailaddress patterns
        for idx, val in enumerate(our_authors):
            our_authors[idx] = re.compile(val)

        for idx, val in enumerate(exclude_anyway):
            exclude_anyway[idx] = re.compile(val)


        ### apply the filter
        remaining_authors=[]
        anymailfiltered=False
        for a in authors:
            mail = mailmatcher.match(a)
            if not mail:
                Logs.warn("WARN: Wierd mail filtered:    '{}'".format(a[:-1]))
                anymailfiltered = True
                continue
            #else
            mail = mail.group('mail')
            #print "--{}--".format(mail)

            mail_known = False
            for r in our_authors:
                if r.match(mail):
                    mail_known = not any([e.match(mail) for e in exclude_anyway])
                    break
            if mail_known:
                remaining_authors.append(a)
            else:
                print "INFO: External mail filtered: '{}".format(a), # there is a newline in the author string
                anymailfiltered= True

        if not anymailfiltered:
            print "No mails have been filtered."
        print # beautiful output
        return remaining_authors


    def sb_createArtifact(self, rargs):
        """\
Creates a tar archive named artifact.tgz containing directories and files specified as rargs.

Usage ./waf jenkins createArtifact path/to/somedir path/to/somefile, rel. to cwd.
NB.; Excludes are momentarily not available.
"""
        cwdn = self.path # current working dir node
        assert cwdn.abspath() == os.getcwd(), "current working dir does not equal waf context path" # that's wierd and not handled

        Logs.info("Creating artifacts in '{}': {}".format(cwdn, rargs)) # TODO: project, not path (or also show project @see show_repos!

        if len(rargs) < 1:
            self.fatal("Cannot create an artifact-archive if you do not specify any artifacts:\n\tUsage: ./waf jenkins createArtifact path/to/artfact1 ...")

        tarnode = cwdn.make_node("artifact.tgz")
        tarnode.delete()
        cmd = [
                'tar',
                # TODO default excludes: .git .waf-*
                '-c{v}zf'.format(v="v"*Logs.verbose), # create [verbose] zip file
                tarnode.abspath()
        ]

        noartifactfound = True
        for r in rargs:
            n = self.path.find_node(r)
            if n:
                cmd.append(n.path_from(cwdn))
                noartifactfound = False
            else:
                Logs.warn("Could not find artifact '{}'".format(r))

        if noartifactfound:
            self.fatal("Could not find any artifact! This is considered an error. You specified these artifacts:\n{}".format(rargs))

        try:
            self.cmd_and_log(cmd, quiet=Context.BOTH)
        except Exception as e:
            Logs.error("Creation of '{}' failed".format(tarnode))
            print(e.stdout, e.stderr)
            return self.exitcode_Failure

        # else:
        return self.exitcode_OK


################################
### Older and obsolete code

    def sb_trigger(self, rargs):
        """\
Simple build trigger

This trigger just checks for upstream changes in the active project (head -1 repo.conf). Triggers also on changes on other branches, use the jenkins trigger for better logic.
        """

        if not self.minimal_symwaf2ic_test():
            return self.exitcode_build
        if not self.fetch_upstream():
            return self.exitcode_buildDueFailure

        # check status
        errcode = self.exec_command('./waf mr-run git status 2>/dev/null | grep "^# Your branch is behind \'.*\'.*$"')
        if errcode: # grep failed
            print "No changes found!"
            return self.exitcode_doNotBuild
        else:
            print "Changes found!"
            return self.exitcode_build

        assert False # unreachable code



    def sb_mailtrigger(self, rargs):
        """
OBSOLETE: Build trigger with blame-mail support

OBSOLETE: use 'BuildTrigger' and 'getAuthors' instead.

This trigger fetches all upstream changes and compares the commits with the
local state. The authors of the upstream changes are saved to a file named authors.
This file can later be used - in cooperation with mail-ext-plugin - to send
blame mails to the vandals (i.e. those who probably broke the build).
        """

        print
        Logs.info("Executing Symwaf2ic Jenkins MailTrigger")

        print # make output a bit human readable..
        Logs.info("Acquiring data...")
        if not self.minimal_symwaf2ic_test():
            return self.exitcode_buildDueFailure
        if not self.fetch_upstream():
            return self.exitcode_buildDueFailure

        fn_authors      = self.jenkins_workspace.make_node("authors").abspath()
        fn_changelog    = self.jenkins_workspace.make_node("changelog").abspath()
        curdir          = os.getcwd()

        #origin_commits = parseLog(cmd_fetch_log)
        #checkout_commits = parseLog(cmd_checkout_log)

        local_commits, origin_commits = self.getLatestCommits()

        # assert dependencies (both commands should return the same set of repositories)
        okeys = set(origin_commits.keys())
        lkeys = set(local_commits.keys())
        assert okeys == lkeys
        del okeys, lkeys

        # do some initial cleanup, if these files should be kept the build script must
        # copy them to some log folder
        if os.path.isfile(fn_authors): os.remove(fn_authors)
        if os.path.isfile(fn_changelog): os.remove(fn_changelog)

        # HERZ_AUS_GOLD: find changes, authors and the changelog
        build_required=False

        print # make output a bit human readable..
        Logs.info("Looking for changes...")
        for repo in origin_commits:
            local = local_commits[repo]
            origin = origin_commits[repo]

            if local == origin:
                print "Unchanged:", origin.shortstring()
                continue

            # else:
            build_required=True
            print "Changed:  ", local.getCommitRange(origin, nice=True)

            with open(fn_changelog, "a") as f:
                f.write("######################################################################\n")
                f.write("# %66s #\n\n" % local.getCommitRange(origin, nice=True))

            # retrieve authors and remove redundant entries (multiple commits)
            os.chdir(os.path.join(curdir, repo))
            p = ProcessPipe('git', 'log', local.getCommitRange(origin))
            p.add( 'tee', '-a', fn_changelog )
            p.add( 'grep', '^Author:' )
            p.add( 'sort' )
            p.add( 'uniq' )
            p.add( 'sed', 's/^Author/To/' )
            p.add( 'tee', '-a', fn_authors ) # we append from each repo
            # print p # the pipe...
            p = p.execute() # returns the final process (Popen)

            #for line in p.stdout: print line,
            p.wait()

            # end changelog with a newline to separate it from the following one.
            with open(fn_changelog, "a") as f:
                f.write('\n')
        # done: for repo in origin_commits
        print # make output a bit human readable..


        # handle build/ no build
        if not build_required:
            assert( not os.path.isfile(fn_authors) )
            print "Mailman did not find any changes, no build required."
            return self.exitcode_doNotBuild

        # else: CHANGES HAVE BEEN FOUND

        # check for an empty authors file, which indicates that local commits were
        # found by the above routine -- in Jenkins environment this shouldn't happen
        if ( os.path.getsize(fn_authors) == 0 ):
            os.remove(fn_authors)
            os.remove(fn_changelog)
            Logs.error("""
            WARNING: local commits found!
            # The mailman build trigger is supposed to be used with unedited
            # checkouts only, i.e. for automatic build tools like Jenkins.
            # Triggering a //failure//-build!
            """)
            return self.exitcode_buildDueFailure

        # else: REAL CHANGES HAVE BEEN FOUND

        # cleanup (remove redundant authors (commiters to multiple repositories))
        os.chdir(self.jenkins_workspace.abspath())
        p = ProcessPipe('cat', fn_authors)
        p.add( 'sort' )
        p.add( 'uniq' )
        p.add( 'tee', fn_authors)
        p = p.execute()

        #Logs.info("The //potential// vandals:")
        #for line in p.stdout: print line,
        #print
        p.wait()


        ### give some status...
        print "The //potential// vandals:"

        ### filter authors that are not internal ones
        # specify regex patterns to be matched against the authors email addresses
        our_authors = [
            '^.*\.tu-dresden\.de$',
            '^.*@kip\.uni-heidelberg\.de$'
        ]

        exclude_anyway = [
            '^root@kip\.uni-heidelberg\.de$',
            '^postmaster@kip\.uni-heidelberg\.de$',
            '^none@kip\.uni-heidelberg\.de$',
            '.*\$.*'
        ]


        # to extract the mail addy from the "To: somebody <mail@provider.cc>"
        mailmatcher=re.compile('^To: .*<(?P<mail>.*)>$')

        # precompile the author-mailaddress patterns
        for idx, val in enumerate(our_authors):
            our_authors[idx] = re.compile(val)

        for idx, val in enumerate(exclude_anyway):
            exclude_anyway[idx] = re.compile(val)

        with open(fn_authors) as f:
            lines = f.readlines()


        with open(fn_authors, 'w') as f:
            for l in lines:
                mail = mailmatcher.match(l)
                if not mail:
                    print "WARNING: '{}' does not contain a <mail@provider.cc>".format(l)
                    continue
                #else
                mail = mail.group('mail')

                mail_known = False
                for r in our_authors:
                    if r.match(mail):
                        mail_known = not any([e.match(mail) for e in exclude_anyway])
                        break
                if mail_known:
                    print l,        # l contains a newline
                    f.write(l)      # override fn_authors
                else:
                    print "INFO: Mail filtered: {}".format(l)


        # say goodby
        assert( os.path.isfile(fn_authors) )    # must have been created at this point!
        assert( os.path.isfile(fn_changelog) )  # like above

        Logs.info("""
            Beware, the vandals responsible for this build are known.
            Pray that you did not introduce a regression!

            Now triggering a build!
            """
        )
        return self.exitcode_build



#####################
### Helper classes


### A CommitSpecifier instance holds a specific commit, ie.
# a repo name (workspace directory)
# a commit id (hash)
# and the title of that commit
class CommitSpecifier():
    def __init__(self, repo, commitId, commitText ):
        assert( repo.startswith('./') ) # WORKSPACE relative path TODO: test -d check?
        int(commitId, 16)               # must be a hexstring

        self.repo       = repo
        self.commitId   = commitId
        self.commitText = commitText

    def shortstring(self):
        return '<%s, %s>' % (self.repo, self.commitId[0:8])

    def getCommitRange(self, newer, nice=False):
        assert self.repo == newer.repo, 'Different repos: "%s" != "%s"' % (self.repo, newer.repo)

        if nice:
            return "<%s, %s..%s>" % (self.repo, self.commitId[0:8], newer.commitId[0:8])
        return '%s..%s' % (self.commitId, newer.commitId)

    def __str__(self):
        return 'Repo: %s\nId:   %s\nText: %s' % (self.repo, self.commitId, self.commitText)

    def __eq__(self, other):
        assert self.repo == other.repo, 'Different repos: "%s" != "%s"' % (self.repo, other.repo)

        if self.commitId == other.commitId:
            assert self.commitText == other.commitText
            return True
        return False


### ProcessPipe helps building and executing process pipes without shell-pipe usage
# useful to execute things like "git log | grep | sort | uniq", i.e process pipes...
# does not need shell access!
class ProcessPipe():
    def __init__(self, *comargs):
        self.commandStack = []
        self.initial = comargs

    def add(self, *comargs):
        self.commandStack.append(comargs)

    def execute(self):
        p = subprocess.Popen(self.initial, stdout=subprocess.PIPE, shell=False)
        for command in self.commandStack:
            p = subprocess.Popen( command, stdin=p.stdout, stdout=subprocess.PIPE, shell=False )
        return p

    def __str__(self):
        j =' '
        ret = j.join(self.initial)
        for command in self.commandStack:
            ret = ret + " | " + j.join(command)
        return ret


### function to parse "git log -n1 --pretty=oneline", retrieving the recent authors
def parseLog(command, toplevel):
    with open(os.devnull, 'w') as fp:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=fp)
    # mr title line has been removed (was available in the old flow)
    triple=[]   # 3 lines log output
    ret={}      # ret['<repo>'] = CommitSpecifier(...)
    #i = 0      # for debugging...
    for line in proc.stdout:
        #print i, line,
        #i+=1
        triple.append(line)
        if len(triple)==3:

            # triple[0]                 # mr run: </path/to/repository>\n
            s=triple[0].split()
            assert( len(s) == 3 )
            assert( s[0]+s[1] == 'mrrun:' ) # startswith "mr run:"
            assert( s[2].startswith(toplevel) )  # is an absolute path to somedir in symap2ic/below toplevel

            repo=s[2].replace(toplevel,".") # abspath to relpath (beutify)

            # triple[1]                 # <hexstring> <commit message with spaces>\n
            s=triple[1].partition(' ')
            int(s[0], 16)                   # throws if not a hex string
            assert( s[1] == ' ' )           # space found!

            commitId=s[0]
            commitText=s[2].strip()         # remove trailing newline

            # triple[2]                 # \n
            assert( triple[2] == "\n" )     # just a newline

            c = CommitSpecifier(repo, commitId, commitText)
            assert repo not in ret
            ret[repo] = c
            triple = []
    returncode = proc.wait()

    assert( returncode == 0 )
    assert( len(triple) == 1 )          # ~ "mr run: finished (N ok)"
    assert( triple[0].startswith("mr run: finished (") )    # failures not jet handled..
    final = triple[0]

    return ret
