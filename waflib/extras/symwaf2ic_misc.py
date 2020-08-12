import argparse, os
import re
try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse

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
# monkey-patch original OptionsContext to support add_withoption as well
Options.OptionsContext.add_withoption = _withoption


def _withargument(self, option, dest=None, default=None, help=None):
    """
    cf. _withoption (this argparse version needes for setup)
    """
    w_opt, wo_opt, dest = _withoption_helper(option, dest)
    self.add_argument(w_opt, wo_opt, action=WithOrWithoutAction, dest=dest, default=default, help=help)

# monkey-patch ArgumentParser to support add_withargument (translation in symwaf2ic's OptionParserContext)
argparse.ArgumentParser.add_withargument = _withargument


# --- Gerrit helper functions --- #
def parse_gerrit_changes(arg):
    # we convert integers and things that look like a changeset id to
    # explicit "change" queries
    check = re.compile(r'|'.join([
        r'^\d+$',         # numerical changeset number
        r'^I[0-9a-f]+$'   # changeset id
    ]))
    # numerical changeset number with custom patchset requirement:
    # <change-number>/<patchset-number>
    # -> patchset requirement has to stripped for gerrit-query
    check_custom_patchset = re.compile(r'^(\d+)/(\d+)$')

    ret = []
    for item in arg.split(','):
        if check.match(item):
            ret.append('change:{}'.format(item))
        else:
            match = check_custom_patchset.match(item)
            if match:
                ret.append('change:{}'.format(match(item).group(1)))
            else:
                ret.append(item)
    return ret


def validate_gerrit_url(arg):
    url = urlparse(arg)
    if url.scheme != 'ssh' or url.netloc == '':
        raise argparse.ArgumentTypeError(
            "Please enter a valid ssh URL")
    return arg


def add_username_to_gerrit_url(url, username):
    url = urlparse(url)

    # skip if no username was provided
    if not username:
        return url

    # we assume that the url is valid and was validated already
    netloc = url.netloc

    # if the url already contains a username, raise error
    if url.username is not None:
        raise argparse.ArgumentTypeError(
            "Please do provide only one username")

    netloc_with_username = "{username}@{netloc}".format(
        username=username, netloc=netloc)

    new_url = url._replace(netloc=netloc_with_username)
    assert new_url.username == username

    return new_url.geturl()
