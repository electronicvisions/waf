TOOLS=boost,clang_compilation_database,documentation,gtest,mr,nosepatch,openmp,post_task,pypp,pypp,pytest,symap2ic_doxygen,symwaf2ic,symwaf2ic_prelude,test_base

# Note take care to preseve the leading tab character in the following line!
PRELUDE=from waflib.extras.symwaf2ic_prelude import prelude; prelude()
TOP=$(CURDIR)/$(dir $(lastword $(MAKEFILE_LIST)))

waf:
	cd $(TOP) && ./waf-light '--tools=${TOOLS}' '--prelude=	${PRELUDE}' --nostrip configure build

clean:
	cd $(TOP) && ./waf-light distclean

.PHONY: clean waf
