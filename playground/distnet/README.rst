#######
distnet
#######

This example provides an example of the `remote` extras tool,
used to build and share binary packages in the context of an intranet.

Usage
#####

Run the following in order in three distinct consoles:

1. start the server::

     cd server && ./start.sh

2. publish a package::
   
     cd app && waf configure_all build_all package publish

3. use a package in a project::
   
     cd app2 && waf configure_all build_all

Features
########

- a simple cgi server helps uploading/distributing the files
- headers can be redistributed
- binary data can be redistributed
- configuration scripts can be redistributed along with build rules
- packages are compressed on the server

Limitations
###########

- Waf and Python cannot be distributed as a packages (may require another process or an auto-update system)
- all dependencies must be specified at the moment, and there is no consistency verification
- once a folder is written to the cache it is never updated again
- there is no integrity verification aside from the package compresssion
- files submitted must not be small enough
- no server security (do it yourself!)

