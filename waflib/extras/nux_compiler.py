"""
C-Cross compiler detection for the nux
"""
from waflib.extras import cross_gcc, cross_as
from waflib import Options

def options(opt):
	opt.load('cross_gcc')
	opt.load('cross_gxx')
	opt.load('nux_assembler')

def configure(conf):
	conf.env.CROSS_PLATFORM = Options.options.cross_prefix
	conf.load('cross_gcc')
	conf.load('cross_gxx')
	conf.load('cross_as')
	conf.env.RPATH_ST = ""
	conf.env.CFLAGS += [
		'-ffreestanding',
		'-mcpu=nux',
		'-std=gnu11',
		#'-fstack-protector-strong', # requires handler
		'-fno-common',
		'-ffunction-sections',
		'-fdata-sections',
	]
	conf.env.CXXFLAGS += [
		'-ffreestanding',
		'-mcpu=nux',
		'-fno-exceptions',
		'-fno-rtti',
		'-fno-non-call-exceptions',
		#'-fstack-protector-strong', # requires handler
		'-fno-common',
		'-ffunction-sections',
		'-fdata-sections',
	]
	conf.env.DEFINES += ['SYSTEM_HICANN_DLS_MINI']
	conf.env.LINKFLAGS += [
		'-nostdlib',
		'-Wl,--gc-sections',
	]
	conf.env.STLIB += ['gcc']
