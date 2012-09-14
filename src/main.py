#!/usr/bin/env python

import itertools
import argparse
import hashlib
import os.path
import struct
import sys
import os

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

class FTLDatPacker(object):
    """ Class to create a FTL .dat file.

        >>> packer = FTLDatPacker(open('data.dat', 'wb'), 12345)
        >>> packer.add(open('myfile.png'), 'data/myfile.png', 32123)
        """
    def __init__(self, f, index_size=2048):
        self.index_size = index_size
        self.first_free_index = 0
        self.first_free_offset = 4 + 4*index_size
        self.f = f
        self.f.seek(0, 0)
        self.f.write(struct.pack("<L", index_size))
        for i in xrange(index_size):
            self.f.write(struct.pack("<L", 0))
    def add(self, filename, f, size):
        if self.first_free_index == self.index_size:
            raise FTLDatPacker, "Index is full"
        index = self.first_free_index
        offset = self.first_free_offset
        self.first_free_index += 1
        self.f.seek(4 + 4*index)
        self.f.write(struct.pack("<L", offset))
        self.f.seek(offset, 0)
        self.f.write(struct.pack("<LL", size, len(filename)))
        self.f.write(filename)
        self.first_free_offset += 8 + size + len(filename)
        to_write = size
        while to_write:
            buf = f.read(min(4096, to_write))
            self.f.write(buf)
            to_write -= len(buf)

class FTLDatUnpacker(object):
    """ Class to unpack a FTL .dat file

        >>> unpacker = FTLDatUnpacker(open('data.dat'))
        >>> for i, filename, size, offset in unpacker:
        ...     print filename
        ...     print unpacket.get(filename)
        """
    def __init__(self, f):
        self.index = []      # [idx: offset]
        self.filenames = {}  # {filename: idx}
        self.metadata = []   # [idx: (filename, size, offset)]
        self.f = f
        self._read_index()
    def _read_index(self):
        self.f.seek(0, 0)
        n_entries  = struct.unpack('<L', self.f.read(4))[0]
        for i in xrange(n_entries):
            self.index.append(struct.unpack('<L', self.f.read(4))[0])
            self.metadata.append(None)
        for i, offset in enumerate(self.index):
            if offset == 0:
                continue
            self.f.seek(offset, 0)
            size, l_filename  = struct.unpack('<LL', self.f.read(8))
            filename = self.f.read(l_filename)
            self.metadata[i] = (filename, size, offset+8+l_filename)
            if filename in self.filenames:
                raise FTLDatError("Duplicate filename")
            self.filenames[filename] = i
    def __getitem__(self, filename):
        """ Returns the contents of the file <filename> in a string """
        if not filename in self.filenames:
            raise KeyError
        filename, size, offset = self.metadata[self.filenames[filename]]
        self.f.seek(offset, 0)
        return self.f.read(size)
    def extract_to(self, filename, f):
        """ Extracts the file <filename> to the fileobject <f>. """
        if not filename in self.filenames:
            raise KeyError
        filename, size, offset = self.metadata[self.filenames[filename]]
        self.f.seek(offset, 0)
        to_read = size
        while to_read:
            buf = self.f.read(min(4096, to_read))
            to_read -= len(buf)
            f.write(buf)
    def __iter__(self):
        return itertools.imap(lambda x: (x[0], x[1][0], x[1][1], x[1][2]),
                enumerate(filter(lambda x: x is not None, self.metadata)))

