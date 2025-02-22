"""
besmarts.core.assignments

Associates BESMARTS structures to data
"""

from typing import List, Dict, Sequence, Tuple, Any
from besmarts.core import graphs, topology, codecs, hierarchies, geometry
import math

assignment_mapping = Dict[str, List[List[Sequence[int]]]]
cartesian_coordinates = List[List[Tuple[float, float, float]]]

POSITIONS = 0
GRADIENTS = 1
HESSIANS = 2
DISTANCES = 3
ANGLES = 4
TORSIONS = 5
OUTOFPLANES = 6
CHARGES = 7
GRID = 8
ESP = 9
RADII = 10

ASSN_NAMES = {
    POSITIONS : "positions",
    GRADIENTS : "gradients",
    HESSIANS : "hessians",
    DISTANCES : "distances",
    ANGLES : "angles",
    TORSIONS : "torsions",
    OUTOFPLANES : "outofplanes",
    CHARGES : "charges",
    GRID : "grid",
    ESP : "esp",
    RADII : "radii",
}

gid_t = int
sid_t = Sequence[int]
aid_t = int
did_t = Sequence

class graph_topology_db_table:
    """
    Holds the data for a db of graphs that all share the same topology.
    """
    def __init__(self, topo, sel):
        self.topology: topology.structure_topology = topo
        self.selection: Dict[gid_t, Dict[sid_t, did_t]] = sel

class graph_topology_db:
    """
    Aggregation of data of various topology with the graphs
    """
    def __init__(self):
        self.graphs: Dict[gid_t, graphs.graph] = {}
        self.gfuncs: Dict[aid_t, graph_topology_db_table] = {}

class smiles_assignment:
    __slots__ = "smiles", "selections"

    def __init__(self, smiles, selections):
        raise NotImplementedError()

    def copy(self):
        return smiles_assignment_copy(self)

    def compute(self, idx: Sequence[int]):
        raise NotImplementedError()


class smiles_assignment_group:
    def __init__(self, assignments, topo):
        self.assignments: List[smiles_assignment] = assignments
        self.topology = topo

    def copy(self):
        return smiles_assignment_group_copy(self)

class graph_assignment(smiles_assignment):
    """
    Assign a subgraph selection some value.
    """

    __slots__ = "smiles", "selections", "graph"

    def __init__(self, smiles, assignments, graph):
        assert type(smiles) is str
        assert type(graph) is graphs.graph
        self.smiles: str = smiles
        self.selections: Dict[Sequence[int], Any] = assignments
        self.graph: graphs.graph = graph

    def copy(self):
        return graph_assignment_copy(self)


class structure_assignment_group(smiles_assignment_group):
    """
    A group of assignments that share the same topology.
    """

    __slots__ = "assignments", "topology"

    def __init__(self, assignments, topo):
        self.assignments: List[graph_assignment] = assignments
        self.topology: topology.structure_topology = topo

    def copy(self):
        return structure_assignment_group_copy(self)


class topology_assignment_group:
    def __init__(self):
        self.topology = None
        self.assignments: List[Dict] = []

class smiles_state:
    def __init__(self):
        self.smiles = ""
        self.assignments: Dict[str, topology_assignment] = {}

class graph_state:
    """
    this keeps track of the observables, e.g.
    state.assignments[POSITIONS][(1,)]
    
    """
    def __init__(self):
        self.smiles = ""
        self.graph = None
        self.assignments: Dict[str, topology_assignment] = {}


