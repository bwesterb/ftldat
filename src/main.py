#!/usr/bin/env python

# ftldat r7
#
#   (c) 2012 - Bas Westerbaan <bas@westerbaan.name>
#
#    May be redistributed under the conditions of the
#      GNU General Public License version 3.  See LICENSE.

import collections
import itertools
import argparse
import tempfile
import hashlib
import os.path
import struct
import sys
import os

def ftl_path_split(path):
    """ Split a path in the way FTL expects them to be in .dat files.
        That is: the UNIX way. """
    return path.split('/')

def ftl_path_join(*args):
    """ Joins paths in the way FTL expects them to be in .dat files.
        That is: the UNIX way. """
    return '/'.join(args)

def nice_size(s):
    """ Nicely formats size.

        >>> nice_size(12345)
        12 KiB
        """
    if s <= 1024: return str(s) + ' B  '
    s /= 1024
    if s <= 1024: return str(s) + ' KiB'
    s /= 1024
    if s <= 1024: return str(s) + ' MiB'
    s /= 1024
    if s <= 1024: return str(s) + ' GiB'
    s /= 1024
    return str(s) + 'TiB'

class FTLDatError(Exception):
    pass

ftldat_entry = collections.namedtuple('ftldat_entry',
                        ('filename', 'size', 'offset'))

class BasePack(object):
    """ Base pack.  Can be implemented either by a folder (unpacked) or
        by a FTL dat file. """
    def list(self):
        """ Returns an iterator over the filenames.
            NOTE the filenames are / separated. """
        raise NotImplementedError
    def list_sizes(self):
        """ Returns an iterator over the pairs of (filename, filesize). """
        raise NotImplementedError
    def add(self, filename, f, size):
        """ Adds the first <size> bytes read from <f> as <filename> to
            the pack. """
        raise NotImplementedError
    def extract_to(self, filename, f):
        """ Writes the contents of the file with <filename> to <f>. """
        raise NotImplementedError
    def remove(self, filename):
        """ Removes the file with <filename> from the pack. """
        raise NotImplementedError
    def __contains__(self, filename):
        """ Returns whether <filename> is in the pack. """
        raise NotImplementedError

class FolderPack(object):
    def __init__(self, root):
        self.root = root
    #
    # Base interface functions
    #
    def list(self):
        s = [()]
        while s:
            current = s.pop()
            path = os.path.join(self.root, *current)
            if os.path.isfile(path):
                yield ftl_path_join(*current)
            elif os.path.isdir(path):
                for child in os.listdir(path):
                    s.append(current + (child,))
    def list_sizes(self):
        for filename in self.list():
            yield (filename, os.stat(os.path.join(self.root,
                                *ftl_path_split(filename))).st_size)
    def add(self, filename, f, size):
        path = os.path.join(self.root, *ftl_path_split(filename))
        if os.path.exists(path):
            raise KeyError("File already exists")
        # Ensure the parent directory exists
        dirpath = os.path.dirname(path)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        # Create file
        with open(path, 'wb') as fo:
            todo = size
            while todo:
                buf = f.read(min(todo, 4096))
                if not buf:
                    raise ValueError("f is too small")
                fo.write(buf)
                todo -= len(buf)
    def extract_to(self, filename, f):
        path = os.path.join(self.root, *ftl_path_split(filename))
        if not os.path.exists(path):
            raise KeyError
        with open(path, 'rb') as fi:
            while True:
                buf = fi.read(4096)
                if not buf:
                    break
                f.write(buf)
    def remove(self, filename):
        path = os.path.join(self.root, *ftl_path_split(filename))
        if not os.path.exists(path):
            raise KeyError
        os.unlink(path)
    def __contains__(self, filename):
        return os.path.exists(os.path.join(self.root,
                        *ftl_path_split(filename)))

    #
    # Extra interface functions
    #
    def open(self, filename, mode='rb'):
        """ Returns a new fileobj for <filename>. """
        path = os.path.join(self.root, *ftl_path_split(filename))
        dirpath = os.path.dirname(path)
        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        return open(path, mode)

