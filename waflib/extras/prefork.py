#! /usr/bin/env python
# encoding: utf-8
# Thomas Nagy, 2015 (ita)

"""
Execute commands through pre-forked servers. This tool creates as many servers as build threads.
On a benchmark executed on Linux Kubuntu 14, 8 virtual cores and SSD drive::

    ./genbench.py /tmp/build 200 100 15 5
    waf clean build -j24
    # no prefork: 2m7.179s
    # prefork:    0m55.400s

To use::

    def build(bld):
        bld.load('serverprocess_client')
        ...
        more code
"""

import os, re, tempfile, socket, threading, shutil, sys, subprocess, time, atexit
try:
	import SocketServer
except ImportError:
	import socketserver as SocketServer
try:
	from queue import Queue
except ImportError:
	from Queue import Queue
try:
	import cPickle
except ImportError:
	import pickle as cPickle

DEFAULT_PORT = 51200

HEADER_SIZE = 128

REQ = 'REQ'
RES = 'RES'
BYE = 'BYE'

def make_header(params):
	header = ','.join(params)
	if sys.hexversion > 0x3000000:
		header = header.encode('iso8859-1')
	header = header.ljust(HEADER_SIZE)
	assert(len(header) == HEADER_SIZE)
	return header


re_valid_query = re.compile('^[a-zA-Z0-9_, ]+$')
class req(SocketServer.StreamRequestHandler):
	def handle(self):
		while 1:
			try:
				self.process_command()
			except Exception as e:
				print(e)
				break

	def process_command(self):
		query = self.rfile.read(HEADER_SIZE)
		if not query:
			return
		#print(len(query))
		assert(len(query) == HEADER_SIZE)
		if sys.hexversion > 0x3000000:
			query = query.decode('iso8859-1')
		#print "%r" % query
		if not re_valid_query.match(query):
			raise ValueError('Invalid query %r' % query)

		query = query.strip().split(',')

		if query[0] == REQ:
			self.run_command(query[1:])
		elif query[0] == BYE:
			raise ValueError('Exit')
		else:
			raise ValueError('Invalid query %r' % query)

	def run_command(self, query):

		size = int(query[0])
		data = self.rfile.read(size)
		assert(len(data) == size)
		kw = cPickle.loads(data)

		# run command
		ret = out = err = exc = None
		cmd = kw['cmd']
		del kw['cmd']
		#print(cmd)

		try:
			if kw['stdout'] or kw['stderr']:
				p = subprocess.Popen(cmd, **kw)
				(out, err) = p.communicate()
				ret = p.returncode
			else:
				ret = subprocess.Popen(cmd, **kw).wait()
		except Exception as e:
			ret = -1
			exc = str(e)

		# write the results
		if out or err or exc:
			data = (out, err, exc)
			data = cPickle.dumps(data, -1)
		else:
			data = ''

		params = [RES, str(ret), str(len(data))]

		self.wfile.write(make_header(params))

		if data:
			self.wfile.write(data)

def create_server(conn, cls):
	#SocketServer.ThreadingTCPServer.allow_reuse_address = True
	#server = SocketServer.ThreadingTCPServer(conn, req)

	SocketServer.TCPServer.allow_reuse_address = True
	server = SocketServer.TCPServer(conn, req)
	#server.timeout = 6000 # seconds
	server.serve_forever(poll_interval=0.001)

if __name__ == '__main__':
	if len(sys.argv) > 1:
		port = int(sys.argv[1])
	else:
		port = DEFAULT_PORT
	#conn = (socket.gethostname(), port)
	conn = ("127.0.0.1", port)
	#print("listening - %r %r\n" % conn)
	create_server(conn, req)
