How to create the windows installer
-----------------------------------

1. First you will need
   
   *  NSIS
   *  pyinstaller
   *  py-win32
   *  Python 2.*
   
2. Open a command prompt.  Goto this folder.  And run pyinstaller like:
   
       c:\python27\python.exe path\to\pyinstaller.py ftldat.spec
   
4. Check whether the version in ftldat.nsi is OK.
3. Run NSIS, by rightclicking on ftldat.nsi and using "Compile NSIS Script".
