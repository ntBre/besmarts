#!/usr/bin/env python

"""
besmarts.tests.test_enumerate_smiles

"""

from besmarts.codecs.codec_rdkit import graph_codec_rdkit
from besmarts.core.codecs import primitive_key as p
from besmarts.core import graphs

from besmarts.core.enumerate import enumerate_smiles
from besmarts.core.rulesets import visitor_ruleset

atom = (p.ELEMENT, p.HYDROGEN, p.FORMAL_CHARGE, p.VALENCE, p.RING_SMALLEST, p.CONNECTIVITY_RING, p.AROMATIC)
bond = (p.BOND_ORDER,)
gcd = graph_codec_rdkit(atom, bond)

gcd.smiles_config.strip_hydrogen = True

rulesets = [visitor_ruleset(gcd.primitive_codecs)]

for l, smi in enumerate(("CCC",)):

    b = gcd.smiles_decode(smi)
    print(gcd.smiles_encode(b))

    graphs.graph_fill(b)

    for chem in b.nodes.values():
        chem.primitives[p.ELEMENT][:] = False
        chem.primitives[p.ELEMENT][6] = True
        # chem.primitives[p.ELEMENT][7] = True
        # chem.primitives[p.ELEMENT][8] = True
        # chem.primitives[p.ELEMENT][9] = True
        chem.primitives[p.FORMAL_CHARGE][:] = False
        chem.primitives[p.FORMAL_CHARGE][0] = True
        chem.primitives[p.VALENCE][:] = False
        # chem.primitives[p.VALENCE][1:5] = True
        chem.primitives[p.VALENCE][4] = True
        chem.primitives[p.AROMATIC][0] = True
        chem.primitives[p.AROMATIC][1] = False
        chem.primitives[p.RING_SMALLEST][:] = False
        chem.primitives[p.RING_SMALLEST][0] = True
    for chem in b.edges.values():
        chem.primitives[p.BOND_ORDER][:] = False
        chem.primitives[p.BOND_ORDER][1:4] = True


    mols = []
    smis = set()
    print("Input is", gcd.smarts_encode(b))
    for i, P in enumerate(enumerate_smiles(b, rulesets)):
        if P not in mols:
            mols.append(P)
            smi = gcd.smiles_encode(P)
            if smi not in smis:
                smis.add(smi)
                print(f"{len(smis):4d} {smi}")
