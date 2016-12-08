"""
C-Cross compiler detection for the nux
"""
from waflib.extras import cross_gcc, cross_as
from waflib import Options

def options(opt):
	opt.load('cross_gcc')
	opt.load('nux_assembler')

def configure(conf):
	conf.env.CROSS_PLATFORM = Options.options.cross_prefix
	conf.load('cross_gcc')
	conf.load('cross_as')
	conf.env.CFLAGS += [
		'-ffreestanding',
		'-mcpu=nux',
		'-std=gnu11',
	]
	conf.env.DEFINES += ['SYSTEM_HICANN_DLS_MINI']
	conf.env.LINKFLAGS += [
		'-T%s' % conf.path.find_node('libnux/elf32nux.x').abspath(),
	]
