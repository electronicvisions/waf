TOOLS=compat15,boost,test_base,gtest,pytest,pytest_runner,openmp,mr,symwaf2ic,symap2ic_doxygen,pypp
# Note take care to preseve the leading tab character in the following line!
PRELUDE=from waflib.extras.symwaf2ic import prelude; prelude()

main: waf
	./waf-light '--tools=${TOOLS}' '--prelude=	${PRELUDE}' configure build

clean:
	./waf-light distclean

.PHONY: clean