class smarts_hierarchy_assignment:
    __slots__ = tuple()

    def assign(
        self,
        shier: hierarchies.smarts_hierarchy,
        gcd: codecs.graph_codec,
        smi: List[str],
        selections,
    ) -> smiles_assignment_group:
        raise NotImplementedError()

    def assign_atoms(
        self,
        shier: hierarchies.smarts_hierarchy,
        gcd: codecs.graph_codec,
        smi: List[str],
    ) -> smiles_assignment_group:
        raise NotImplementedError()

    def assign_bonds(
        self,
        shier: hierarchies.smarts_hierarchy,
        gcd: codecs.graph_codec,
        smi: List[str],
    ) -> smiles_assignment_group:
        raise NotImplementedError()

    def assign_angles(
        self,
        shier: hierarchies.smarts_hierarchy,
        gcd: codecs.graph_codec,
        smi: List[str],
    ) -> smiles_assignment_group:
        raise NotImplementedError()

    def assign_torsions(
        self,
        shier: hierarchies.smarts_hierarchy,
        gcd: codecs.graph_codec,
        smi: List[str],
    ) -> smiles_assignment_group:
        raise NotImplementedError()

    def assign_outofplanes(
        self,
        shier: hierarchies.smarts_hierarchy,
        gcd: codecs.graph_codec,
        smi: List[str],
    ) -> smiles_assignment_group:
        raise NotImplementedError()

class smiles_assignment_float(smiles_assignment):
    __slots__ = "smiles", "selections"

    def __init__(self, smiles, selections):
        self.smiles: str = smiles
        self.selections: Dict[Sequence[int], List[float]] = selections

    def copy(self):
        return smiles_assignment_float_copy(self)

    def compute(self, idx) -> List[float]:
        return smiles_assignment_float_compute(self, idx)

class graph_assignment_float(smiles_assignment):
    __slots__ = "graph", "selections"

    def __init__(self, graph, selections):
        self.graph: str = graph
        self.selections: Dict[Sequence[int], List[float]] = selections

    def copy(self):
        return smiles_assignment_float_copy(self)

    def compute(self, idx) -> List[float]:
        return smiles_assignment_float_compute(self, idx)


# class structure_assignment_float(smiles_assignment):
#     __slots__ = "graph", "selections"

#     def __init__(self, graph, selections):
#         self.graph: str = graph
#         self.selections: Dict[Sequence[int], List[float]] = selections
#         self.topology: topology.structure_topology = None

#     def copy(self):
#         return smiles_assignment_float_copy(self)

#     def compute(self, idx) -> List[float]:
#         return smiles_assignment_float_compute(self, idx)
class smarts_assignment:
    __slots__ = "smarts", "selections"

class smarts_assignment_float(smarts_assignment):
    __slots__ = "smarts", "selections"

class smarts_assignment_str(smarts_assignment):
    __slots__ = "smarts", "selections"

class structure_assignment_str:
    __slots__ = "topology", "selections"

class structure_assignment_float:
    __slots__ = "topology", "selections"
    def __init__(self, topology, selections):
        self.topology = topology
        self.selections = selections

class atom_assignment_float(structure_assignment_float):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.atom
        self.selections = selections

class bond_assignment_float(structure_assignment_float):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.bond
        self.selections = selections

class pair_assignment_float(structure_assignment_float):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.pair
        self.selections = selections

class angle_assignment_float(structure_assignment_float):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.angle
        self.selections = selections

class torsion_assignment_float(structure_assignment_float):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.torsion
        self.selections = selections

class outofplane_assignment_float(structure_assignment_float):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.outofplane
        self.selections = selections

class atom_assignment_str(structure_assignment_str):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.atom
        self.selections = selections

class bond_assignment_str(structure_assignment_str):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.bond
        self.selections = selections

class angle_assignment_str(structure_assignment_str):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.angle
        self.selections = selections

class torsion_assignment_str(structure_assignment_str):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.torsion
        self.selections = selections

class outofplane_assignment_str(structure_assignment_str):
    __slots__ = "topology", "selections"
    def __init__(self, selections):
        self.topology = topology.outofplane
        self.selections = selections

def make_structure_assignment_type(name):
    return type("structure_assignment_"+name, stucture_assignment)

def smiles_assignment_copy(sa: smiles_assignment) -> smiles_assignment:
    smiles = sa.smiles
    selections = sa.selections.copy()

    return smiles_assignment(smiles, selections)


def smiles_assignment_group_concatenate(
    A: smiles_assignment_group, B: smiles_assignment_group
):
    assert A.topology == B.topology
    assn: List[smiles_assignment] = list(A.assignments + B.assignments)
    sag = smiles_assignment_group(assn, A.topology)
    return sag




