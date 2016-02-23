#!/usr/bin/env python

import hashlib
import os
import socket
import subprocess
import sys
import time
import textwrap

from cStringIO import StringIO
from glob import glob
from grp import getgrgid
from itertools import chain
from os import path
from pwd import getpwuid
from tarfile import TarFile, TarInfo
from textwrap import wrap


def wrap(text, **kwargs):
    dkwargs = {'subsequent_indent': '    '}
    dkwargs.update(kwargs)
    return os.linesep.join(textwrap.wrap(text, **dkwargs))

def add_string(archive, filename, data):
    """Create a file with the given filename and the content from data"""
    #TODO test with unicode...
    fileobj = StringIO(data)
    info = TarInfo(filename)
    info.size = len(data)
    info.mtime = time.time()
    info.uid = os.getuid()
    info.uname = getpwuid(info.uid).pw_name
    info.gid = os.getgid()
    info.gname = getgrgid(info.gid).gr_name
    archive.addfile(info, fileobj)

def get_repo_folders(root):
    "returns tuple with (abspath, path relative to root)"
    get_path = lambda p: (path.split(p)[0], path.split(path.relpath(p, root))[0])
    return [get_path(p) for p in glob(path.join(root, '**/.git'))]

def sha256sum(filename, blocksize=65536):
    hasher = hashlib.sha256()
    with open(filename, "rb") as f:
        for block in iter(lambda: f.read(blocksize), b""):
            hasher.update(block)
        return hasher.hexdigest()

def collect_git_revisions(folders):
    revisions = []
    for abspath, relpath in folders:
        output = subprocess.check_output(['git', 'rev-parse', '--verify', 'HEAD'], cwd=abspath).strip()
        revisions.append("{}: {}".format(relpath, output))
    return os.linesep.join(revisions)

def collect_untracked_files(folders):
    files = []
    for abspath, relpath in folders:
        output = subprocess.check_output(['git', 'ls-files', '-o'], cwd=abspath)
        files.extend(path.join(relpath, p) for p in output.splitlines() if p)
    return files

def collect_git_diffs(folders):
    patches = []
    for abspath, relpath in folders:
        patch = subprocess.check_output(['git', 'diff', '-p'], cwd=abspath)
        if patch:
            patches.append(("{}.patch".format(relpath), patch))
    return patches

def collect_enviroment():
    return os.linesep.join(
        "{}={}".format(k, v) for k, v in os.environ.iteritems())

def collect_modules():
    return subprocess.check_output(
        'module list', shell=True, stderr=subprocess.STDOUT)

def collect_waf():
    waf_path = subprocess.check_output('which waf', shell=True, stderr=subprocess.STDOUT)[:-1]
    if os.path.exists(waf_path):
        with open(waf_path) as waf_file:
            return waf_file.read()
    else:
        return None

def collect_hostname():
    return socket.gethostname()

def collect_waf_files(root):
    files = []
    targets = ['.symwaf2ic.conf.json', 'build/config.log', 'build/c4che/']
    for target in targets:
        if path.exists(path.join(root, target)):
            files.append(target)
    return files

def collect_conda_env():
    if 'anaconda' in sys.exec_prefix:
        anaconda_env = path.basename(sys.exec_prefix)
        cmd = [
            path.join(sys.exec_prefix, 'bin', 'conda'),
            'env',
            'export',
            '-n',
            anaconda_env
        ]
        return subprocess.check_output(cmd, stderr=subprocess.STDOUT)

def collect_waf_installed_file_hashes(root):
    """Collect files installed in bin, lib and etc"""
    files = []
    for subfolder in ['bin', 'lib', 'etc']:
        folder = path.join(root, subfolder)
        for dirpath, _, filenames in os.walk(folder, followlinks=True):
            files.extend(path.join(dirpath, f) for f in filenames)

    result = ["# SHA256 filename os.stat"]
    for filename in files:
        result.append("{} {} {}".format(
            sha256sum(filename), filename, os.stat(filename)))
    return os.linesep.join(result)

def collect_system_packages():
    return subprocess.check_output(
        ['dpkg', '-l'])

def main():
    root = os.getcwd()
    git_folders = get_repo_folders(root)
    print wrap(
        "Collecting: "
        "enviroment, modules, waf, hostname, python, "
        "anaconda packages, debian packages")
    print "Collectiong changes in repos:"
    print wrap(', '.join(f for _, f in git_folders))

    PREFIX = "PROVENANCE_DATA"

    env = collect_enviroment()
    modules = collect_modules()
    hostname = collect_hostname()
    repo_revisions = collect_git_revisions(git_folders)
    waf = collect_waf()
    patches = collect_git_diffs(git_folders)
    packages = collect_system_packages()
    conda_env = collect_conda_env()

    installed_file_hashes = collect_waf_installed_file_hashes(root)

    waf_files = collect_waf_files(root)
    untracked_files = collect_untracked_files(git_folders)

    # We order by liklyless of access
    with TarFile("provenance.tar", "w") as archive:

        # String data
        add_string(archive, path.join(PREFIX, "ENV"), env)
        add_string(archive, path.join(PREFIX, "MODULES"), modules)
        add_string(archive, path.join(PREFIX, "HOSTNAME"), hostname)
        add_string(archive, path.join(PREFIX, "REPOS"), repo_revisions)
        add_string(archive, path.join(PREFIX, "PYTHON"), sys.version)
        add_string(archive, path.join(PREFIX, "INSTALLED"), installed_file_hashes)
        add_string(archive, path.join(PREFIX, "DEBIAN_PACKAGES"), packages)
        if conda_env:
            add_string(archive, path.join(PREFIX, "anaconda_virtual_env.yaml"), conda_env)
        if waf:
            add_string(archive, path.join(PREFIX, "waf_excutable_from_path"), waf)

        # Diffs
        for name, diff in patches:
            add_string(archive, path.join('UNCOMMITED', name), diff)

        # Untracked stuff
        for filename in waf_files:
            archive.add(filename, path.join('WAF_CONFIG', filename))

        # Untracked stuff
        for filename in untracked_files:
            archive.add(filename, path.join('UNTRACKED', filename))


if __name__ == '__main__':
    main()
