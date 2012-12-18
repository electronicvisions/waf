#!/bin/bash

TOOLS="compat15,boost,test_base,gtest,openmp,mr,symwaf2ic,symap2ic_doxygen,pypp"
# Note take care to preseve the leading tab character in the following line!
PRELUDE="	from waflib.extras.symwaf2ic import prelude; prelude()"

./waf-light distclean
./waf-light "--tools=${TOOLS}" "--prelude=${PRELUDE}" configure build