def smiles_assignment_group_copy(
    sag: smiles_assignment_group,
) -> smiles_assignment_group:
    assignments = [x.copy() for x in sag.assignments]
    topo = sag.topology
    return smiles_assignment_group(assignments, topo)


def smiles_assignment_group_atoms(assignments: List[smiles_assignment]):
    return smiles_assignment_group(assignments, topology.atom_topology())


def smiles_assignment_group_bonds(assignments: List[smiles_assignment]):
    return smiles_assignment_group(assignments, topology.bond_topology())


def smiles_assignment_group_angles(assignments: List[smiles_assignment]):
    return smiles_assignment_group(assignments, topology.angle_topology())


def smiles_assignment_group_torsions(assignments: List[smiles_assignment]):
    return smiles_assignment_group(assignments, topology.torsion_topology())


def smiles_assignment_group_outofplanes(assignments: List[smiles_assignment]):
    return smiles_assignment_group(assignments, topology.outofplane_topology())


def structure_assignment_group_copy(stuag: structure_assignment_group):
    assignments = [graph_assignment_copy(x) for x in stuag.assignments]
    topo = stuag.topology

    return structure_assignment_group(assignments, topo)


def graph_assignment_copy(ga: graph_assignment) -> graph_assignment:
    smiles = ga.smiles
    selections = ga.selections.copy()
    graph = graphs.graph_copy(ga.graph)
    assert type(graph) is graphs.graph

    return graph_assignment(smiles, selections, graph)

def graph_assignment_geometry_position(smiles, graph, confs):
    atoms = graphs.graph_atoms(g)
    selections = {atom: [] for atom in atoms}
    for c in confs:
        for atom in atoms:
            idx = atom[0]
            selections[atom].append(c[idx])

    return graph_assignment(smiles, graph, selections)

def smiles_assignment_geometry_distances(
    pos: smiles_assignment_float,
    indices
) -> bond_assignment_float:

    if indices is None:
        indices = graphs.graph_bonds(pos.graph)

    xyz = pos.selections
    selections = {}

    for bond in indices:
        c1, c2 = bond
        selections[bond] = geometry.measure_distance(xyz[c1,], xyz[c2,])

    return bond_assignment_float(selections)

def smiles_assignment_jacobian_distances(pos, indices) -> smiles_assignment_float:

    xyz = pos.selections
    selections = {}

    for bond in indices:
        c1, c2 = bond
        results = geometry.jacobian_distance(xyz[c1,], xyz[c2,])
        selections[bond] = results

    return bond_assignment_float(selections)

def graph_assignment_jacobian_distances(pos, indices=None) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_bonds(pos.graph)

    return smiles_assignment_jacobian_distances(pos, indices)

def graph_assignment_jacobian_bonds(pos, indices=None) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_bonds(pos.graph)

    return smiles_assignment_jacobian_distances(pos, indices)

def graph_assignment_jacobian_pairs(pos, indices=None) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_pairs(pos.graph)

    return smiles_assignment_jacobian_distances(pos, indices)

def smiles_assignment_geometry_angles(
    pos: smiles_assignment_float,
    indices
) -> angle_assignment_float:

    xyz = pos.selections
    selections = {}

    for angle in indices:
        c1, c2, c3 = angle
        selections[angle] = geometry.measure_angle(xyz[c1,], xyz[c2,], xyz[c3,])

    return angle_assignment_float(selections)

def smiles_assignment_jacobian_angles(
    pos: smiles_assignment_float,
    indices
) -> angle_assignment_float:

    xyz = pos.selections
    selections = {}

    for angle in indices:
        c1, c2, c3 = angle
        selections[angle] = geometry.jacobian_angle(xyz[c1,], xyz[c2,], xyz[c3,])

    return angle_assignment_float(selections)

def graph_assignment_jacobian_angles(
    pos: smiles_assignment_float,
    indices = None
) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_angles(pos.graph)

    return smiles_assignment_jacobian_angles(pos, indices)

