TOOLS=compat15,boost,test_base,gtest,pytest,pytest_runner,openmp,mr,symwaf2ic,symap2ic_doxygen,pypp
# Note take care to preseve the leading tab character in the following line!
PRELUDE=from waflib.extras.symwaf2ic import prelude; prelude()
TOP=$(CURDIR)/$(dir $(lastword $(MAKEFILE_LIST)))

waf:
	cd $(TOP) && ./waf-light '--tools=${TOOLS}' '--prelude=	${PRELUDE}' configure build

clean:
	cd $(TOP) && ./waf-light distclean

.PHONY: clean waf