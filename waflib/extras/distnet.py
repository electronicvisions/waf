#! /usr/bin/env python
# encoding: utf-8

"""
waf-powered distributed network builds, with a network cache.

Caching files from a server has advantages over a NFS/Samba shared folder:

- builds are much faster because they use local files
- builds just continue to work in case of a network glitch
- permissions are much simpler to manage

TODO: python3 compatibility

"""

import os, urllib, urllib2, tarfile, collections, re, shutil, tempfile
from waflib import Context, Configure, Utils, Logs

DISTNETCACHE = os.environ.get('DISTNETCACHE', '/tmp/distnetcache')
DISTNETSERVER = os.environ.get('DISTNETSERVER', 'http://localhost:8000/cgi-bin/')
TARFORMAT = 'w:bz2'
TIMEOUT=60

re_com = re.compile('\s*#.*', re.M)

def get_distnet_cache():
	return getattr(Context.g_module, 'DISTNETCACHE', DISTNETCACHE)

def get_server_url():
	return getattr(Context.g_module, 'DISTNETSERVER', DISTNETSERVER)

def get_download_url():
	return '%s/download.py' % get_server_url()

def get_upload_url():
	return '%s/upload.py' % get_server_url()

def get_resolve_url():
	return '%s/resolve.py' % get_server_url()

def send_package_name():
	out = getattr(Context.g_module, 'out', 'build')
	pkgfile = '%s/package_to_upload.tarfile' % out
	return pkgfile

class package(Context.Context):
	fun = 'package'
	cmd = 'package'

	def execute(self):
		try:
			files = self.files
		except AttributeError:
			files = self.files = []

		Context.Context.execute(self)
		pkgfile = send_package_name()
		if not pkgfile in self.files:
			if not 'requires.txt' in self.files:
				self.files.append('requires.txt')
			self.make_tarfile(pkgfile, self.files, add_to_package=False)

	def make_tarfile(self, filename, files, **kw):
		if kw.get('add_to_package', True):
			self.files.append(filename)

		with tarfile.open(filename, TARFORMAT) as tar:
			endname = os.path.split(filename)[-1]
			endname = endname.split('.')[0] + '/'
			for x in files:
				tarinfo = tar.gettarinfo(x, x)
				tarinfo.uid   = tarinfo.gid   = 0
				tarinfo.uname = tarinfo.gname = 'root'
				tarinfo.size = os.stat(x).st_size

				# TODO - more archive creation options?
				if kw.get('bare', True):
					tarinfo.name = os.path.split(x)[1]
				else:
					tarinfo.name = endname + x # todo, if tuple, then..
				Logs.debug("adding %r to %s" % (tarinfo.name, filename))
				with open(x, 'rb') as f:
					tar.addfile(tarinfo, f)
		Logs.info('Created %s' % filename)

class publish(Context.Context):
	fun = 'publish'
	cmd = 'publish'
	def execute(self):
		if hasattr(Context.g_module, 'publish'):
			Context.Context.execute(self)
		mod = Context.g_module

		rfile = getattr(self, 'rfile', send_package_name())
		if not os.path.isfile(rfile):
			self.fatal('Create the release file with "waf release" first! %r' % rfile)

		fdata = Utils.readf(rfile, m='rb')
		data = urllib.urlencode([('pkgdata', fdata), ('pkgname', mod.APPNAME), ('pkgver', mod.VERSION)])

		req = urllib2.Request(get_upload_url(), data)
		response = urllib2.urlopen(req, timeout=TIMEOUT)
		data = response.read().strip()

		if data != 'ok':
			self.fatal('Could not publish the package %r' % data)


class pkg(object):
	pass
	# name              foo
	# version           1.0.0
	# required_version  1.0.*
	# localfolder       /tmp/packages/foo/1.0/

