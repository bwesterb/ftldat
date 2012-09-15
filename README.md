CLI tool to pack and unpack .dat files of FTL
=============================================

`ftldat` allows you to pack and unpack the `data.dat` and `resource.dat`
files of [FTL](http://ftlgame.com).

Installation
------------
Windows
=======
Download the installer, here: http://westerbaan.name/~bas/ftldat/ftldat-r4.exe

Linux and Mac OS X
==================
Simply execute

    pip install ftldat

or from this source distribution, run

    python setup.py install

Unpacking
---------
Run

    ftldat unpack path/to/data.dat

This will unpack to `path/to/data.dat-unpacked`.  To unpack to another
folder, use:

    ftldat unpack path/to/data.dat path/to/extract/to

Packing
-------
If you have a `data.dat-unpacked` folder and want to pack it again, run:

    ftldat pack path/to/data.dat

To pack another folder, run:

    ftldat pack path/to/data.dat path/to/pack

Information
-----------
To show information about a `.dat` file, run:

    ftldat info path/to/data.dat
