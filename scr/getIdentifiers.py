from collections import OrderedDict
import pubchempy as pcp
import time
import json
import sys
import os
import re

from molecule import moleculeEncoder
from molecule import moleculeDecoder
from molecule import Molecule
import myExceptions
import utils
import IO


def run(dbsConfig):
    nArgs = len(sys.argv)
    if nArgs < 4:
        raise myExceptions.ArgError(4, nArgs)

    # flsFile = sys.argv[2]
    fieFile = sys.argv[2]
    cidSmilesFile = sys.argv[3]

    isomers = IO.readFieFile(fieFile)
    # molecules = IO.readFlsFile(flsFile, isomers)
    molecules = getMolecules(isomers)

    print('Canonicalizing SMILES')
    canonicalizeSmiles(molecules)
    # this will take a while
    cidSmiles = IO.readCiDSmilesFile(cidSmilesFile)

    data = OrderedDict()
    # check if json/pickle file exists
    # molDataFile = 'out/enuMolData.json'
    molDataFile = dbsConfig.getOutFileName('enuDataFile')
    if os.path.exists(molDataFile):
        with open(molDataFile) as jsonFile:
            data = json.load(jsonFile, object_hook=moleculeDecoder)

    print('Downloading Molecules')
    if cidSmiles.shape[0] != 0:
        matchMol(cidSmiles, molecules, data, molDataFile)
    else:
        downloadMol(molecules, data, molDataFile)


def getMolecules(isomers):
    molecules = []
    for idx, row in isomers.iterrows():
        smiles = row['smiles']
        form = row['frm']
        nam = row['nam']

        mol = Molecule(smiles, '', nam, '', 0, [], 0, '')
        mol.form = form
        molecules.append(mol)

    return molecules


def canonicalizeSmiles(molecules):
    for mol in molecules:
        smiles = mol.smiles
        smiles = utils.getCanonicalSmiles(smiles)
        mol.smiles = smiles


# get idenfier from already downloaded file
#  there is higher chance of matching identifiers because both smiles are canonicalized with RDKit
def matchMol(cidSmiles, molecules, data, molDataFile):
    # wait 1 sec after searching for 5 molecules
    count = 0
    for mol in molecules:
        code = mol.enu_code
        smiles = mol.smiles

        if smiles in data:
            print('\t{} ({}) already included'.format(code, smiles))
            continue

        print(mol)

        cid_pcp = cidSmiles[cidSmiles['smiles'] == smiles]['cid']

        if cid_pcp.shape[0] == 1:
            cid_pcp = cid_pcp.values[0]
            cid_pcp = str(cid_pcp)
            mol_pcp = pcp.get_compounds(cid_pcp, 'cid')

            if len(mol_pcp) == 0:
                continue
            if len(mol_pcp) != 1:
                print('More than 1 match for: {} {}'.format(mol_pcp, smiles))
                sys.exit(1)

            mol_pcp = mol_pcp[0]
            if mol_pcp.cid is None:
                continue

            getPcpData(mol_pcp, smiles, mol, data, molDataFile)

            count += 1
            if count % 5 == 0:
                time.sleep(1)

        # sys.exit(123)


def downloadMol(molecules, data, molDataFile):
    # wait 1 sec after searching for 5 molecules
    count = 0

    for mol in molecules:
        code = mol.enu_code
        smiles = mol.smiles

        # canonicalize smiles with RDKit
        smiles = utils.getCanonicalSmiles(smiles)
        mol.smiles = smiles

        if smiles in data:
            print('\t{} ({}) already included'.format(code, smiles))
            continue

        print(mol)

        mol_pcp = pcp.get_compounds(smiles, 'smiles')
        if len(mol_pcp) == 0:
            continue
        if len(mol_pcp) != 1:
            print('More than 1 match for: {} {}'.format(mol_pcp, smiles))
            sys.exit(1)

        mol_pcp = mol_pcp[0]
        if mol_pcp.cid is None:
            continue

        getPcpData(mol_pcp, smiles, mol, data, molDataFile)

        count += 1
        if count % 5 == 0:
            time.sleep(1)


