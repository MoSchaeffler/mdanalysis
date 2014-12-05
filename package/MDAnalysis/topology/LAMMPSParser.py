# -*- Mode: python; tab-width: 4; indent-tabs-mode:nil; -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
#
# MDAnalysis --- http://mdanalysis.googlecode.com
# Copyright (c) 2006-2014 Naveen Michaud-Agrawal,
#               Elizabeth J. Denning, Oliver Beckstein,
#               and contributors (see AUTHORS for the full list)
# Released under the GNU Public Licence, v2 or any higher version
#
# Please cite your use of MDAnalysis in published work:
#
#     N. Michaud-Agrawal, E. J. Denning, T. B. Woolf, and
#     O. Beckstein. MDAnalysis: A Toolkit for the Analysis of
#     Molecular Dynamics Simulations. J. Comput. Chem. 32 (2011), 2319--2327,
#     doi:10.1002/jcc.21787
#

"""
LAMMPSParser
============

The :func:`parse` function reads a LAMMPS_ data file to build a system
topology.

.. _LAMMPS: http://lammps.sandia.gov/

Functions and classes
----------------------

.. autofunc:: parse


Deprecated classes
------------------

.. autoclass:: LAMMPSDataConverter
   :members:

"""

import numpy
import logging

from MDAnalysis.core.AtomGroup import Atom
from MDAnalysis.core import util

logger = logging.getLogger("MDAnalysis.topology.LAMMPS")

def _parse_pos(psffile, pos):
    """Strip coordinate info into np array"""
    psffile.next()
    for i in xrange(pos.shape[0]):
        line = psffile.next()
        idx, resid, atype, q, x, y, z = _parse_atom_line(line)
        # assumes atom ids are well behaved?
        # LAMMPS sometimes dumps atoms in random order
        pos[idx] = x, y, z

def _parse_vel(psffile, vel):
    """Strip velocity info into np array"""
    psffile.next()
    for i in xrange(vel.shape[0]):
        line = psffile.next().split()
        idx = int(line[0]) - 1
        vx, vy, vz = map(float, line[1:4])
        vel[idx] = vx, vy, vz

def read_DATA_timestep(ts, datafile):
    """Read a DATA file and try and extract:
      - positions
      - velocities
      - box information

    .. versionadded:: 0.8.2
    """
    read_atoms = False
    read_velocities = False

    with util.openany(datafile, 'r') as psffile:
        nitems, ntypes, box = _parse_header(psffile)

        # lammps box: xlo, xhi, ylo, yhi, zlo, zhi
        lx = box[1] - box[0]
        ly = box[3] - box[2]
        lz = box[5] - box[4]
        # mda unitcell: A alpha B beta gamma C
        ts._unitcell[[0, 1, 2]] = lx, ly, lz
        ts._unitcell[[3, 4, 5]] = 90.0

        while True:
            try:
                section = psffile.next().strip()
            except StopIteration:
                break

            if section == 'Atoms':
                _parse_pos(psffile, ts._pos)
                read_atoms = True
            elif section == 'Velocities':
                ts._velocities = numpy.zeros((ts.numatoms, 3),
                                             dtype=numpy.float32, order='F')
                _parse_vel(psffile, ts._velocities)
                read_velocities = True
            elif len(section) > 0:
                _skip_section(psffile)
            else:
                continue

            if read_atoms & read_velocities:
                break

    if not read_atoms:
        raise IOError("Position information not found")

    return ts

def _parse_section(psffile, nlines, nentries):
    """Read lines and strip information"""
    def zeroint(val):
        """For mapping values to 0 based"""
        return int(val) - 1

    psffile.next()
    section = []
    for i in xrange(nlines):
        line = psffile.next().split()
        # logging.debug("Line is: {}".format(line))
        section.append(tuple(map(zeroint, line[2:2+nentries])))

    return tuple(section)


def _parse_atom_line(line):
    """Parse a atom line into MDA stuff"""
    line = line.split()
    n = len(line)
    # logger.debug('Line length: {}'.format(n))
    # logger.debug('Line is {}'.format(line))
    q = 0.0  # charge is zero by default

    idx, resid, atype = map(int, line[:3])
    idx -= 1  # 0 based atom ids in mda, 1 based in lammps
    if n in [7, 10]:  #atom_style full
        q, x, y, z = map(float, line[3:7])
    elif n in [6, 9]: #atom_style molecular
        x, y, z = map(float, line[3:6])

    return idx, resid, atype, q, x, y, z