else:

	from waflib import Task, Logs, Utils, Build, Options, Runner, Errors

	SERVERS = []

	def init_task_pool(self):
		# lazy creation, and set a common pool for all task consumers
		pool = self.pool = []
		for i in range(self.numjobs):
			consumer = Runner.get_pool()
			pool.append(consumer)
			consumer.idx = i
		self.ready = Queue(0)
		def setq(consumer):
			consumer.ready = self.ready
			try:
				threading.current_thread().idx = consumer.idx
			except Exception as e:
				print(e)
		for x in pool:
			x.ready.put(setq)
		return pool
	Runner.Parallel.init_task_pool = init_task_pool

	PORT = 51200

	def make_server(bld, idx):
		port = PORT + idx
		cmd = [sys.executable, os.path.abspath(__file__), str(port)]
		proc = subprocess.Popen(cmd)
		proc.port = port
		return proc

	def make_conn(bld, srv):
		#port = PORT + idx
		port = srv.port
		conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		conn.connect(('127.0.0.1', port))
		return conn


	SERVERS = []
	CONNS = []
	def close_all():
		while CONNS:
			conn = CONNS.pop()
			try:
				conn.close()
			except:
				pass
		while SERVERS:
			srv = SERVERS.pop()
			try:
				srv.kill()
			except:
				pass
	atexit.register(close_all)

	def put_data(conn, data):
		conn.send(data)

	def read_data(conn, siz):
		ret = conn.recv(siz)
		if not ret:
			print("closed connection?")

		assert(len(ret) == siz)
		return ret

	def exec_command(self, cmd, **kw):

		kw['shell'] = isinstance(cmd, str)
		Logs.debug('runner: %r' % cmd)
		Logs.debug('runner_env: kw=%s' % kw)

		if self.logger:
			self.logger.info(cmd)

		if 'stdout' not in kw:
			kw['stdout'] = subprocess.PIPE
		if 'stderr' not in kw:
			kw['stderr'] = subprocess.PIPE

		if Logs.verbose and not kw['shell'] and not Utils.check_exe(cmd[0]):
			raise Errors.WafError("Program %s not found!" % cmd[0])

		idx = threading.current_thread().idx
		kw['cmd'] = cmd

		# serialization..
		#print("sub %r %r" % (idx, cmd))
		#print("write to %r %r" % (idx, cmd))

		data = cPickle.dumps(kw, -1)
		params = [REQ, str(len(data))]
		header = make_header(params)

		conn = CONNS[idx]

		put_data(conn, header)
		put_data(conn, data)

		#print("running %r %r" % (idx, cmd))
		#print("read from %r %r" % (idx, cmd))

		data = read_data(conn, HEADER_SIZE)
		if sys.hexversion > 0x3000000:
			data = data.decode('iso8859-1')

		#print("received %r" % data)
		lst = data.split(',')
		ret = int(lst[1])
		dlen = int(lst[2])

		out = err = None
		if dlen:
			data = read_data(conn, dlen)
			(out, err, exc) = cPickle.loads(data)
			if exc:
				raise Errors.WafError('Execution failure: %s' % exc)

		if out:
			if not isinstance(out, str):
				out = out.decode(sys.stdout.encoding or 'iso8859-1')
			if self.logger:
				self.logger.debug('out: %s' % out)
			else:
				Logs.info(out, extra={'stream':sys.stdout, 'c1': ''})
		if err:
			if not isinstance(err, str):
				err = err.decode(sys.stdout.encoding or 'iso8859-1')
			if self.logger:
				self.logger.error('err: %s' % err)
			else:
				Logs.info(err, extra={'stream':sys.stderr, 'c1': ''})

		return ret


	def build(bld):
		if bld.cmd == 'clean':
			return

		while len(SERVERS) < bld.jobs:
			i = len(SERVERS)
			srv = make_server(bld, i)
			SERVERS.append(srv)
		while len(CONNS) < bld.jobs:
			i = len(CONNS)
			srv = SERVERS[i]
			conn = None
			for x in range(30):
				try:
					conn = make_conn(bld, srv)
					break
				except socket.error:
					time.sleep(0.01)
			if not conn:
				raise ValueError('Could not start the server!')
			CONNS.append(conn)
		bld.__class__.exec_command = exec_command