def getPcpData(mol_pcp, smiles, mol, data, molDataFile):
    name = mol_pcp.iupac_name

    if not name:
        name = getFirstSynonym(mol_pcp)

    match = compare(mol, mol_pcp)
    if not match:
        return
    add_other_names(mol, mol_pcp)

    data[smiles] = mol
    # save data to json file
    with open(molDataFile, 'w') as out:
        json.dump(data, out, cls=moleculeEncoder, indent=2)
    # sys.exit(123)


def getFirstSynonym(mol_pcp):
    name = mol_pcp.synonyms
    if len(name) != 0:
        name = name[0]
        name = name.lower()
    else:
        name = 'TODO'
    return name


def compare(mol, mol_pcp):
    cid_pcp = mol_pcp.cid
    inchi_pcp = mol_pcp.inchikey

    name_pcp = mol_pcp.iupac_name
    if not name_pcp:
        name_pcp = getFirstSynonym(mol_pcp)

    form_pcp = mol_pcp.molecular_formula

    # print(mol_pcp.cid)
    smiles_match = match_smiles(mol.smiles, mol_pcp.canonical_smiles)
    if not smiles_match:
        return False

    formula_match = match_formula(mol.form, form_pcp)
    if not formula_match:
        return False

    mol.cid_pcp = cid_pcp
    mol.inchi_pcp = inchi_pcp
    mol.name_pcp = name_pcp
    mol.form_pcp = form_pcp

    cas = get_cas_pcp(cid_pcp)
    mol.cas = cas

    print('\t{} {} {}'.format(mol.name_pcp, mol.cas, mol_pcp.cid))
    return True


def match_smiles(reference, smiles):
    if reference != smiles:
        smiles = utils.getCanonicalSmiles(smiles)
        if reference != smiles:
            print('Smiles do not match: {} != {}'.format(reference, smiles))
            # sys.exit(123)
            return False

    return True


def match_formula(reference, formula):
    s1 = re.findall(r'([A-Z][a-z]*)(\d*)', reference)

    # for alcohol with formula Cx{OH}yHz
    # tmp = re.findall(r'([A-Z][a-z]*)(\d*)', reference)
    # nO = 3
    # s = 'C{}H{}O{}'.format(tmp[0][1], int(tmp[3][1]) + nO * int(tmp[2][1]), nO)
    # s1 = re.findall(r'([A-Z][a-z]*)(\d*)', s)

    s2 = re.findall(r'([A-Z][a-z]*)(\d*)', formula)

    for i in range(len(s1)):
        s1[i] = (s1[i][0].encode(), s1[i][1].encode())
        if not s1[i][1]:
            s1[i] = (s1[i][0], '1'.encode())

    for i in range(len(s2)):
        s2[i] = (s2[i][0].encode(), s2[i][1].encode())
        if not s2[i][1]:
            s2[i] = (s2[i][0], '1'.encode())

    s1 = sorted(s1)
    s2 = sorted(s2)

    if len(s1) != len(s2):
        print('\tFormulas do not match: {} {}'.format(reference, formula))
        return False

    for i in range(len(s1)):
        if s1[i] != s2[i]:
            print(s1[i], s2[i])
            print('\tFormulas do not match: {} {}'.format(reference, formula))
            return False

    return True


def get_cas_pcp(cid):
    results = pcp.get_synonyms(cid, 'cid')
    for result in results:
        for syn in result.get('Synonym', []):
            match = re.match('(\d{2,7}-\d\d-\d)', syn)
            if match:
                cas = match.group(1)
                return cas
    return ''


def add_other_names(mol, mol_pcp):
    names = ['allowed_name', 'cas_like_style_name', 'systematic_name', 'traditional_name']
    for n in names:
        try:
            method_to_call = getattr(mol_pcp, n)
            result = method_to_call
            mol.add_other_name(result)
        except AttributeError:
            continue