class FTLPack(object):
    def __init__(self, filename_or_fileobj, create=False, index_size=2048):
        """ Opens or creates a FTL .dat by <filename_or_fileobj>

            If <create> is False, the default, we will assume that <f> already
            contains a FTL .dat and read its index.  <index_size> is ignored.

            If <create> is True, we will assume that <f> does not contain an
            existing FTL .dat and create an index of size <index_size>. """
        # We actually set these properly in _create_index and _read_index.
        # This is just for documentation.
        self.index = []      # [ idx: offset ]
        self.index_free = [] # [ idx with self.index[idx] == 0 ]
        self.metadata = []   # [ idx: (filename, size, offset) ]
        self.filenames = {}  # { filename: idx }
        self.eof = 0         # size of the file; thus also the offset of the
                             # end of the file

        # Open the file
        if isinstance(filename_or_fileobj, basestring):
            if create:
                self.f = open(filename_or_fileobj, 'wb+')
            else:
                self.f = open(filename_or_fileobj, 'rb+')
        else:
            self.f = filename_or_fileobj

        # Read or create the index
        if create:
            self._create_index(index_size)
        else:
            self._read_index()

    #
    # Internal functions
    #
    def _create_index(self, index_size=2048):
        """ Creates a new index.
            WARNING. This will remove the old index, if any. """
        # Set new state
        self.index = [0] * index_size
        self.index_free = range(index_size-1,-1,-1)
        self.metadata = [None] * index_size
        self.filenames = {}
        self.eof = index_size * 4 + 4
        # Write to file
        self.f.seek(0, 0)
        self.f.write(struct.pack('<L', index_size))
        for n in xrange(index_size):
            self.f.write(struct.pack('<L', 0))
    def _read_index(self):
        """ Reads (or re-reads) the index from the file. """
        # Read index size
        self.f.seek(0, 0)
        index_size = struct.unpack('<L', self.f.read(4))[0]
        # Prepare new state
        self.index = [0] * index_size
        self.metadata = [None] * index_size
        self.filenames = {}
        self.index_free = []
        # Read the index
        for n in xrange(index_size):
            self.index[n] = struct.unpack('<L', self.f.read(4))[0]
        # Read the metadata
        for n, offset in enumerate(self.index):
            if not offset:
                self.index_free.append(n)
                continue
            self.f.seek(offset, 0)
            size, lfn = struct.unpack('<LL', self.f.read(8))
            filename = self.f.read(lfn)
            self.metadata[n] = ftldat_entry(filename=filename,
                                            size=size,
                                            offset=offset + 8 + len(filename))
            if filename in self.filenames:
                raise FTLDatError("Filename %s occurs more than once" %
                                    filename)
            self.filenames[filename] = n
        # Determine eof
        self.f.seek(0, 2)
        self.eof = self.f.tell()
    def _move_to_eof(self, n):
        """ Move the nth entry to the end of the file.  Used by _grow_index """
        # What to do?
        old_offset = self.index[n]
        new_offset = self.eof
        size = self.metadata[n].size + len(self.metadata[n].filename) + 8
        self.eof += size
        todo = size
        # Do it
        while todo:
            self.f.seek(old_offset + size - todo, 0)
            buf = self.f.read(min(4096, todo))
            assert buf
            self.f.seek(new_offset + size - todo, 0)
            self.f.write(buf)
            todo -= len(buf)
        # Update the index and state
        self.f.seek(n*4 + 4, 0)
        self.f.write(struct.pack('<L', new_offset))
        self.index[n] = new_offset
        self.metadata[n] = self.metadata[n]._replace(
                    offset=new_offset + len(self.metadata[n].filename)+8)
    def _grow_index(self, amount=1):
        """ Grows the index with at least <amount> entries.
            This is done by moving the first file after the index to the
            end of the file. """ 
        while True:
            # For how many new free entries is there space after the index and
            # before the first file?
            index_used = [n for n in xrange(len(self.index)) if self.index[n]]
            if not index_used:
                # There is no file after the index, we can grow with as much
                # as we like.  Limit ourselves to amount.
                free_room = amount
            else:
                n = min(index_used, key=lambda n: self.index[n])
                free_room = (self.index[n] - len(self.index)*4-4) / 4
            if free_room >= amount:
                break
            # If it is not enough, move the first file and check again
            self._move_to_eof(n)
        # Update state
        self.index_free.extend(xrange(len(self.index) + free_room - 1,
                                len(self.index) - 1, -1))
        for n in xrange(free_room):
            self.index.append(0)
            self.metadata.append(None)
        # And write to the file
        self.f.seek(0, 0)
        self.f.write(struct.pack('<L', len(self.index)))
        self.f.seek((len(self.index) - free_room)*4+4, 0)
        for n in xrange(free_room):
            self.f.write(struct.pack('<L', 0))
    #
    # Base interface functions
    #
    def list(self):
        return self.filenames.iterkeys()
    def list_sizes(self):
        for filename, n in self.filenames.iteritems():
            yield (filename, self.metadata[n].size)
    def add(self, filename, f, size):
        if filename in self.filenames:
            raise ValueError("filename already in use")
        # Find an index and offset
        if not self.index_free:
            self._grow_index()
        assert self.index_free
        n = self.index_free.pop()
        offset = self.eof
        self.eof += size + 8 + len(filename)
        # Update state
        self.index[n] = offset
        self.filenames[filename] = n
        self.metadata[n] = ftldat_entry(filename=filename,
                                        size=size,
                                        offset=offset+8+len(filename))
        # Write metadata
        self.f.seek(n*4 + 4, 0)
        self.f.write(struct.pack('<L', offset))
        self.f.seek(offset, 0)
        self.f.write(struct.pack('<LL', size, len(filename)))
        self.f.write(filename)
        # Write the data
        todo = size
        while todo:
            buf = f.read(min(todo, 4096))
            if not buf:
                raise ValueError("f is too small")
            self.f.write(buf)
            todo -= len(buf)
    def extract_to(self, filename, f):
        """ Writes the contents of the file with <filename> to <f>. """
        # Find index and offset
        if filename not in self.filenames:
            raise KeyError
        n = self.filenames[filename]
        offset = self.metadata[n].offset
        # And pump!
        self.f.seek(self.metadata[n].offset, 0)
        todo = self.metadata[n].size
        while todo:
            buf = self.f.read(min(todo, 4096))
            assert buf
            f.write(buf)
            todo -= len(buf)
    def remove(self, filename):
        """ Removes the file with <filename> from the pack. """
        # Find index
        if filename not in self.filenames:
            raise KeyError
        n = self.filenames[filename]
        # Update state
        self.index[n] = 0
        self.index_free.append(n)
        self.metadata[n] = None
        del self.filenames[filename]
        # Write to file
        self.f.seek(n*4+4, 0)
        self.f.write(struct.pack('<L', 0))
    def __contains__(self, filename):
        return filename in self.filenames
    #
    # New interface functions
    #
    def list_metadata(self):
        """ Returns a list of quadruples (idx, filename, size, offset) """
        return [(n, x.filename, x.size, x.offset)
                    for n, x in enumerate(self.metadata) if x]
    def repack(self):
        """ Repacks the datfile.  This will remove overhead, which could
            be created when adding, removing or replacing files. """
        # Create the new index
        entry = collections.namedtuple('repack_entry',
                            ('old_n', 'old_offset', 'filename', 'size',
                                    'new_offset'))
        result = collections.namedtuple('result',
                            ('bytes_moved', 'old_size', 'new_size'))
        bytes_moved = 0
        old_size = self.eof
        entries = [entry(old_n=n,
                         old_offset=addr,
                         filename=self.metadata[n].filename,
                         size=self.metadata[n].size,
                         new_offset=None)
                        for n, addr in enumerate(self.index) if addr]
        entries.sort(key=lambda x: x.old_offset)
        # Check for overlap
        for i in xrange(len(entries) - 1):
            if (entries[i].old_offset + entries[i].size
                    > entries[i+1].old_offset):
                raise FTLDatError("Cannot repack datfile with overlapping "+
                                  "entries")
        # Create new layout
        offset = 4 + len(entries) * 4
        for n, entry in enumerate(entries):
            entries[n] = entry._replace(new_offset=offset)
            offset += entry.size + len(entry.filename) + 8
        new_total_size = offset
        # Write new index
        assert len(entries) <= len(self.index)
        if len(entries) == len(self.index):
            skipped = True
        else:
            self.f.seek(0, 0)
            self.f.write(struct.pack('<L', len(entries)))
            bytes_moved += 4
            skipped = False
        for n, entry in enumerate(entries):
            if entry.new_offset == self.index[n]:
                skipped = True
            else:
                if skipped:
                    self.f.seek(4 + 4 * n, 0)
                self.f.write(struct.pack('<L', entry.new_offset))
                bytes_moved += 4
                skipped = False
        # Move files
        for entry in entries:
            # Do not move the file, if we do not need to
            if entry.new_offset == entry.old_offset:
                continue
            size = entry.size + 8 + len(entry.filename)
            todo = size
            bytes_moved += todo
            assert entry.new_offset < entry.old_offset
            while todo:
                self.f.seek(entry.old_offset + size - todo, 0)
                buf = self.f.read(min(4096, todo))
                self.f.seek(entry.new_offset + size - todo, 0)
                self.f.write(buf)
                todo -= len(buf)
        # Truncate the ftldat!
        self.f.truncate(new_total_size)
        # Update state
        self.eof = new_total_size
        self.index = [entry.new_offset for entry in entries]
        self.metadata = [ftldat_entry(
                            filename=entry.filename,
                            size=entry.size,
                            offset=entry.new_offset + 8 + len(entry.filename))
                                for entry in entries]
        self.filenames = {}
        for n, entry in enumerate(entries):
            self.filenames[entry.filename] = n
        self.index_free = []
        return result(old_size=old_size, new_size=new_total_size,
                        bytes_moved=bytes_moved)