def smiles_assignment_jacobian_outofplanes(
    pos: smiles_assignment_float,
    indices
) -> smiles_assignment_float:

    xyz = pos.selections
    selections = {}

    for outofplane in indices:
        c1, c2, c3, c4 = outofplane
        selections[outofplane] = geometry.jacobian_outofplane(xyz[c1,], xyz[c2,], xyz[c3,], xyz[c4,])
            
    return outofplane_assignment_float(selections)

def graph_assignment_jacobian_outofplanes(
    pos: smiles_assignment_float,
    indices = None
) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_outofplanes(pos.graph)

    return smiles_assignment_jacobian_outofplanes(pos, indices)

def smiles_assignment_geometry_outofplanes(
    pos: smiles_assignment_float,
    indices
) -> smiles_assignment:
    x = smiles_assignment_geometry_torsions(pos, indices)
    return outofplane_assignment_float(x.selections)

def smiles_assignment_jacobian_torsions(
    pos: smiles_assignment_float,
    indices
) -> smiles_assignment_float:

    xyz = pos.selections
    selections = {}

    for torsion in indices:
        c1, c2, c3, c4 = torsion
        selections[torsion] = geometry.jacobian_torsion(xyz[c1,], xyz[c2,], xyz[c3,], xyz[c4,])
            
    return torsion_assignment_float(selections)

def graph_assignment_jacobian_torsions(
    pos: smiles_assignment_float,
    indices = None
) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_torsions(pos.graph)

    return smiles_assignment_jacobian_torsions(pos, indices)

def smiles_assignment_geometry_torsions(
    pos: smiles_assignment_float,
    indices
) -> smiles_assignment_float:

    if indices is None:
        indices = graphs.graph_torsions(pos.graph)
    xyz = pos.selections
    selections = {}

    for torsion in indices:
        c1, c2, c3, c4 = torsion
        selections[torsion] = geometry.measure_dihedral(xyz[c1,], xyz[c2,], xyz[c3,], xyz[c4,])
            

    return torsion_assignment_float(selections)


def graph_assignment_geometry_bonds(
    pos: graph_assignment_float,
    indices=None
) -> bond_assignment_float:

    if indices is None:
        indices = graphs.graph_bonds(pos.graph)

    x = smiles_assignment_geometry_distances(pos, indices)
    return bond_assignment_float(x.selections)

def graph_assignment_geometry_pairs(
    pos: graph_assignment_float,
    indices=None
) -> bond_assignment_float:

    if indices is None:
        indices = graphs.graph_pairs(pos.graph)

    x = smiles_assignment_geometry_distances(pos, indices)
    return pair_assignment_float(x.selections)

def graph_assignment_geometry_angles(
    pos: graph_assignment_float,
    indices = None
) -> angle_assignment_float:

    if indices is None:
        indices = graphs.graph_angles(pos.graph)
    return smiles_assignment_geometry_angles(pos, indices)


def graph_assignment_geometry_torsions(
    pos: graph_assignment_float,
    indices = None
) -> torsion_assignment_float:

    if indices is None:
        indices = graphs.graph_torsions(pos.graph)

    xyz = pos.selections
    selections = {}

    for torsion in indices:
        c1, c2, c3, c4 = torsion
        selections[torsion] = geometry.measure_dihedral(xyz[c1,], xyz[c2,], xyz[c3,], xyz[c4,])
            
    return torsion_assignment_float(selections)

def graph_assignment_geometry_outofplanes(
    pos: graph_assignment_float,
    indices = None
) -> outofplane_assignment_float:

    x = graph_assignment_geometry_torsions(pos, indices)
    return outofplane_assignment_float(x.selections)

