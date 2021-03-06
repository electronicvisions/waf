"""
Asm-Cross compiler detection for the nux
"""
from waflib.extras import cross_as
from waflib import Options

def options(opt):
	opt.load('cross_as')
	opt.add_option('--cross-prefix', type='string',
			default='powerpc-ppu',
			help='compiler command prefix')

def configure(conf):
	conf.env.CROSS_PLATFORM = Options.options.cross_prefix
	conf.load('cross_as')
	conf.env.ASFLAGS += ['-mcpu=nux'] # we use gcc as assembler, compiler option here