def _parse_atoms(psffile, natoms, mass, atom_style):
    """Special parsing for atoms

    Lammps atoms can have lots of different formats, and even custom formats.

    http://lammps.sandia.gov/doc/atom_style.html

    Treated here are
      - atoms with 7 fields (with charge) "full"
      - atoms with 6 fields (no charge) "molecular"
    """
    logger.info("Doing Atoms section")
    atoms = []
    psffile.next()
    for i in xrange(natoms):
        line = psffile.next().strip()
        # logger.debug("Line: {} contains: {}".format(i, line))
        idx, resid, atype, q, x, y, z = _parse_atom_line(line)
        m = mass.get(atype, 0.0)
        # Atom() format:
        # Number, name, type, resname, resid, segid, mass, charge
        atoms.append(Atom(idx, atype, atype,
                          str(resid), resid, str(resid),
                          m, q))

    return atoms

def _parse_masses(psffile, ntypes):
    """Lammps defines mass on a per atom basis.

    This reads mass for each type and stores in dict
    """
    logger.info("Doing Masses section")

    masses = {}

    psffile.next()
    for i in xrange(ntypes):
        line = psffile.next().split()
        masses[int(line[0])] = float(line[1])

    return masses

def _skip_section(psffile):
    """Read lines but don't parse"""
    psffile.next()
    line = psffile.next().split()
    while len(line) != 0:
        try:
            line = psffile.next().split()
        except StopIteration:
            break

    return

def _parse_header(psffile):
    """Parse the header of DATA file

    This should be fixed in all files
    """
    hvals = {'atoms':'_atoms',
             'bonds':'_bonds',
             'angles':'_angles',
             'dihedrals':'_dihe',
             'impropers':'_impr'}
    nitems = {k:0 for k in hvals.values()}

    psffile.next() # Title
    psffile.next() # Blank line

    line = psffile.next().strip()
    while line:
        val, key = line.split()
        nitems[hvals[key]] = int(val)
        line = psffile.next().strip()

    ntypes = {k:0 for k in hvals.values()}
    line = psffile.next().strip()
    while line:
        val, key, _ = line.split()
        ntypes[hvals[key + 's']] = int(val)
        line = psffile.next().strip()

    # Read box information next
    box = numpy.zeros(6, dtype=numpy.float64)
    box[0:2] = psffile.next().split()[:2]
    box[2:4] = psffile.next().split()[:2]
    box[4:6] = psffile.next().split()[:2]
    psffile.next()

    return nitems, ntypes, box

def parse(filename, **kwargs):
    """Parses a LAMMPS_ DATA file.

    The parser implements the `LAMMPS DATA file format`_ but only for
    the LAMMPS `atom_style`_ *full* (numeric ids 7, 10) and
    *molecular* (6, 9).

    :Returns: MDAnalysis internal *structure* dict as defined here.

    .. versionadded:: 0.8.2

    .. _LAMMPS DATA file format: :http://lammps.sandia.gov/doc/2001/data_format.html
    .. _`atom_style`: http://lammps.sandia.gov/doc/atom_style.html
    """
    # Can pass atom_style to help parsing
    atom_style = kwargs.get('atom_style', None)

    # Used this to do data format:
    # http://lammps.sandia.gov/doc/2001/data_format.html
    with util.openany(filename, 'r') as psffile:
        # Check format of file somehow
        structure = {}

        nitems, ntypes, box = _parse_header(psffile)

        strkey = {'Bonds':'_bonds',
                  'Angles':'_angles',
                  'Dihedrals':'_dihe',
                  'Impropers':'_impr'}
        nentries = {'_bonds':2,
                    '_angles':3,
                    '_dihe':4,
                    '_impr':4}
        # Masses can appear after Atoms section.
        # If this happens, this blank dict will be used and all atoms
        # will have zero mass, can fix this later
        masses = {}
        read_masses = False

        # Now go through section by section
        while True:
            try:
                section = psffile.next().strip()
            except StopIteration:
                break

            logger.info("Parsing section '{}'".format(section))
            if section == 'Atoms':
                fix_masses = False if read_masses else True

                structure['_atoms'] = _parse_atoms(psffile, nitems['_atoms'],
                                                   masses, atom_style)
            elif section == 'Masses':
                read_masses = True
                masses = _parse_masses(psffile, ntypes['_atoms'])
            elif section in strkey:  # for sections we use in MDAnalysis
                logger.debug("Doing strkey section for {}".format(section))
                f = strkey[section]
                structure[f] = _parse_section(psffile, nitems[f], nentries[f])
            elif len(section) > 0:  # for sections we don't use in MDAnalysis
                logger.debug("Skipping section, found: {}".format(section))
                _skip_section(psffile)
            else:  # for blank lines
                continue

        if fix_masses:
            for a in structure['_atoms']:
                try:
                    a.mass = masses[a.type]
                except KeyError:  # default mass to 0.0
                    a.mass = 0.0

    return structure

