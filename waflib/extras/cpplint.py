#! /usr/bin/env python
# encoding: utf-8
#
# written by Sylvain Rouquette, 2014

'''

This is an extra tool, not bundled with the default waf binary.
To add the cpplint tool to the waf file:
$ ./waf-light --tools=compat15,cpplint
    or, if you have waf >= 1.6.2
$ ./waf update --files=cpplint

this tool also requires cpplint for python.
If you have PIP, you can install it like this: pip install cpplint

But I'd recommend getting the latest version from the SVN,
the PIP version is outdated.
https://code.google.com/p/google-styleguide/source/browse/trunk/cpplint/cpplint.py
Apply this patch if you want to run it with Python 3:
https://code.google.com/p/google-styleguide/issues/detail?id=19


When using this tool, the wscript will look like:

    def options(opt):
        opt.load('compiler_cxx cpplint')

    def configure(conf):
        conf.load('compiler_cxx cpplint')
        # optional, you can also specify them on the command line
        conf.env.CPPLINT_FILTERS = ','.join((
            '-whitespace/newline',      # c++11 lambda
            '-readability/braces',      # c++11 constructor
            '-whitespace/braces',       # c++11 constructor
            '-build/storage_class',     # c++11 for-range
            '-whitespace/blank_line',   # user pref
            '-whitespace/labels'        # user pref
            ))

    def build(bld):
        bld(features='cpplint', source='main.cpp', target='app')
        # add include files, because they aren't usually built
        bld(features='cpplint', source=bld.path.ant_glob('**/*.hpp'))
'''

import sys, re
import logging
import threading
from waflib import Task, Build, TaskGen, Logs, Utils
try:
    from cpplint.cpplint import ProcessFile, _cpplint_state
except ImportError:
    pass


CPPLINT_FORMAT = '[CPPLINT] %(filename)s:\nline %(linenum)s, severity %(confidence)s, category: %(category)s\n%(message)s\n'
CPPLINT_RE = re.compile('(?P<filename>.*):(?P<linenum>\d+):  (?P<message>.*)  \[(?P<category>.*)\] \[(?P<confidence>\d+)\]')
critical_errors = 0


def init_env_from_options(env):
    from waflib.Options import options
    if not env.CPPLINT_FILTERS:
        env.CPPLINT_FILTERS = options.CPPLINT_FILTERS
    if not env.CPPLINT_LEVEL:
        env.CPPLINT_LEVEL  = options.CPPLINT_LEVEL
    if not env.CPPLINT_BREAK:
        env.CPPLINT_BREAK  = options.CPPLINT_BREAK
    if not env.CPPLINT_SKIP:
        env.CPPLINT_SKIP   = options.CPPLINT_SKIP


def options(opt):
    opt.add_option('--cpplint-filters', type='string',
                   default='', dest='CPPLINT_FILTERS',
                   help='add filters to cpplint')
    opt.add_option('--cpplint-level', default=1, type='int', dest='CPPLINT_LEVEL',
                   help='specify the log level (default: 1)')
    opt.add_option('--cpplint-break', default=5, type='int', dest='CPPLINT_BREAK',
                   help='break the build if error >= level (default: 5)')
    opt.add_option('--cpplint-skip', action='store_true',
                   default=False, dest='CPPLINT_SKIP',
                   help='skip cpplint during build')


def configure(conf):
    conf.start_msg('Checking cpplint')
    try:
        import cpplint
    except ImportError:
        conf.fatal('cpplint not found. try "pip install cpplint".')
    conf.end_msg('ok')


class cpplint_formatter(Logs.formatter):
    def __init__(self):
        logging.Formatter.__init__(self, CPPLINT_FORMAT)

    def format(self, rec):
        result = CPPLINT_RE.match(rec.msg).groupdict()
        rec.msg = CPPLINT_FORMAT % result
        if rec.levelno <= logging.INFO:
            rec.c1 = Logs.colors.CYAN
        return super(cpplint_formatter, self).format(rec)


class cpplint_handler(Logs.log_handler):
    def __init__(self, stream=sys.stderr, **kw):
        super(cpplint_handler, self).__init__(stream, **kw)
        self.stream = stream

    def emit(self, rec):
        rec.stream = self.stream
        self.emit_override(rec)
        self.flush()


class cpplint_wrapper(object):
    stream = None
    tasks_count = 0
    lock = threading.RLock()

    def __init__(self, logger, threshold):
        self.logger = logger
        self.threshold = threshold
        self.error_count = 0

    def __enter__(self):
        with cpplint_wrapper.lock:
            cpplint_wrapper.tasks_count += 1
            if cpplint_wrapper.tasks_count == 1:
                sys.stderr.flush()
                cpplint_wrapper.stream = sys.stderr
                sys.stderr = self
            return self

    def __exit__(self, exc_type, exc_value, traceback):
        with cpplint_wrapper.lock:
            cpplint_wrapper.tasks_count -= 1
            if cpplint_wrapper.tasks_count == 0:
                sys.stderr = cpplint_wrapper.stream
                sys.stderr.flush()

    def write(self, message):
        global critical_errors
        result = CPPLINT_RE.match(message)
        if not result:
            return
        level = int(result.groupdict()['confidence'])
        if level >= self.threshold:
            critical_errors += 1
        if level <= 2:
            self.logger.info(message)
        elif level <= 4:
            self.logger.warning(message)
        else:
            self.logger.error(message)


cpplint_logger = None
def get_cpplint_logger():
    global cpplint_logger
    if cpplint_logger:
        return cpplint_logger
    cpplint_logger = logging.getLogger('cpplint')
    hdlr = cpplint_handler()
    hdlr.setFormatter(cpplint_formatter())
    cpplint_logger.addHandler(hdlr)
    cpplint_logger.setLevel(logging.DEBUG)
    return cpplint_logger


class cpplint(Task.Task):
    color = 'PINK'

    def __init__(self, *k, **kw):
        super(cpplint, self).__init__(*k, **kw)

    def run(self):
        global critical_errors
        _cpplint_state.SetFilters(self.env.CPPLINT_FILTERS)
        break_level = self.env.CPPLINT_BREAK
        verbosity = self.env.CPPLINT_LEVEL
        with cpplint_wrapper(get_cpplint_logger(), break_level):
            ProcessFile(self.inputs[0].abspath(), verbosity)
        return critical_errors


@TaskGen.extension('.h', '.hh', '.hpp', '.hxx')
def cpplint_includes(self, node):
    pass

@TaskGen.feature('cpplint')
@TaskGen.before_method('process_source')
def run_cpplint(self):
    if not self.env.CPPLINT_INITIALIZED:
        self.env.CPPLINT_INITIALIZED = True
        init_env_from_options(self.env)
    if self.env.CPPLINT_SKIP:
        return
    for src in self.to_list(getattr(self, 'source', [])):
        if isinstance(src, str):
            self.create_task('cpplint', self.path.find_or_declare(src))
        else:
            self.create_task('cpplint', src)
