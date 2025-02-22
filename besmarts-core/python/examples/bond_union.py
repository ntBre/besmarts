
"""
Example of combining the bond graphs of propane into a single pattern.

pypy can be used to approximately half the runtime needed for this example.
However, pypy can only be used when rdkit is not used. To do this, make sure all
graphs are decoded and saved first, then load them using the native load function
in this example.
"""

from besmarts.codecs import codec_native
from besmarts.core import graphs
from besmarts.core import mapper
from besmarts.core import configs

# load the default native graph codec. It can encode SMARTS/SMILES
codecs = codec_native.primitive_codecs_get()
atom_primitives = list(codec_native.primitive_codecs_get_atom())
bond_primitives = list(codec_native.primitive_codecs_get_bond())
gcd = codec_native.graph_codec_native(codecs, atom_primitives, bond_primitives)


# load in a pre-decoded propane graph
G = codec_native.graph_codec_native_load("propane.bg")[0]
bonds = graphs.graph_to_structure_bonds(G)


# default depth is 0, so it will only union the primary atoms (i.e. the bond)
U = mapper.union_list(bonds)
graphs.structure_print(U)
print(gcd.smarts_encode(U))


# extend the bonds to include the immediate neighbors
cfg = configs.smarts_extender_config(1, 1, True)
graphs.structure_extend(cfg, bonds)
U = mapper.union_list(bonds)
graphs.structure_print(U)
print(gcd.smarts_encode(U))