class LAMMPSAtom(object):
    __slots__ = ("index", "name", "type", "chainid", "charge", "mass", "_positions")
    def __init__(self, index, name, type, chain_id, charge=0, mass=1):
        self.index = index
        self.name = repr(type)
        self.type = type
        self.chainid = chain_id
        self.charge = charge
        self.mass = mass
    def __repr__(self):
        return "<LAMMPSAtom "+repr(self.index+1)+ ": name " + repr(self.type) +" of chain "+repr(self.chainid)+">"
    def __cmp__(self, other):
        return cmp(self.index, other.index)
    def __eq__(self, other):
        return self.index == other.index
    def __hash__(self):
        return hash(self.index)
    def __getattr__(self, attr):
        if attr == 'pos':
            return self._positions[self.index]
        else: super(LAMMPSAtom, self).__getattribute__(attr)
    def __iter__(self):
        pos = self.pos
        return iter((self.index+1, self.chainid, self.type, self.charge, self.mass, pos[0], pos[1], pos[2]))


header_keywords= ["atoms","bonds","angles","dihedrals","impropers","atom types","bond types","angle types","dihedral types","improper types","xlo xhi","ylo yhi","zlo zhi"]
connections = dict([["Bonds",("bonds", 3)],["Angles",("angles", 3)],
                    ["Dihedrals",("dihedrals", 4)],["Impropers",("impropers", 2)]])
coeff = dict([["Masses",("atom types", 1)], ["Velocities",("atoms", 3)],
             ["Pair Coeffs",("atom types", 4)],
             ["Bond Coeffs",("bond types", 2)],["Angle Coeffs",("angle types", 4)],
             ["Dihedral Coeffs",("dihedral types", 3)], ["Improper Coeffs",("improper types", 2)]])


def conv_float(l):
    """
    Function to be passed into map or a list comprehension. If the argument is a float it is converted,
    otherwise the original string is passed back
    """
    try:
        n = float(l)
    except ValueError:
        n = l
    return n

