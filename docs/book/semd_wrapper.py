#! /usr/bin/env python
# encoding: utf-8
#
# SEMANTIK_D="/home/user/waf/docs/book/semd_wrapper.py --gen" waf configure

import sys, os, shutil, subprocess

realgen = ''
width = ''
lst = sys.argv[1:]
while lst:
	arg = lst.pop(0)
	if arg.startswith('--width'):
		width = arg
	elif arg == '--gen':
		realgen = True
	elif arg.startswith('-o'):
		outfile = lst.pop(0)
	else:
		infile = arg

obase, of = os.path.split(outfile)
base, f = os.path.split(infile)
intermediate = os.path.join(base, 'semd_cache', width.replace('--', '').replace('=', '') + '_' + of)

if realgen:
	cmd = ['semantik-d'] + sys.argv[1:]
	cmd.remove('--gen')
	ret = subprocess.Popen(cmd).wait()
	if ret:
		sys.exit(ret)
	shutil.copy(outfile, intermediate)
else:
	shutil.copy(intermediate, outfile)

