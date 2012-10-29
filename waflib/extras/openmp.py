#!/usr/bin/env python
# -*- coding: utf-8 -*-

from waflib import Options

TEST_CODE="""
#include <omp.h>
int main()
{
    return omp_get_num_threads();
}
"""

def options(opt):
    """
    Provide options for gtest tests
    """
    opt.add_option('--disable-openmp', action='store_true', default=False,
                   dest="openmp_disable", help='Disable use of openmp')

def configure(cfg):
    if getattr(Options.options, 'openmp_disable', False):
        return

    for flag in ['-fopenmp','-openmp','-mp','-xopenmp','-omp','-qsmp=omp']:
        try:
            cfg.check_cxx(
                msg = 'Checking for OpenMP flag %s' % flag,
                fragment = TEST_CODE,
                cflags = flag,
                cxxflags = flag,
                linkflags = flag,
                uselib_store = 'OPENMP',
                define_name = 'HAVE_OPENMP'
                )
        except cfg.errors.ConfigurationError:
            pass
        else:
            break
