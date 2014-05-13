import argparse, os
from waflib import Logs, Options

class WithOrWithoutAction(argparse.Action):
    __doc__ = 'Option callback (argparse) function that implements autotools-style --with-x/--without-x option behavior'

    def __init__(self,
                 option_strings,
                 dest,
                 nargs=None,
                 const=None,
                 default=None,
                 type=None,
                 choices=None,
                 required=False,
                 help=None,
                 metavar=None):
        super(WithOrWithoutAction, self).__init__(
            option_strings=option_strings,
            nargs=0,
            dest=dest,
            const=True,
            default=default,
            required=required,
            help=help)

    def __call__(self, parser, namespace, value, opt=None):
        dest, value = withOrOut_option(None, opt, value, None)
        self.dest = getattr(self, 'dest', dest) # use specified dest if available
        setattr(namespace, self.dest, value)


# compatibility with optparse-style arguments in waf => free functions
def withOrOut_option(option=None, opt=None, value=None, parser=None):
    if not any([option, opt, value, parser]):
        return WithOrWithoutAction

    """
    Option callback function that implements autotools-style --with-x/--without-x option behavior.

    @return tuple(dest, value) if in non-optparse-mode (i.e. 0 parameters), otherwise: nothing
    """

    if opt.startswith('--without-'):
        value = False
        autodest = 'with_' + opt[len('--without-'):]
    elif opt.startswith('--with-'):
        value = True
        autodest = 'with_' + opt[len('--with-'):]
    else:
        raise OptionValueError('Option %s not a --with/--without option' % str(option))

    if parser:
        # optparse-mode
        if not option.dest:
            option.dest = autodest
        setattr(parser.values, option.dest, value)
    else:
        return autodest, value


def _withoption_helper(option, dest=None):
    assert(not option.startswith('-'))
    w_opt = '--with-' + option
    wo_opt = '--without-' + option
    if not dest:
        dest= 'with_' + option
    # fix dest variable name
    dest = dest.replace('-', '_')
    return w_opt, wo_opt, dest


def _withoption(self, option, dest=None, default=None, help=None):
    """
    Encapsulate ugly --with-x --without-x add_option call into this function

    @param option  name (string) of option (without -)
    @param dest    see add_option
    @param default see add_option
    @param help    see add_option
    """
    w_opt, wo_opt, dest = _withoption_helper(option, dest)
    self.add_option(w_opt, wo_opt, action='callback', callback=withOrOut_option, dest=dest, default=default,
                    help=help)

# monkey-patch OptionContainer to support add_withoption
Options.optparse.OptionContainer.add_withoption = _withoption


def _withargument(self, option, dest=None, default=None, help=None):
    """
    cf. _withoption (this argparse version needes for setup)
    """
    w_opt, wo_opt, dest = _withoption_helper(option, dest)
    self.add_argument(w_opt, wo_opt, action=WithOrWithoutAction, dest=dest, default=default, help=help)

# monkey-patch ArgumentParser to support add_withargument (translation in symwaf2ic's OptionParserContext)
argparse.ArgumentParser.add_withargument = _withargument


from optparse import OptionParser, BadOptionError, AmbiguousOptionError
def _process_args(self, largs, rargs, values):
    """
    An unknown option pass-through implementation of _process_args.
    """
    while rargs:
        try:
            OptionParser._old_process_args(self, largs, rargs, values)
        except (BadOptionError, AmbiguousOptionError), e:
            largs.append(e.opt_str)

# monkey patch optparse to support unkown arguments (partial argument list while constructing the list => depends() needs it)
Options.optparse.OptionParser._old_process_args = Options.optparse.OptionParser._process_args
Options.optparse.OptionParser._process_args = _process_args


from waflib.Configure import conf
@conf
def fix_boost_paths(self):
    if not getattr(self, 'orig_check_boost', None) is None:
        return # already set

    self.orig_check_boost = self.check_boost # raise if boost tool isn't loaded
    incs = os.environ.get('BOOSTINC', None)
    libs = os.environ.get('BOOSTLIB', None)

    def my_check_boost(*k, **kw):
        if not kw.has_key('includes') and incs:
            kw['includes'] = incs
        if not kw.has_key('libs') and libs:
            kw['libs'] = libs
        self.orig_check_boost(*k, **kw)
    self.check_boost = my_check_boost
