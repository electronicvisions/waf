"""
Provides python code style (PEP8) checking support using pycodestyle.

Results will be written to test_xml_output_folder/pycodestyle_$name.pycodestyle

Usage example:

    def options(ctx):
        ctx.load('pycodestyle')


    def configure(ctx):
        ctx.load('pycodestyle')


    def build(ctx):
        ctx(
            features='py pycodestyle',
            name='my_pretty_module',
            source=ctx.path.ant_glob('python_module/**'),
            pycodestyle_config="pycodestyle_config"    # optional
        )
"""
from waflib import Node
from waflib.TaskGen import feature, after_method
from waflib.Tools import ccroot
from waflib.extras import test_base
from waflib.extras.symwaf2ic import get_toplevel_path


class pycodestyle(test_base.TestBase):
    """
    Task for checking python files with pycodestyle.
    """

    def __init__(self, *args, **kwargs):
        super(pycodestyle, self).__init__(*args, **kwargs)
        self.config_file = None

    def set_pycodestyle_config(self):
        """
        Set `self.config_file` to the (optional) pycodestyle config from the
        task's generator. Make it a node if it is none.

        Add the config to the task's dependencies (if applicable).
        """
        config = getattr(self.generator, "pycodestyle_config", None)
        if config is None:
            return

        if not isinstance(config, Node.Node):
            config = self.generator.bld.root.find_node(config)

        if config is None:
            self.generator.bld.fatal("pycodestyle config %s not found!" %
                                     self.generator.pycodestyle_config)

        self.dep_nodes.append(config)
        self.config_file = config

    def run(self):
        out = self.xmlDir.find_or_declare("pycodestyle_" + self.generator.name)

        pycodestyle_cmd = [self.env.PYCODESTYLE[0]]
        if self.config_file is not None:
            pycodestyle_cmd.append("--config=%s" % self.config_file.abspath())
        pycodestyle_cmd += [f.abspath() for f in self.inputs]
        pycodestyle_cmd.append("> %s" % out.change_ext(".pycodestyle").abspath())

        # Run pycodestyle relative to toplevel for correct paths in the result
        self.runTest(out, pycodestyle_cmd, cwd=get_toplevel_path())


# Needed for population of task_gen.tmp_use_seen, as expected by test_base
@feature("pycodestyle")
@after_method("process_use")
def pycodestyle_process_use(self):
    if not hasattr(self, "uselib"):
        ccroot.process_use(self)


@feature("pycodestyle")
@after_method("pycodestyle_process_use")
def pycodestyle_create_task(self):
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

    self.pycodestyle_task = t = self.create_task('pycodestyle', input_nodes)
    t.init(self)
    t.set_pycodestyle_config()


def options(opt):
    opt.load('python')
    test_base.options(opt)


def configure(ctx):
    ctx.load('python')
    ctx.check_python_version()
    test_base.configure(ctx)
    ctx.find_program('pycodestyle', mandatory=True)
