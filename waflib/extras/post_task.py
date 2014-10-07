#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2013-2014

import functools
from waflib import Build
from waflib.TaskGen import feature, after_method


def _patch():
    """Update the BuildContext"""
    old_post_group = Build.BuildContext.post_group

    @functools.wraps(Build.BuildContext.post_group)
    def post_group(self):
        old_post_group(self)

        post_tasks = getattr(self, 'post_task_task_list', [])
        for tsk, post_task in post_tasks:
            if getattr(tsk, 'posted', False):
                for tsk in post_task:
                    tsk.post()

    Build.BuildContext.post_group = post_group


_patch()


@feature('post_task')
@after_method('process_use')
def add_manual_depencies(self):
    post_tasks = getattr(self.bld, 'post_task_task_list', [])
    post_task = set(self.to_list(getattr(self, 'post_task', [])))
    post_tasks.append((self,
                       [self.bld.get_tgen_by_name(dep) for dep in post_task]))
    self.bld.post_task_task_list = post_tasks