class HashFile:
    """ Helper class.  Data written to this virtual file is hashed. """
    def __init__(self):
        self.h = hashlib.md5()
    def write(self, s):
        self.h.update(s)
    def finish_up(self):
        return self.h.hexdigest()

class Program(object):
    def cmd_list(self):
        pack = FTLPack(self.args.datfile)
        for filename in pack.list():
            print filename
    def cmd_hashes(self):
        pack = FTLPack(self.args.datfile)
        hashes = {}
        # First generate hashes sequentially
        for filename in pack.list():
            hf = HashFile()
            pack.extract_to(filename, hf)
            hashes[filename] = hf.finish_up()
        filenames = hashes.keys()
        # Then sort and display
        filenames.sort()
        for filename in filenames:
            print '%s %s' % (filename, hashes[filename])
    def cmd_info(self):
        print 'Loading index ...'
        pack = FTLPack(self.args.datfile)
        print 
        print "%-4s %-7s %-57s%10s" % ('#', 'offset', 'filename', 'size')
        N = 0
        c_size = 0
        for i, filename, size, offset in pack.list_metadata():
            print "%-4s %-7s %-57s%10s" % (i, hex(offset)[2:], filename,
                            str(size) if self.args.bytes else nice_size(size))
            if self.args.hashes:
                hf = HashFile()
                pack.extract_to(filename, hf)
                print "        md5: %s" % hf.finish_up()
            c_size += size
            N += 1
        print
        print '  %s/%s entries' % (N, len(pack.index))
        print '  %s' % str(c_size) if self.args.bytes else nice_size(c_size)
    def cmd_pack(self):
        if os.path.exists(self.args.datfile) and not self.args.force:
            print ('ERROR %s already exists. Use -f to override.'
                    % self.args.datfile)
            return -2
        if self.args.folder is None:
            self.args.folder = self.args.datfile + '-unpacked'
        print 'Listing files to pack ...'
        folder = FolderPack(self.args.folder)
        files = list(folder.list_sizes())
        if self.args.indexsize is not None:
            indexSize = max(self.args.indexsize, len(files))
        else:
            indexSize = len(files)
        print 'Create datfile ...'
        pack = FTLPack(self.args.datfile, create=True, index_size=indexSize)
        print 'Packing ...'
        for _file, size in files:
            print " %s" % _file
            pack.add(_file, folder.open(_file), size)
    def cmd_append(self):
        pack = FTLPack(self.args.datfile)
        if not os.path.exists(self.args.appendix):
            print 'ERROR %s does not exist.' % self.args.appendix
            return -8
        f = None
        try:
            if not self.args.filename in pack:
                if not self.args.force:
                    print ('ERROR %s does not exist.  Use -f to add anyway'
                            % self.args.filename)
                    return -9
                f = open(self.args.appendix, 'rb')
            else:
                f = tempfile.TemporaryFile()
                pack.extract_to(self.args.filename, f)
                pack.remove(self.args.filename)
                with open(self.args.appendix, 'rb') as fi:
                    while True:
                        buf = fi.read(4096)
                        if not buf:
                            break
                        f.write(buf)
                f.seek(0, 0)
            size = os.fstat(f.fileno()).st_size
            pack.add(self.args.filename, f, size)
        finally:
            if f:
                f.close()
    def cmd_add(self):
        pack = FTLPack(self.args.datfile)
        if not os.path.exists(self.args.file):
            print 'ERROR %s does not exist.' % self.args.file
            return -7
        if self.args.filename is None:
            self.args.filename = ftl_path_join(*ftl_path_split(self.args.file))
        size = os.stat(self.args.file).st_size
        if self.args.filename in pack:
            if not self.args.force:
                print ('ERROR %s already exists. Use -f to replace.'
                        % self.args.filename)
                return -2
            pack.remove(self.args.filename)
        with open(self.args.file, 'rb') as f:
            pack.add(self.args.filename, f, size)
    def cmd_extract(self):
        pack = FTLPack(self.args.datfile)
        if (self.args.target and os.path.exists(self.args.target) and
                not self.args.force):
            print ('ERROR %s already exists.  Use -f to override.'
                    % self.args.target)
            return -4
        if not self.args.filename in pack:
            print 'ERROR %s does not exist' % self.args.filename
            return -5
        try:
            if self.args.target:
                f = open(self.args.target, 'wb')
            else:
                f = sys.stdout
            pack.extract_to(self.args.filename, f)
        finally:
            if f is not sys.stdout:
                f.close()
    def cmd_repack(self):
        print 'Repacking ...'
        pack = FTLPack(self.args.datfile)
        res = pack.repack()
        print
        print ' old size      %s (%s)' % (nice_size(res.old_size),
                                          res.old_size)
        print ' new size      %s (%s; %s%%)' % (
                            nice_size(res.new_size), res.new_size,
                        round(100.0 * res.new_size / res.old_size, 1))
        print ' bytes moved   %s (%s; %s%%)' % (
                            nice_size(res.bytes_moved), res.bytes_moved,
                        round(100.0 * res.bytes_moved / res.new_size, 1))
    def cmd_remove(self):
        pack = FTLPack(self.args.datfile)
        if not self.args.filename in pack:
            if not self.args.force:
                print ('ERROR %s does not exist.'
                        % self.args.filename)
                return -6
        else:
            pack.remove(self.args.filename)
    def cmd_replace(self):
        pack = FTLPack(self.args.datfile)
        if not os.path.exists(self.args.replacement):
            print 'ERROR %s does not exist.' % self.args.replacement
            return  -10
        size = os.stat(self.args.replacement).st_size
        if not self.args.filename in pack:
            if not self.args.force:
                print ('ERROR %s does not exist. Use -f to add anyway.'
                        % self.args.filename)
                return -3
        else:
            pack.remove(self.args.filename)
        with open(self.args.replacement, 'rb') as f:
            pack.add(self.args.filename, f, size)
    def cmd_unpack(self):
        if self.args.folder is None:
            self.args.folder = self.args.datfile + '-unpacked'
        print 'Loading index ... '
        pack = FTLPack(self.args.datfile)
        folder = FolderPack(self.args.folder)
        print 'Extracting ...'
        for filename in pack.list():
            if filename in folder and not self.args.force:
                print 'ERROR %s already exists. Use -f to override.' % filename
                return -1
            print " %s" % filename
            pack.extract_to(filename, folder.open(filename, 'wb'))
    def main(self):
        self.parse_args()
        return self.args.func()
    def parse_args(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(title='commands',
                                        description='Valid commands')
        parser_info = subparsers.add_parser('info',
                help='Shows detailed technical information about a datfile')
        parser_info.add_argument('datfile',
                help='The datfile to examine')
        parser_info.add_argument('--hashes', '-H', action='store_true',
                help='Show MD5 hashes')
        parser_info.add_argument('--bytes', '-B', action='store_true',
                help='Show sizes in bytes')
        parser_info.set_defaults(func=self.cmd_info)

        parser_pack = subparsers.add_parser('pack',
                help='Creates a datfile from a folder')
        parser_pack.add_argument('datfile',
                help="The datfile to create")
        parser_pack.add_argument('folder', nargs='?', default=None,
                help="The folder to pack. Defaults to [datfile]-unpacked")
        parser_pack.add_argument('--indexsize', '-I', default=None, type=int,
                help="Index size.")
        parser_pack.add_argument('-f', '--force', action='store_true',
                help='Override existing datfile')
        parser_pack.set_defaults(func=self.cmd_pack)

        parser_unpack = subparsers.add_parser('unpack',
                help='Unpacks a datfile to a folder')
        parser_unpack.add_argument('datfile',
                help="The datfile to unpack")
        parser_unpack.add_argument('folder', nargs='?', default=None,
                help="The folder to extract to. Defaults to [datfile]-unpacked")
        parser_unpack.add_argument('-f', '--force', action='store_true',
                help='Override existing files')
        parser_unpack.set_defaults(func=self.cmd_unpack)

        parser_add = subparsers.add_parser('add',
                help='Add a single file to a datfile')
        parser_add.add_argument('datfile',
                help='The datfile to add the file to')
        parser_add.add_argument('file',
                help='The file to add')
        parser_add.add_argument('filename', nargs='?', default=None,
                help='The filename the file will have in the datfile.  '+
                     'Defaults to [file]')
        parser_add.add_argument('-f', '--force', action='store_true',
                help='Overrides [filename] if it already exists')
        parser_add.set_defaults(func=self.cmd_add)

        parser_append = subparsers.add_parser('append',
                help='Append a file to an existing file in the datfile')
        parser_append.add_argument('datfile',
                help='The datfile')
        parser_append.add_argument('filename',
                help='The file to append to')
        parser_append.add_argument('appendix',
                help='The file to append')
        parser_append.add_argument('-f', '--force', action='store_true',
                help='Create [filename] if it did not exist')
        parser_append.set_defaults(func=self.cmd_append)

        parser_replace = subparsers.add_parser('replace',
                help='Replace a single file in the datfile')
        parser_replace.add_argument('datfile',
                help='The datfile to replace the file to')
        parser_replace.add_argument('replacement',
                help='The file to replace [filename] with')
        parser_replace.add_argument('filename',
                help='The filename of the file to replace in the datfile')
        parser_replace.add_argument('-f', '--force', action='store_true',
                help='Adds [replacement] even if [filename] does not exist')
        parser_replace.set_defaults(func=self.cmd_replace)

        parser_remove = subparsers.add_parser('remove',
                help='Removes a file from the datfile')
        parser_remove.add_argument('datfile',
                help='The datfile to remove the file from')
        parser_remove.add_argument('filename',
                help='The filename of the file to remove')
        parser_remove.add_argument('-f', '--force', action='store_true',
                help='Do not error when [filename] does not exist')
        parser_remove.set_defaults(func=self.cmd_remove)

        parser_extract = subparsers.add_parser('extract',
                help='Extract a single file from a datfile')
        parser_extract.add_argument('datfile',
                help='The datfile to extract from')
        parser_extract.add_argument('filename',
                help='The filename of the file to extract')
        parser_extract.add_argument('target', nargs='?', default=None,
                help='The file to extract to.  Defaults to stdout')
        parser_extract.add_argument('-f', '--force', action='store_true',
                help='Overrides [target] if it already exists')
        parser_extract.set_defaults(func=self.cmd_extract)

        parser_hashes = subparsers.add_parser('hashes',
                help='Shows the filenames and their md5 hashes alphabetically.'+
                     '  Useful for debugging.')
        parser_hashes.add_argument('datfile',
                help='The datfile to examine')
        parser_hashes.set_defaults(func=self.cmd_hashes)

        parser_repack = subparsers.add_parser('repack',
                help='Repacks the datfile: removes overhead')
        parser_repack.add_argument('datfile',
                help='The datfile to repack')
        parser_repack.set_defaults(func=self.cmd_repack)

        parser_list = subparsers.add_parser('list',
                help='Lists the filenames in the datfile')
        parser_list.add_argument('datfile',
                help='The datfile to examine')
        parser_list.set_defaults(func=self.cmd_list)

        self.args = parser.parse_args()

def main():
    return Program().main()

if __name__ == '__main__':
    sys.exit(main())
    
# vim: et:sw=4:ts=4:bs=2
