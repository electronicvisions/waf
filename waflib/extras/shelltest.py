"""
Executes (shell) scripts and reports successful/failed unit tests based on their
exit code.

Note: All tested scripts need to feature a valid shebang for determination of
      the correct interpreter!

Usage example:

    def options(ctx):
        ctx.load('shelltest')


    def configure(ctx):
        ctx.load('shelltest')


    def build(ctx):
        ctx(
            features='shelltest',
            name='my_pretty_tests',
            source=ctx.path.ant_glob('tests/*.sh')
        )
"""
from os.path import basename
from waflib.TaskGen import feature, after_method, extension
from waflib.Tools import ccroot
from waflib.extras import test_base


class shelltest(test_base.TestBase):
    """
    Task for running (shell) scripts as unit tests.
    """

    def run(self):
        for script in self.inputs:
            script_path = script.abspath()
            script_name = basename(script_path)

            test_output = self.xmlDir.find_or_declare(str(self.generator.name)
                                                      + "_"
                                                      + script_name)

            # Run tests using perl
            # This is a hack for executing non-executable scripts with the
            # interpreter specified in their shebang.
            # Perl parses the shebang for us and does the right thing, quoting
            # its documentation:
            #   If the #! line does not contain the word "perl" nor the word
            #   "indir", the program named after the #! is executed instead
            #   of the Perl interpreter. This is slightly bizarre, but it
            #   helps people on machines that don't do #! , because they can
            #   tell a program that their SHELL is /usr/bin/perl, and Perl
            #   will then dispatch the program to the correct interpreter for
            #   them.
            self.runTest(test_output, [self.env.PERL[0], script_path])


# Needed for population of task_gen.tmp_use_seen, as expected by test_base
@feature("shelltest")
@after_method("process_use")
def shelltest_process_use(self):
    if not hasattr(self, "uselib"):
        ccroot.process_use(self)


@feature("shelltest")
@after_method("shelltest_process_use")
def shelltest_create_task(self):
    if not len(self.name):
        self.bld.fatal('%s: "name" parameter is mandatory' % self.source)

    input_nodes = self.to_nodes(self.source)
    if hasattr(self, "tests"):
        input_nodes += self.to_nodes(self.tests)

    if not len(input_nodes):
        self.bld.fatal('%s: No inputs found. Specify "tests" or "source".' %
                       self.name)

    if self.testsDisabled():
        return

    if not self.isTestExecutionEnabled():
        return

    self.shelltest_task = t = self.create_task('shelltest', input_nodes)
    t.init(self)


def options(opt):
    test_base.options(opt)


def configure(ctx):
    test_base.configure(ctx)
    ctx.find_program('perl', mandatory=True)


@extension('.sh')
def process_shell(self, node):
    pass