class Program(object):
    def cmd_info(self):
        print 'Loading index ...'
        unpacker = FTLDatUnpacker(self.args.datfile)
        print 
        print "%-4s %-7s %-57s%10s" % ('#', 'offset', 'filename', 'size')
        N = 0
        c_size = 0
        for i, filename, size, offset in unpacker:
            print "%-4s %-7s %-57s%10s" % (i, hex(offset)[2:], filename,
                            str(size) if self.args.bytes else nice_size(size))
            if self.args.hashes:
                class HashFile:
                    def __init__(self): self.h = hashlib.md5()
                    def write(self, s): self.h.update(s)
                    def finish_up(self): return self.h.hexdigest()
                hf = HashFile()
                unpacker.extract_to(filename, hf)
                print "        md5: %s" % hf.finish_up()
            c_size += size
            N += 1
        print
        print '  %s/%s entries' % (N, len(unpacker.index))
        print '  %s' % str(c_size) if self.args.bytes else nice_size(c_size)
    def cmd_pack(self):
        if self.args.folder is None:
            self.args.folder = self.args.datfile.name + '-unpacked'
        print 'Listing files to pack ...'
        s = [()]
        files = []
        while s:
            current = s.pop()
            for child in os.listdir(os.path.join(self.args.folder, *current)):
                full_path = os.path.join(self.args.folder,
                                            *(current + (child,)))
                if os.path.isfile(full_path):
                    files.append(current + (child,))
                elif os.path.isdir(full_path):
                    s.append(current + (child,))
        print 'Create datfile ...'
        if self.args.indexsize is not None:
            indexSize = max(self.args.indexsize, len(files))
        else:
            indexSize = len(files)
        packer = FTLDatPacker(self.args.datfile, indexSize)
        print 'Packing ...'
        for _file in files:
            print ' %s' % '/'.join(_file)
            full_path = os.path.join(self.args.folder, *_file)
            size = os.stat(full_path).st_size
            with open(full_path, 'rb') as f:
                packer.add(ftl_path_join(*_file), f, size)
    def cmd_unpack(self):
        if self.args.folder is None:
            self.args.folder = self.args.datfile.name + '-unpacked'
        print 'Loading index ... '
        unpacker = FTLDatUnpacker(self.args.datfile)
        print 'Extracting ...'
        for i, filename, size, offset in unpacker:
            target = os.path.join(self.args.folder, filename)
            if not os.path.exists(os.path.dirname(target)):
                os.makedirs(os.path.dirname(target))
            if os.path.exists(target) and not self.args.force:
                print 'ERROR %s already exists. Use -f to override.' % target
                return -1
            with open(target, 'wb') as f:
                print ' %s' % filename
                unpacker.extract_to(filename, f)
    def main(self):
        self.parse_args()
        return self.args.func()
    def parse_args(self):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(title='commands',
                                        description='Valid commands')
        parser_info = subparsers.add_parser('info',
                help='Shows the contents of a datfile')
        parser_info.add_argument('datfile',
                type=argparse.FileType('rb'),
                help='The datfile to examine')
        parser_info.add_argument('--hashes', '-H', action='store_true',
                help='Show MD5 hashes')
        parser_info.add_argument('--bytes', '-B', action='store_true',
                help='Show sizes in bytes')
        parser_info.set_defaults(func=self.cmd_info)

        parser_pack = subparsers.add_parser('pack',
                help='Creates a datfile from a folder')
        parser_pack.add_argument('datfile',
                type=argparse.FileType('wb'),
                help="The datfile to create")
        parser_pack.add_argument('folder', nargs='?', default=None,
                help="The folder to pack. Defaults to [datfile]-unpacked")
        parser_pack.add_argument('--indexsize', '-I', default=None, type=int,
                help="Index size.")
        # TODO implement -f
        #parser_pack.add_argument('-f', '--force', action='store_true',
        #        help='Override existing datfile')
        parser_pack.set_defaults(func=self.cmd_pack)

        parser_unpack = subparsers.add_parser('unpack',
                help='Unpacks a datfile to a folder')
        parser_unpack.add_argument('datfile',
                type=argparse.FileType('rb'),
                help="The datfile to unpack")
        parser_unpack.add_argument('folder', nargs='?', default=None,
                help="The folder to extract to. Defaults to [datfile]-unpacked")
        parser_unpack.add_argument('-f', '--force', action='store_true',
                help='Override existing files')
        parser_unpack.set_defaults(func=self.cmd_unpack)

        self.args = parser.parse_args()

def main():
    return Program().main()

if __name__ == '__main__':
    sys.exit(main())
    
# vim: et:sw=4:ts=4:bs=2
