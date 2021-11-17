"""
Provides python linting support using pylint.

Results will be written to test_xml_output_folder/pylint_$name.pylint

Usage example:

    def options(ctx):
        ctx.load('python')
        ctx.load('pylint')


    def configure(ctx):
        ctx.load('python')
        ctx.check_python_version()
        ctx.load('pylint')


    def build(ctx):
        ctx(
            features='py pylint',
            name='my_pretty_module',
            source=ctx.path.ant_glob('python_module/**'),
            pylint_config="pylintrc"    # optional
        )

        ctx(
            features='py pylint',
            name='my_pretty_scripts',
            source='python_module/a.py python_module/b.py',
            pylint_config="pylintrc"    # optional
        )
"""
from os.path import splitext, basename, dirname
from waflib import Node
from waflib.TaskGen import feature, after_method, before_method
from waflib.Tools import ccroot
from waflib.extras import test_base
from waflib.extras.symwaf2ic import get_toplevel_path


class pylint(test_base.TestBase):
    """
    Task for linting python scripts and modules using pylint.
    """

    def __init__(self, *args, **kwargs):
        super(pylint, self).__init__(*args, **kwargs)
        self.rcfile = None

    def set_pylint_config(self):
        """
        Set `self.rcfile` to the (optional) pylint config from the task's
        generator. Make it a node if it is none.

        Add the config to the task's dependencies (if applicable).
        """
        pylint_config = getattr(self.generator, "pylint_config", None)
        if pylint_config is None:
            return

        if not isinstance(pylint_config, Node.Node):
            pylint_config = self.generator.bld.root.find_node(pylint_config)

        if pylint_config is None:
            self.generator.bld.fatal("Pylint config %s not found!" %
                                     self.generator.pylint_config)

        self.dep_nodes.append(pylint_config)
        self.rcfile = pylint_config

    def _get_pylint_target(self):
        """
        Find the target pylint is supposed to check. This can either be
        python-module (if __init__.* files are found) or  list of python
        scripts.

        If a module is checked, no sources above the module-toplevel are
        allowed.

        :return: List of options to be appended to the pylint command
        :rtype: list of str
        """
        init_files = [f for f in self.inputs
                      if splitext(basename(f.abspath()))[0] == "__init__"]

        if len(init_files):  # There is an __init__.* in the inputs => module!
            top_init = min(init_files, key=lambda x: x.height())

            if any([src.height() < top_init.height() for src in self.inputs]):
                self.generator.bld.fatal("%s: Sources above the top-level "
                                         "__init__ file found. Nested module"
                                         "handling is not implemented." %
                                         self.generator.name)

            # Pylint should try to import the actual module by path
            return [dirname(top_init.abspath())]
        else:  # No init file => not a python module
            return [f.abspath() for f in self.inputs]

    def run(self):
        output = self.xmlDir.find_or_declare("pylint_" + self.generator.name)

        pylint_cmd = [self.env.PYLINT[0]]
        pylint_cmd.append("-j%d" % self.env.PYLINT_NUM_JOBS)
        if self.rcfile is not None:
            pylint_cmd.append("--rcfile=%s" % self.rcfile.abspath())
        pylint_cmd += self._get_pylint_target()
        pylint_cmd.append("> %s" % output.change_ext(".pylint").abspath())

        # Run pylint relative to toplevel for correct paths in the result file
        self.runTest(output, pylint_cmd, cwd=get_toplevel_path())


@feature('pyext')
@after_method('apply_link')
@before_method('process_use')
def add_pyext_pylint(self):
    # store link_task if there is one
    try:
        self.pyext_task = self.link_task
    except AttributeError:
        pass


@feature("pylint")
@after_method("process_use")
def pylint_process_use(self):
    if not hasattr(self, "uselib"):
        ccroot.process_use(self)


@feature("pylint")
@after_method("pylint_process_use")
def pylint_create_task(self):
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

    self.pylint_task = t = self.create_task('pylint', input_nodes)
    t.init(self)
    t.set_pylint_config()
    for use in self.tmp_use_seen:
        tg = self.bld.get_tgen_by_name(use)
        if hasattr(tg, "pyext_task"):
            t.dep_nodes.extend(tg.pyext_task.outputs)


def options(opt):
    opt.load('python')
    test_base.options(opt)

    opt.add_option("--pylint-num-jobs",
                   dest="pylint_num_jobs",
                   default=1,
                   type="int",
                   action="store",
                   help="Number of parallel jobs (-j) to use for pylint "
                        "(default=1, use '0' to auto-detect the number "
                        "of cores available)")


def configure(ctx):
    test_base.configure(ctx)
    ctx.load('python')
    ctx.check_python_version()
    ctx.find_program('pylint', mandatory=True)
    ctx.env.PYLINT_NUM_JOBS = ctx.options.pylint_num_jobs
