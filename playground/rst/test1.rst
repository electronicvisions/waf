#########
Example 1
#########

:purpose: demonstrate basic rst processing

.. figure:: test.svg
   :align: center
   :width: 50%

   This is a static svg file

.. figure:: test.png
   :align: center
   :width: 50%

   This figure is a png file generated
   (in the build folder of course).

   As of 2013-08-25, rst2pdf and docutils do not have
   some way of specifying include paths, in which includes
   are searched.

   So the figure is broken.
   
   We could generate the figure in the source directory,
   but I prefer not having a figure at all for the sake
   of cleanleness.


.. include:: generated.rst


