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

def perr(msg):
	return
	sys.stderr.write('----- ' + msg)
	sys.stderr.write('\n')
	sys.stderr.flush()

# quit if the parent process ends abruptly
ppid = int(sys.stdin.readline())
def reap():
	if os.sep != '/':
		os.waitpid(ppid, 0)
	else:
		while 1:
			try:
				os.kill(ppid, 0)
			except OSError:
				break
			else:
				time.sleep(1)
	os.kill(os.getpid(), signal.SIGKILL)
t = threading.Thread(target=reap)
t.setDaemon(True)
t.start()

while 1:
	txt = sys.stdin.readline()
	if not txt:
		# end
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

