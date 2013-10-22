#!/usr/bin/env python
# encoding: utf-8
# Christoph Koke, 2013

from waflib.TaskGen import task_gen, feature, after_method


def _patch_task_gen_post():
    old_post = task_gen.post

    def post(self):
        if old_post(self):
            for tsk in getattr(self, 'post_on_post', []):
                tsk.post()
            return True
        else:
            return False

    task_gen.post = post


_patch_task_gen_post()


@feature('post_task')
@after_method('process_use')
def add_manual_depencies(self):
    self.post_on_post = getattr(self, 'post_on_post', [])
    post_tasks = set(self.to_list(getattr(self, 'post_task', [])))
    for dep in post_tasks:
        dep_task_gen = self.bld.get_tgen_by_name(dep)
        self.post_on_post.append(dep_task_gen)
