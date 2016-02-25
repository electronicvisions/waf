#! /usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2015 (ita)

"""
"""

import os, threading, sys, signal, time, traceback
try:
	import cPickle
except ImportError:
	import pickle as cPickle

try:
	import subprocess32 as subprocess
except ImportError:
	import subprocess

while 1:
	txt = sys.stdin.readline()
	if not txt:
		# parent process probably ended
		break

	buflen = int(txt.strip())
	obj = sys.stdin.read(buflen)
	[cmd, kwargs, cargs] = cPickle.loads(obj.encode())
	cargs = cargs or {}

	ret = 1
	out, err = (None, None)
	ex = None
	try:
		proc = subprocess.Popen(cmd, **kwargs)
		out, err = proc.communicate(**cargs)
		ret = proc.returncode
	except OSError as e:
		# TODO
		exc_type, exc_value, tb = sys.exc_info()
		exc_lines = traceback.format_exception(exc_type, exc_value, tb)
		ex = str(cmd) + '\n' + ''.join(exc_lines)
	except ValueError as e:
		# TODO
		ex = str(e)

	# it is just text so maybe we do not need to pickle()
	tmp = [ret, out, err, ex]
	obj = cPickle.dumps(tmp, 0)

	header = "%d\n" % len(obj)
	sys.stdout.write(header)
	sys.stdout.write(obj.decode(sys.stdout.encoding or 'iso8859-1'))
	sys.stdout.flush()

