import sys
import os
import codecs
import bottle
import shutil

def stpl(tsk):
    ps = tsk.inputs[0].abspath()
    pt = tsk.outputs[0].abspath()
    bld = tsk.generator.bld
    lookup,name=os.path.split(ps)
    st=bottle.template(name,template_lookup=[lookup], company = bld.env.company, guiname=bld.env.guiname, version=bld.env.version,
            dllname=bld.env.dllname, maxfuni=bld.env.maxfuni)
    with codecs.open(pt,mode='w',encoding="utf-8") as f: f.write(st)

#for files that will be created
def cp(self):
    shutil.copy(self.inputs[0].abspath(),self.outputs[0].abspath())

#for files that already exist
src2bld = lambda bld,x: shutil.copy(bld.path.find_node(x).abspath(), bld.path.get_bld().make_node(x).write('').abspath())