def graph_assignment_geometry_bonds_v1(
    smiles: str,
    graph: graphs.graph,
    confs: List[List[Tuple[float, float, float]]],
) -> graph_assignment:
    selections = {}

    indices = graphs.graph_bonds(graph)

    lhs = [x[0] for x in indices]
    rhs = [x[1] for x in indices]

    # confs = np.array(confs)

    distances = []
    for c in confs:
        (x0, y0, z0), (x1, y1, z1) = c[lhs], c[rhs]
        r = ((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z0 - z1) ** 2) ** 0.5
        selections[idx].append(r)
        # dist = [ for (x0, y0, z0), (x1, y1, z1) in zip(c[lhs], c[rhs])]
        # distances.append(dist)
    # distances = np.linalg.norm(confs[:, lhs] - confs[:, rhs], axis=2)
    # for idx, d in enumerate(zip(indices, distances)):
    #     selections[idx] = d

    return graph_assignment(smiles, graph, selections)

def smiles_assignment_to_graph_assignment(
    smas: smiles_assignment, gcd
) -> graph_assignment:
    smiles = smas.smiles
    assignments = smas.selections.copy()

    graph = gcd.smiles_decode(smas.smiles)
    graph = graphs.graph(graph.nodes, graph.edges)

    return graph_assignment(smiles, assignments, graph)


def smiles_assignment_group_to_structure_assignment_group(
    smag: smiles_assignment_group, gcd: codecs.graph_codec
) -> structure_assignment_group:
    topo = smag.topology
    gph_assn_list = []

    for assn in smag.assignments:
        gph_assn = smiles_assignment_to_graph_assignment(assn, gcd)
        gph_assn_list.append(gph_assn)

    return structure_assignment_group(gph_assn_list, topo)


def smiles_assignment_group_to_graph_topology_db(sag, aid, gcd) -> graph_topology_db:

    db = graph_topology_db()
    tassn = graph_topology_db_table(sag.topology, {})

    for sa in sag.assignments:
        g = gcd.smiles_decode(sa.smiles)
        gid = graph_topology_db_add_graph(db, g)
        tassn.selections[gid] = sa.selections

    graph_topology_db_add_selection(db, gid, aid, tassn)

    return db

def graph_topology_db_get_graphs(db):
    return db.graphs


def graph_topology_db_iter_values(db):
    kv = {}
    for aid, gassn in db.assignments.items():
        for gid, tassn in gassn.items():
            for sid, data in tassn.selections.items():
                for did, v in enumerate(data):
                    kv[(aid, gid, sid, did)] = v
    return kv


def graph_topology_db_add_graph(db, g) -> gid_t:
    """
    """
    i = len(db.graphs)
    db.graphs[i] = g
    return i


def graph_topology_db_add_selection(db, gid, aid, sel: graph_topology_db_table):

    assert gid in db.graphs

    if aid not in db.assignments:
        db.assignments[aid] = {}
    db.assignments[aid][gid] = sel


def graph_topology_db_add_positions(db, gid, sel: graph_topology_db_table):

    assert sel.topology == topology.atom

    for sid, data in sel.selections.items():
        for xyz in data:
            assert len(xyz) == 3

    return graph_topology_dbs_add_selection(db, gid, POSITIONS, sel)


def db_graph_position_assignment(nids, confs):
    tassn = graph_topology_db_table()
    tassn.topology = topology.atom
    tassn.selections.update({nid: xyz for nid, xyz in zip(nids, confs)})
    return tassn
    

def graph_topology_db_add_gradients(db, gid, sel: graph_topology_db_table):

    assert sel.topology == topology.atom

    for sid, data in sel.selections.items():
        for xyz in data:
            assert len(xyz) == 3

    return graph_topology_dbs_add_selection(db, gid, GRADIENTS, sel)


def graph_topology_db_add_hessians(db, gid, sel: graph_topology_db_table):

    assert sel.topology == topology.pair

    for sid, data in sel.selections.items():
        for xyz2 in data:
            assert len(xyz2) == 9

    return graph_topology_dbs_add_selection(db, gid, HESSIANS, sel)


def graph_topology_db_add_distances(db, gid, sel: graph_topology_db_table):

    assert sel.topology == topology.pair

    for sid, data in sel.selections.items():
        data: Sequence[float]
        assert all((type(d) is float for d in data))

    return graph_topology_dbs_add_selection(db, gid, DISTANCES, sel)
