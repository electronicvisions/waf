#! /usr/bin/env python
# encoding: utf-8

"""
This module assumes that only one build context is running at a given time, which
is not the case if you want to execute configuration tests in parallel.

Store some values on the buildcontext mapping file paths to
stat values and md5 values (timestamp + md5)
this way the md5 hashes are computed only when timestamp change (can be faster)
There is usually little or no gain from enabling this, but it can be used to enable
the second level cache with timestamps (WAFCACHE)

You may have to run distclean or to remove the build directory before enabling/disabling
this hashing scheme
"""

import os, stat
from waflib import Utils, Build, Node

STRONGEST = True

Build.SAVED_ATTRS.append('hashes_md5_tstamp')
def h_file(self):
	filename = self.abspath()
	st = os.stat(filename)

	cache = self.ctx.hashes_md5_tstamp
	if filename in cache and cache[filename][0] == st.st_mtime:
		return cache[filename][1]

	global STRONGEST
	if STRONGEST:
		ret = Utils.h_file(filename)
	else:
		if stat.S_ISDIR(st[stat.ST_MODE]):
			raise IOError('Not a file')
		ret = Utils.md5(str((st.st_mtime, st.st_size)).encode()).digest()

	cache[filename] = (st.st_mtime, ret)
	return ret
Node.Node.h_file = h_file

