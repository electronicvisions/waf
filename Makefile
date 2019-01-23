# ECM: This is not trivially splittable as we would have to replace the
# whitespace (which is generated from the escaped newline) into nothing.
# I think, that's too much work to make a single variable definition nicer :p.
TOOLS=boost,gccdeps,clang_compilation_database,documentation,gtest,jenkins,mr,nosepatch,openmp,post_task,pypp,genpybind,pytest,symwaf2ic,symwaf2ic_prelude,symwaf2ic_misc,test_base,visionflags,cross_ar,cross_as,cross_gcc,cross_gxx,nux_compiler,nux_assembler,objcopy,local_rpath,c_emscripten

# Note take care to preseve the leading tab character in the following line!
PRELUDE=from waflib.extras.symwaf2ic_prelude import prelude; prelude()
TOP=$(CURDIR)/$(dir $(lastword $(MAKEFILE_LIST)))

waf:
	cd $(TOP) && ./waf-light '--tools=${TOOLS}' '--prelude=	${PRELUDE}' --nostrip --zip-type=gz configure build

clean:
	cd $(TOP) && ./waf-light distclean

.PHONY: clean waf