class package_reader(object):
	def read_packages(self, filename='requires.txt'):
		txt = Utils.readf(filename).strip()
		self.compute_dependencies(filename)

	def read_package_string(self, txt):
		if txt is None:
			Logs.error('Hahaha, None!')
		self.pkg_list = []
		txt = re.sub(re_com, '', txt)
		lines = txt.splitlines()
		for line in lines:
			if not line:
				continue
			p = pkg()
			p.required_line = line
			lst = line.split(',')
			p.name = lst[0]
			p.requested_version = lst[1]
			self.pkg_list.append(p)
			for k in lst:
				a, b, c = k.partition('=')
				if a and c:
					setattr(p, a, c)

	def compute_dependencies(self, filename='requires.txt'):
		text = Utils.readf(filename)
		data = urllib.urlencode([('text', text)])
		req = urllib2.Request(get_resolve_url(), data)
		try:
			response = urllib2.urlopen(req, timeout=TIMEOUT)
		except urllib2.URLError as e:
			Logs.warn('The package server is down! %r' % e)
			self.local_resolve(text)
		else:
			ret = response.read()
			print ret
			self.read_package_string(ret)

		errors = False
		for p in self.pkg_list:
			if getattr(p, 'error', ''):
				Logs.error(p.error)
				errors = True
		if errors:
			raise ValueError('Requirements could not be satisfied!')

	def get_results(self):
		buf = []
		for x in self.pkg_list:
			buf.append('%s,%s' % (x.name, x.requested_version))
			for y in ('error', 'version'):
				if hasattr(x, y):
					buf.append(',%s=%s' % (y, getattr(x, y)))
			buf.append('\n')
		return ''.join(buf)

	def local_resolve(self, text):
		self.read_package_string(text)
		for p in self.pkg_list:

			pkgdir = os.path.join(get_distnet_cache(), p.name)
			try:
				versions = os.listdir(pkgdir)
			except OSError:
				p.error = 'Directory %r does not exist' % pkgdir
				continue

			vname = p.requested_version.replace('*', '.*')
			rev = re.compile(vname, re.M)
			versions = [x for x in versions if rev.match(x)]
			versions.sort()

			try:
				p.version = versions[0]
			except IndexError:
				p.error = 'There is no package that satisfies %r %r' % (p.name, p.requested_version)

	def download_to_file(self, p, subdir, tmp):
		data = urllib.urlencode([('pkgname', p.name), ('pkgver', p.version), ('pkgfile', subdir)])
		req = urllib2.urlopen(get_download_url(), data, timeout=TIMEOUT)
		with open(tmp, 'wb') as f:
			while True:
				buf = req.read(8192)
				if not buf:
					break
				f.write(buf)

	def extract_tar(self, subdir, pkgdir, tmpfile):
		with tarfile.open(tmpfile) as f:
			temp = tempfile.mkdtemp(dir=pkgdir)
			try:
				f.extractall(temp)
				os.rename(temp, os.path.join(pkgdir, subdir))
			finally:
				try:
					shutil.rmtree(temp)
				except Exception:
					pass

	def get_pkg_dir(self, pkg, subdir):
		pkgdir = os.path.join(get_distnet_cache(), pkg.name, pkg.version)
		if not os.path.isdir(pkgdir):
			os.makedirs(pkgdir)

		target = os.path.join(pkgdir, subdir)
		if os.path.exists(target):
			return target

		(fd, tmp) = tempfile.mkstemp(dir=pkgdir)
		try:
			os.close(fd)
			self.download_to_file(pkg, subdir, tmp)
			if subdir == 'requires.txt':
				os.rename(tmp, target)
			else:
				self.extract_tar(subdir, pkgdir, tmp)
		finally:
			try:
				os.remove(tmp)
			except OSError as e:
				pass

		return target

	def __iter__(self):
		if not hasattr(self, 'pkg_list'):
			self.read_packages()
			self.compute_dependencies()
		for x in self.pkg_list:
			yield x
		raise StopIteration

packages = package_reader()

def load_tools(ctx, extra):
	global packages
	for pkg in packages:
		packages.get_pkg_dir(pkg, extra)
		noarchdir = packages.get_pkg_dir(pkg, 'noarch')
		#sys.path.append(noarchdir)
		for x in os.listdir(noarchdir):
			if x.startswith('waf_') and x.endswith('.py'):
				ctx.load(x.rstrip('.py'), tooldir=noarchdir)

def options(opt):
	packages.read_packages()
	load_tools(opt, 'requires.txt')

def configure(conf):
	load_tools(conf, conf.variant)

