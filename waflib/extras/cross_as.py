#!/usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2008-2010 (ita)

"Detect cross assembler for compiling assembly files"

import waflib.Tools.asm # - leave this
from waflib.extras import cross_ar

def configure(conf):
	"""
	Find the cross assembler and set the variable *AS*
	"""
	conf.find_program('%s-gcc' % conf.env.CROSS_PLATFORM, var='AS')
	conf.find_program('%s-ld' % conf.env.CROSS_PLATFORM, var='ASLINK')
	conf.env.AS_TGT_F = ['-c', '-o']
	conf.env.ASLNK_TGT_F = ['-o']
	conf.find_cross_ar()
	conf.load('asm')
