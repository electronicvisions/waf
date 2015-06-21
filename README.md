Waf is a Python-based framework for configuring, compiling and installing applications. Here are perhaps the most important features of Waf:

  * *Automatic build order*: the build order is computed from input and output files, among others
  * *Automatic dependencies*: tasks to execute are detected by hashing files and commands
  * *Performance*: tasks are executed in parallel automatically, the startup time is meant to be fast (separation between configuration and build)
  * *Flexibility*: new commands and tasks can be added very easily through subclassing, bottlenecks for specific builds can be eliminated through dynamic method replacement
  * *Extensibility*: though many programming languages and compilers are already supported by default, many others are available as extensions
  * *IDE support*: Eclipse, Visual Studio and Xcode project generators (waflib/extras/)
  * *Documentation*: the application is based on a robust model documented in [The Waf Book](https://waf.io/book/) and in the [API docs](https://waf.io/apidocs/)
  * *Python compatibility*: cPython 2.5 to 3.4, Jython 2.5, IronPython, and Pypy

Waf is used in particular by innovative companies such as [Avalanche Studios](http://www.avalanchestudios.se) and by open-source projects such as [the Samba project](https://www.samba.org/). Learn more about Waf by reading [The Waf Book](https://waf.io/book/).

For researchers and build system writers, Waf also provides a framework for creating [custom build systems](https://github.com/waf-project/waf/tree/master/build_system_kit) and [package distribution systems](https://github.com/waf-project/waf/tree/master/playground/distnet/README.rst).

Download the project from our page on [waf.io](https://waf.io/) or from the mirror on [freehackers.org](http://www.freehackers.org/~tnagy/release/).