class LAMMPSDataConverter(object):
    """Class to parse a LAMMPS_ data file.

    The data file contains both topology and coordinate information.

    The :class:`LAMMPSDataConverter` class can extract topology information and
    coordinates from a LAMMPS_ data file. For instance, in order to
    produce a PSF file of the topology and a PDB file of the coordinates
    from a data file "lammps.data" you can use::

      from MDAnalysis.topology.LAMMPSParser import LAMPPSData
      d = LAMMPSDataConverter("lammps.data")
      d.writePSF("lammps.psf")
      d.writePDB("lammps.pdb")

    You can then read a trajectory (e.g. a LAMMPS DCD, see
    :class:`MDAnalysis.coordinates.LAMMPS.DCDReader`) with ::

      u = MDAnalysis.Unverse("lammps.psf", "lammps.dcd", format="LAMMPS")

    .. deprecated:: 0.8.2

    .. versionchanged:: 0.8.2
       Renamed from ``LAMMPSData`` to ``LAMMPSDataConverter``.
    """
    def __init__(self, filename=None):
        self.names = {}
        self.headers = {}
        self.sections = {}
        if filename == None:
            self.title = "LAMMPS data file"
        else:
            # Open and check validity
            with open(filename, 'r') as file:
                file_iter = file.xreadlines()
                self.title = file_iter.next()
                # Parse headers
                headers = self.headers
                for l in file_iter:
                    line = l.strip()
                    if len(line) == 0: continue
                    found = False
                    for keyword in header_keywords:
                        if line.find(keyword) >= 0:
                            found = True
                            values = line.split()
                            if keyword in ("xlo xhi", "ylo yhi", "zlo zhi"):
                                headers[keyword] = (float(values[0]), float(values[1]))
                            else:
                                headers[keyword] = int(values[0])
                    if found == False: break

            # Parse sections
            # XXX This is a crappy way to do it
            with open(filename, 'r') as file:
                file_iter = file.xreadlines()
                # Create coordinate array
                positions = numpy.zeros((headers['atoms'], 3), numpy.float64)
                sections = self.sections
                for l in file_iter:
                    line = l.strip()
                    if len(line) == 0: continue
                    if coeff.has_key(line):
                        h, numcoeff = coeff[line]
                        # skip line
                        file_iter.next()
                        data = []
                        for i in xrange(headers[h]):
                            fields = file_iter.next().strip().split()
                            data.append(tuple(map(conv_float, fields[1:])))
                        sections[line] = data
                    elif connections.has_key(line):
                        h, numfields = connections[line]
                        # skip line
                        file_iter.next()
                        data = []
                        for i in range(headers[h]):
                            fields = file_iter.next().strip().split()
                            data.append(tuple(map(int, fields[1:])))
                        sections[line] = data
                    elif line == "Atoms":
                        file_iter.next()
                        data = []
                        for i in xrange(headers["atoms"]):
                            fields = file_iter.next().strip().split()
                            index = int(fields[0])-1
                            a = LAMMPSAtom(index=index, name=fields[2], type=int(fields[2]), chain_id=int(fields[1]), charge=float(fields[3]))
                            a._positions = positions
                            data.append(a)
                            positions[index] = numpy.array([float(fields[4]), float(fields[5]), float(fields[6])])
                        sections[line] = data
                    elif line == "Masses":
                        file_iter.next()
                        data = []
                        for i in xrange(headers["atom type"]):
                            fields = file_iter.next().strip().split()
                            print "help"
                self.positions = positions

    def writePSF(self, filename, names=None):
        """Export topology information to a simple PSF file."""
        import string
        # Naveen formatted -- works with MDAnalysis verison 52
        #psf_atom_format = "   %5d %-4s %-4d %-4s %-4s %-4s %10.6f      %7.4f            %1d\n"
        # Liz formatted -- works with MDAnalysis verison 59
        #psf_atom_format = "%8d %4.4s %-4.4s %-4.4s %-4.4s %-4.4s %16.8e %1s %-7.4f %7.7s %s\n"
        # Oli formatted -- works with MDAnalysis verison 81
        psf_atom_format = "%8d %4s %-4s %4s %-4s% 4s %-14.6f%-14.6f%8s\n"
        with open(filename, 'w') as file:
            file.write("PSF\n\n")
            file.write(string.rjust('0', 8) + ' !NTITLE\n\n')
            file.write(string.rjust(str(len(self.sections["Atoms"])), 8) + ' !NATOM\n')
            #print self.sections["Masses"]
            for i, atom in enumerate(self.sections["Atoms"]):
                if names != None: resname, atomname = names[i]
                else: resname, atomname = 'TEMP', 'XXXX'
                for j, liz in enumerate(self.sections["Masses"]):
                        liz = liz[0]
                        #print j+1, atom.type, liz
                        if j+1 == atom.type: line = [i+1, 'TEMP', str(atom.chainid), resname, atomname, str(atom.type+1), atom.charge, float(liz), 0.]
                        else: continue
                #print line
                file.write(psf_atom_format%tuple(line))

            file.write("\n")
            num_bonds = len(self.sections["Bonds"])
            bond_list = self.sections["Bonds"]
            file.write(string.rjust(str(num_bonds), 8) + ' !NBOND\n')
            for index in range(0, num_bonds, 4):
                try:
                    bonds = bond_list[index:index+4]
                except IndexError:
                    bonds = bond_list[index:-1]
                bond_line = map(lambda bond: string.rjust(str(bond[1]), 8)+string.rjust(str(bond[2]), 8), bonds)
                file.write(''.join(bond_line)+'\n')

    def writePDB(self, filename):
        """Export coordinates to a simple PDB file."""
        import string
        atom_format = "%6s%.5s %4s %4s %.4s    %8.3f%8.3f%8.3f%6.2f%6.2f          %2s  \n"
        p = self.positions
        with open(filename, 'w') as file:
            for i, atom in enumerate(self.sections["Atoms"]):
                line = ["ATOM  ", str(i+1), 'XXXX', 'TEMP', str(atom.type+1), p[i,0], p[i,1], p[i,2], 0.0, 0.0, str(atom.type)]
                file.write(atom_format%tuple(line))
