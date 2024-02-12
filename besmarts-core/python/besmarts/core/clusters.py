"""
besmarts.core.clusters

Associates a SMARTS hierarchy to a dataset group (of assignments)
"""

import os
import sys
import pickle
import datetime
import collections
import multiprocessing.pool
import threading
import time
from typing import Dict, Sequence, Tuple, List
import heapq

from besmarts.core import (
    codecs,
    configs,
    mapper,
    graphs,
    hierarchies,
    assignments,
    optimization,
    trees,
    tree_iterators,
    splits,
    compute,
    arrays,
)
from besmarts.cluster import cluster_assignment


class smarts_clustering:
    __slots__ = "hierarchy", "group", "mappings", "group_prefix_str"

    def __init__(self, structure_hierarchy, assign_group, mappings):
        # this is the SMARTS hierarchy
        self.hierarchy: hierarchies.structure_hierarchy = structure_hierarchy

        # this will be the labeling of the structures
        self.group: assignments.smiles_assignment_group = assign_group

        # this is the structures grouped by the labels
        self.mappings: assignments.assignment_mapping = mappings

        # when new nodes are created, use this prefix
        self.group_prefix_str = "p"


class clustering_objective:
    def split(self, A, B) -> float:
        raise NotImplementedError()

    def merge(self, A, B) -> float:
        raise NotImplementedError()

    def single(self, A) -> float:
        raise NotImplementedError()

    def report(self, A) -> str:
        raise NotImplementedError()

    def is_discrete(self) -> bool:
        raise NotImplementedError()

    def sum(self) -> bool:
        raise NotImplementedError()


def objective_total(hidx, groups, objective):
    X = 0.0
    for s in hidx.index.nodes.values():
        X += objective.single(groups[s.name])
    return X


def get_objective(cst, assn, objfn, edits, splitting=True):
    hidx = cst.hierarchy
    new_match = cst.mappings
    keep = True
    obj = 0.0
    X = 0.0
    for n in tree_iterators.tree_iter_dive(
        hidx.index, trees.tree_index_roots(hidx.index)
    ):
        m = hidx.index.above.get(n.index, None)
        if m is not None:
            m = hidx.index.nodes[m]
            n_match = new_match[n.name]
            m_match = new_match[m.name]
            # if not (n_match and m_match):
            #     keep = False
            #     print(f"RETURNING FALSE1 because {n_match} {m_match}")
            #     continue
            n_group = tuple(((assn[i] for i in n_match)))
            m_group = tuple(((assn[i] for i in m_match)))
            # print(f"Objective for Sj: {sma}")
            obj = objfn(n_group, m_group, overlap=edits)
            if False and splitting:
                if obj >= 0.0:
                    keep = False
                # print(f"Object increased to {obj} for {n.name} parent {m.name}")
                # continue
            X += obj
    return keep, X


class find_successful_candidates_ctx:
    candidates = None
    pq = None
    group_number = None
    step = None
    hidx = None
    topology = None
    labeler = None
    Sj_sma = None
    groups = None
    assn = None
    strategy = None
    gcd = None
    objective = None


class shm_find_successful_candidates(compute.shm_local):
    def __init__(self, cst, sag, gcd, labeler, objective):
        self.cst = cst
        self.sag = sag
        self.gcd = gcd
        self.labeler = labeler
        self.objective = objective

    def remote_init(self):
        return shm_find_successful_candidates_init


def shm_find_successful_candidates_init(
    shm_proxy: shm_find_successful_candidates,
):
    data = shm_proxy.get()
    shm = shm_find_successful_candidates(
        data["cst"],
        data["sag"],
        data["gcd"],
        data["labeler"],
        data["objective"],
    )
    return shm


def find_successful_candidates_distributed(S, Sj, operation, edits, shm=None):
    sag = shm.sag
    cst = shm.cst
    hidx = cst.hierarchy.copy()
    labeler = shm.labeler
    gcd = shm.gcd

    objective = shm.objective

    smiles = [a.smiles for a in sag.assignments]
    topo = hidx.topology
    assn = shm.assn # get_assns(sag.assignments, topo)

    obj = edits
    X = edits

    # (S, Sj, step, _, _, _, _) = candidates[key]
    # (edits, _, p_j) = key
    param_name = "pX"
    sma = ""
    added = False
    dX = 0.0

    if operation == optimization.optimization_strategy.SPLIT:
        # param_name = "p" + str(group_number)

        # print(datetime.datetime.now(), '*** 2')
        hent = hidx.index.node_add(
            S.index,
            trees.tree_node(None, "parameter", "", param_name),
            index=0,
        )
        # print(datetime.datetime.now(), '*** 3')
        Sj = graphs.subgraph_relabel_nodes(
            Sj, {n: i for i, n in enumerate(Sj.select, 1)}
        )
        Sj = graphs.subgraph_to_structure(Sj, topo)

        # sma = Sj_sma[cnd_i] #gcd.smarts_encode(Sj)

        hidx.subgraphs[hent.index] = Sj
        hidx.smarts[hent.index] = shm.gcd.smarts_encode(graphs.subgraph_as_structure(Sj, topo))

        # print(datetime.datetime.now(), '*** 4')
        new_assignments = labeler.assign(hidx, gcd, smiles, topo)

        # print(datetime.datetime.now(), '*** 5')
        new_match = clustering_build_assignment_mappings(hidx, new_assignments)

        cst = smarts_clustering(hidx, new_assignments, new_match)

        # print(datetime.datetime.now(), '*** 6')
        groups = clustering_build_ordinal_mappings(cst, sag, [S.name, hent.name])

        if not (groups[S.name] and groups[hent.name]):
            keep = False
            _, X = get_objective(
                cst, assn, objective.split, edits, splitting=True
            )
        else:
            obj = objective.split(groups[S.name], groups[hent.name], overlap=edits)
            # print(datetime.datetime.now(), '*** 7')
            keep, X = get_objective(
                cst, assn, objective.split, edits, splitting=True
            )
            # dX = X - X
            # if dX > 0:
            #     keep = False
            if obj > 0.0:
                keep = False

            if not (cst.mappings[S.name] and cst.mappings[hent.name]):
                keep = False

            # keep the splits that match the most (general)
            # match_len = len(cst.mappings[S.name])
            
            # keep the splits that match the least (specific)
            # this is better since it leaves more in S, so more can be split
            # at a time
        match_len = len(cst.mappings[hent.name])

        return keep, X, obj, match_len

        # print(datetime.datetime.now(), '*** 8')
    elif operation == optimization.optimization_strategy.MERGE:

        hent = Sj
        # print(datetime.datetime.now(), '*** 8')
        groups = clustering_build_ordinal_mappings(cst, sag, [S.name, hent.name])
        if (S.name not in groups) or (Sj.name not in groups):
            return False, 0.0, 0.0, 0
        obj = 0.0
        obj = objective.merge(groups[S.name], groups[hent.name], overlap=edits)
        trees.tree_index_node_remove(hidx.index, Sj.index)
        # print(datetime.datetime.now(), '*** 9')
        new_assignments = labeler.assign(hidx, gcd, smiles, topo)
        # print(datetime.datetime.now(), '*** 10')
        new_match = clustering_build_assignment_mappings(hidx, new_assignments)
        cst = smarts_clustering(hidx, new_assignments, new_match)
        # print(datetime.datetime.now(), '*** 11')
        _, X = get_objective(cst, assn, objective.split, edits, splitting=False)
        # Sj = hidx.subgraphs[Sj.index]
        # cst.hierarchy.subgraphs.pop(hent.index)
        # cst.hierarchy.smarts.pop(hent.index)
        # sma = Sj_sma[cnd_i-1]
        keep = obj < 0 or len(groups[hent.name]) == 0

        match_len = len(cst.mappings[S.name])

        return keep, X, obj, match_len
    else:
        return False, 0.0, 0.0, 0

def perform_operations(
        hidx: hierarchies.structure_hierarchy,
        candidates,
        keys,
        group_number,
        Sj_sma,
        strategy,
    ):

    # candidates = find_successful_candidates_ctx.candidates
    # pq = find_successful_candidates_ctx.pq
    # x, key = pq[cnd_i]
    # group_number = find_successful_candidates_ctx.group_number
    # step = find_successful_candidates_ctx.step
    # Sj_sma = find_successful_candidates_ctx.Sj_sma
    # labeler = find_successful_candidates_ctx.labeler

    # hidx = cst.hierarchy
    # strategy = find_successful_candidates_ctx.strategy
    # smiles = find_successful_candidates_ctx.smiles
    # objective = find_successful_candidates_ctx.objective
    # topo = find_successful_candidates_ctx.topology
    # obj = 0.0
    # keep = True
    # dX = 0.0

    topo = hidx.topology

    nodes = []
    for cnd_i, key in keys.items():
        (S, Sj, step, _, _, _, _) = candidates[key]
        (edits, _, p_j) = key
        param_name = "p."
        sma = ""
        added = False

        if step.operation == strategy.SPLIT:
            param_name = "p" + str(group_number)

            # print(datetime.datetime.now(), '*** 2')
            hent = hidx.index.node_add(
                S.index,
                trees.tree_node(None, "parameter", "", param_name),
                index=0,
            )
            # print(datetime.datetime.now(), '*** 3')
            Sj = graphs.subgraph_relabel_nodes(
                Sj, {n: i for i, n in enumerate(Sj.select, 1)}
            )
            Sj = graphs.subgraph_to_structure(Sj, topo)

            sma = Sj_sma[cnd_i-1]  # gcd.smarts_encode(Sj)

            hidx.subgraphs[hent.index] = Sj
            hidx.smarts[hent.index] = sma
            nodes.append(hent)

            group_number += 1

            # print(datetime.datetime.now(), '*** 4')

            #####
        elif step.operation == strategy.MERGE:
            # if (S.name not in groups) or (Sj.name not in groups):
            #     continue

            hent = Sj
            nodes.append(hent)
            # obj += objective.merge(groups[S.name], groups[hent.name], overlap=edits)
            trees.tree_index_node_remove(hidx.index, Sj.index)

            hidx.subgraphs.pop(hent.index)
            hidx.smarts.pop(hent.index)

        


        # procs = configs.processors
        # configs.processors = 1
        # new_assignments = labeler.assign(hidx, gcd, smiles, topo)
        # configs.processors = procs

        # print(datetime.datetime.now(), '*** 5')
        # new_match = clustering_build_assignment_mappings(hidx, new_assignments)

        # cst = smarts_clustering(hidx, new_assignments, new_match)
    return hidx, nodes


def find_successful_candidates(cnd_i, key, return_hier=False):
    candidates = find_successful_candidates_ctx.candidates
    # pq = find_successful_candidates_ctx.pq
    # x, key = pq[cnd_i]
    group_number = find_successful_candidates_ctx.group_number
    # step = find_successful_candidates_ctx.step
    Sj_sma = find_successful_candidates_ctx.Sj_sma
    labeler = find_successful_candidates_ctx.labeler
    groups = find_successful_candidates_ctx.groups
    assn = find_successful_candidates_ctx.assn
    hidx = find_successful_candidates_ctx.hidx.copy()
    strategy = find_successful_candidates_ctx.strategy
    gcd = find_successful_candidates_ctx.gcd
    smiles = find_successful_candidates_ctx.smiles
    objective = find_successful_candidates_ctx.objective
    # topo = find_successful_candidates_ctx.topology

    topo = hidx.topology

    (S, Sj, step, _, _, _, _) = candidates[key]
    (edits, _, p_j) = key
    param_name = "p."
    sma = ""
    added = False
    dX = 0.0

    if step.operation == strategy.SPLIT:
        param_name = "p" + str(group_number)

        # print(datetime.datetime.now(), '*** 2')
        hent = hidx.index.node_add(
            S.index,
            trees.tree_node(None, "parameter", "", param_name),
            index=0,
        )
        # print(datetime.datetime.now(), '*** 3')
        Sj = graphs.subgraph_relabel_nodes(
            Sj, {n: i for i, n in enumerate(Sj.select, 1)}
        )
        Sj = graphs.subgraph_to_structure(Sj, topo)

        sma = Sj_sma[cnd_i]  # gcd.smarts_encode(Sj)

        hidx.subgraphs[hent.index] = Sj
        hidx.smarts[hent.index] = sma

        # print(datetime.datetime.now(), '*** 4')
        procs = configs.processors
        configs.processors = 1
        new_assignments = labeler.assign(hidx, gcd, smiles, topo)
        configs.processors = procs

        # print(datetime.datetime.now(), '*** 5')
        new_match = clustering_build_assignment_mappings(hidx, new_assignments)

        cst = smarts_clustering(hidx, new_assignments, new_match)

        # print(datetime.datetime.now(), '*** 7')
        keep, X = get_objective(
            cst, assn, objective.split, edits, splitting=True
        )
        # dX = X - X
        # if dX > 0:
        #     keep = False
        if not (cst.mappings[S.name] and cst.mappings[hent.name]):
            keep = False

        match_len = len(cst.mappings[hent.name])
        return_cst = None
        if return_hier:
            return_cst = (cst, hent)

        return keep, X, 0.0, match_len, return_cst

        # print(datetime.datetime.now(), '*** 8')
    elif step.operation == strategy.MERGE:
        if (S.name not in groups) or (Sj.name not in groups):
            return False, 0.0, 0.0, 0, (None, None)

        hent = Sj
        obj = objective.merge(groups[S.name], groups[hent.name], overlap=edits)
        trees.tree_index_node_remove(hidx.index, Sj.index)
        procs = configs.processors
        configs.processors = 1
        new_assignments = labeler.assign(hidx, gcd, smiles, topo)
        configs.processors = procs
        new_match = clustering_build_assignment_mappings(hidx, new_assignments)
        cst = smarts_clustering(hidx, new_assignments, new_match)
        _, X = get_objective(cst, assn, objective.split, edits, splitting=False)
        # Sj = hidx.subgraphs[Sj.index]
        cst.hierarchy.subgraphs.pop(hent.index)
        cst.hierarchy.smarts.pop(hent.index)
        # sma = Sj_sma[cnd_i-1]
        keep = True
        if obj >= 0:
            keep = False
        match_len = len(cst.mappings[S.name])

        return_cst = None
        if return_hier:
            return_cst = (cst, hent)
        return keep, X, obj, match_len, return_cst
    else:
        return False, 0.0, 0.0, 0, (None, None)


def check_lbls_data_selections_equal(
    lbls: assignments.smiles_assignment_group,
    data: assignments.smiles_assignment_group,
):
    # check if there as many labeled ICs to data points.
    warning_max = 10
    warnings = 0
    for idx, (lbl_assn, data_assn) in enumerate(
        zip(lbls.assignments, data.assignments)
    ):
        assert lbl_assn.smiles == data_assn.smiles
        for lbl_ic in lbl_assn.selections:
            if lbl_ic not in data_assn.selections:
                if warnings < warning_max:
                    print(
                        f"WARNING: mol {idx} atoms {lbl_ic} does not have data! This will likely fail."
                    )
                    print(f"WARNING:     SMILES: {lbl_assn.smiles}")
                warnings += 1
    if warnings > warning_max:
        print(
            f"WARNING: suppressed {warnings - warning_max} additional warnings"
        )

def smarts_clustering_optimize_binary_merge():
    "Fit each molecule individually and iteratively merge results"
    
    pass

def forcefield_optimize(
    gcd: codecs.graph_codec,
    labeler: assignments.smarts_hierarchy_assignment,
    confs: assignments.smiles_assignment_group,
    objective: clustering_objective,
    strategy: optimization.optimization_strategy,
    initial_conditions: smarts_clustering,
) -> smarts_clustering:
    pass
    """
    need sag to be conformations
    then i need a sag to compute a new assignment
    energy 
    energy(cst sag (confs))
    sag
    sag.compute(sag, cst)
    tree should be a FF
    ff should be a cluster, but then also have parameters
    """

def smarts_clustering_optimize(
    gcd: codecs.graph_codec,
    labeler: assignments.smarts_hierarchy_assignment,
    sag: assignments.smiles_assignment_group,
    objective: clustering_objective,
    strategy: optimization.optimization_strategy,
    initial_conditions: smarts_clustering,
) -> smarts_clustering:


    started = datetime.datetime.now()

    smiles = [a.smiles for a in sag.assignments]

    topo = sag.topology

    group_prefix_str = initial_conditions.group_prefix_str

    hidx = initial_conditions.hierarchy.copy()

    groups = clustering_build_ordinal_mappings(initial_conditions, sag)
    # print(groups)

    # match = clustering_build_assignment_mappings(initial_conditions, initial_conditions.group)
    match = initial_conditions.mappings
    assn = get_assns(sag.assignments, topo)

    icd = codecs.intvec_codec(gcd.primitive_codecs, gcd.atom_primitives, gcd.bond_primitives)


    check_lbls_data_selections_equal(initial_conditions.group, sag)

    """
    nomenclature

    match is node_name:data_idx (mol, ic)
    assn is data_idx:data
    group is node_name:data
    mapping node_name:data_idx
    """

    group_number = max(
        [
            int(x.name[1:])
            for x in hidx.index.nodes.values()
            if x.name[0] == group_prefix_str
        ]
    )

    group_number += 1

    if len(sag.assignments) > 100000:
        batch_size = 10000
        print(f"{datetime.datetime.now()} Large number of graphs detected... using a workspace")
        wq = compute.workqueue_local('', configs.workqueue_port)
        ws = compute.workqueue_new_workspace(wq, address=('127.0.0.1', 0), shm={"gcd": gcd})

        work = compute.workspace_submit_and_flush(
            ws,
            codecs.smiles_decode_list_distributed,
            {i: ((list(e),), {}) for i, e in enumerate(arrays.batched((s.smiles for s in sag.assignments), batch_size))},
            chunksize=10
        )
        
        # A = {}
        # A = {}
        G0 = {}
        n_ics = 0
        for ii in sorted(work):
            i = 0
            for i, ig in enumerate(work[ii], ii*batch_size):
                G0[i] = ig
                # g = icd.graph_decode(ig)
                sels = sag.assignments[i].selections
                # print()
                # print(sag.assignments[i].smiles)
                # print(gcd.smiles_encode(gcd.smiles_decode(sag.assignments[i].smiles)))
                # print(g.nodes.keys())
                # print(sels)
                # for si in sels:
                #     if si[0] not in g.nodes:
                #         breakpoint()
                n_ics += len(sels)
                # for s in sels:
                #     # A[(i, tuple((s[j] for j in topo.primary)))] = sg
                #     A[(i, tuple((s[j] for j in topo.primary)))] = tuple((s[j] for j in topo.primary))
                #     n_ics += 1
            print(f"\r{datetime.datetime.now()} graphs= {i+1:8d}/{len(sag.assignments)} subgraphs= {n_ics:8d}", end="")
        print()
            
            
        # ws.close()
        threading.Thread(target=ws.close).start()
        ws = None

        wq.close()
        wq = None  

    else:

        G0 = {i: icd.graph_encode(gcd.smiles_decode(a.smiles)) for i, a in enumerate(sag.assignments)}
        n_ics = sum((len(s.selections) for s in sag.assignments))
        # A = {
        #     (i, tuple((s[j] for j in topo.primary))): tuple((s[j] for j in topo.primary))
        #     for i, y in enumerate(sag.assignments)
        #     for s in y.selections
        #     #     y.selections,
        #     #     graphs.graph_to_subgraphs(
        #     #         gcd.smiles_decode(y.smiles), y.selections
        #     #     ),
        #     # )
        # }

    N = len(hidx.index.nodes)
    try:
        N = len(set(assn.values()))
    except Exception:
        pass

    repeat = set()
    visited = set()
    iteration = 1
    N_str = "{:" + str(len(str(n_ics))) + "d}"

    success = False

    roots = trees.tree_index_roots(hidx.index)

    print(f"{datetime.datetime.now()} Labeling subgraphs")
    assignments = labeler.assign(hidx, gcd, smiles, topo)
    cst = smarts_clustering(
        hidx,
        assignments,
        clustering_build_assignment_mappings(hidx, assignments),
    )
    print(f"{datetime.datetime.now()} Checking consistency...")
    check_lbls_data_selections_equal(cst.group, sag)
    _, X0 = get_objective(
        cst, assn, objective.split, strategy.overlaps[0], splitting=True
    )


    if not strategy.steps:
        print("Optimization strategy is building steps...")
        strategy.build_steps()
    print(f"{datetime.datetime.now()} The optimization strategy has the following iterations:")
    for ma_i, macro in enumerate(strategy.steps, 1):
        cur = "  "
        if ma_i == strategy.cursor + 1:
            cur = "->"
        for mi_i, micro in enumerate(macro.steps):
            s = micro.pcp.splitter
            a = micro.overlap
            b0 = s.bit_search_min
            b1 = s.bit_search_limit
            d0 = s.branch_depth_min
            d1 = s.branch_depth_limit
            n0 = s.branch_min
            n1 = s.branch_limit
            print(
                f"{cur} {ma_i:3d}. op={micro.operation:2d} a={a} b={b0}->{b1} d={d0}->{d1} n={n0}->{n1}"
            )

    # if not strategy.step_tracker and strategy.cursor > -1:
    #     strategy.step_tracker.update({
    #         x.name: strategy.cursor+1 for x in strategy.tree_iterator(hidx.index, roots)
    #     })
    step_tracker = strategy.step_tracker

    while True:
        if success:
            print("Restarting optimization search")
            strategy = optimization.optimization_strategy_restart(strategy)
            success = False

        elif optimization.optimization_strategy_is_done(strategy):
            print("Nothing found. Done.")
            break

        groups = clustering_build_ordinal_mappings(cst, sag)

        roots = trees.tree_index_roots(cst.hierarchy.index)
        nodes = [
            x
            for x in strategy.tree_iterator(cst.hierarchy.index, roots)
            if strategy.cursor == -1
            or strategy.cursor >= step_tracker.get(x.name, 0)
        ]

        print(f"Targets for this macro step {strategy.cursor+1}:")
        for nidx, n in enumerate(nodes, 1):
            print(nidx, n.name)
        print(f"N Targets: {len(nodes)}")

        print(f"Step tracker for current macro step {strategy.cursor+1}")
        for n, v in step_tracker.items():
            print(n, v + 1)

        macro: optimization.optimization_iteration = strategy.macro_iteration(
            nodes
        )

        candidates = {}
        pq = []
        n_added = 0
        n_macro = len(strategy.steps)

        t = datetime.datetime.now()
        config = strategy.bounds
        spg = "Y" if config.splitter.split_general else "N"
        sps = "Y" if config.splitter.split_specific else "N"
        print(
            f"\n\n*******************\n {t}"
            f" iteration={iteration:4d}"
            f" macro={strategy.cursor:3d}/{n_macro}"
            f" X={X0:9.5g}"
            f" params=({len(cst.mappings)}|{N})"
            f" G={spg}"
            f" S={sps}"
            f" bits={config.splitter.bit_search_min}->{config.splitter.bit_search_limit}"
            f" depth={config.splitter.branch_depth_min}->{config.splitter.branch_depth_limit}"
            f" branch={config.splitter.branch_min}->{config.splitter.branch_limit}"
        )
        print(f"*******************")
        print()
        print("Tree:")
        for ei, e in enumerate(
            tree_iterators.tree_iter_dive(
                cst.hierarchy.index, trees.tree_index_roots(cst.hierarchy.index)
            )
        ):
            s = trees.tree_index_node_depth(cst.hierarchy.index, e)
            obj_repo = ""
            # if groups[e.name]:
            obj_repo = objective.report(groups[e.name])
            print(
                f"** {s:2d} {ei:3d} {e.name:4s}",
                obj_repo,
                cst.hierarchy.smarts.get(e.index),
            )
        print("=====\n")

        print(f"{datetime.datetime.now()} Saving checkpoint to chk.cst.p")
        pickle.dump([sag, cst, strategy], open("chk.cst.p", "wb"))

        

        step = None

        while not optimization.optimization_iteration_is_done(macro):
            t = datetime.datetime.now()
            print(f"{t} Initializing new loop on macro {strategy.cursor}")
            step: optimization.optimization_step = (
                optimization.optimization_iteration_next(macro)
            )

            n_micro = len(macro.steps)
            config: configs.smarts_perception_config = step.pcp
            S = step.cluster
            S0 = graphs.subgraph_to_structure(
                cst.hierarchy.subgraphs[S.index], topo
            )

            cfg = config.extender.copy()
            if graphs.structure_max_depth(S0) > config.extender.depth_max:
                continue

            S0_depth = graphs.structure_max_depth(S0)
            d = max(S0_depth, config.splitter.branch_depth_limit)
            # print("Depth is", d)
            cfg.depth_max = d
            cfg.depth_min = S0_depth

            t = datetime.datetime.now()
            print(
                f"{t} Collecting SMARTS for {S.name} N={len(cst.mappings[S.name])}/{n_ics} and setting to depth={S0_depth}"
            )
            # a = clustering_collect_structures(
            #     A, cst.mappings[S.name], topo, cfg
            # )
            aa = cst.mappings[S.name]
            selected_graphs = set((x[0] for x in aa))
            G = {k:v for k,v in G0.items() if k in selected_graphs}
            del selected_graphs

            assn_s = {i: assn[i] for i in cst.mappings[S.name]}

            iteration += 1

            # X = objective_total(hidx, groups, objective)
            # if X == 0.0:
            #     break

            # _, X0 = get_objective(cst, assn, objective.split, 0)

            t = datetime.datetime.now()
            print(
                f" =="
                f" iteration={iteration:4d}"
                f" macro={strategy.cursor:3d}/{n_macro}"
                f" micro={macro.cursor:3d}/{n_micro}"
                # f" overlap={strategy.overlaps:3d}"
                f" operation={step.operation}"
                f" params=({len(cst.mappings)}|{N})"
                f" cluster={S.name:4s}"
                f" N= " + N_str.format(len(aa)) + ""
                f" overlap={step.overlap}"
                f" bits={config.splitter.bit_search_min}->{config.splitter.bit_search_limit}"
                f" depth={config.splitter.branch_depth_min}->{config.splitter.branch_depth_limit}"
                f" branch={config.splitter.branch_min}->{config.splitter.branch_limit}"
            )
            print()

            if step.operation == strategy.SPLIT:
                new_pq = []
                new_candidates = {}
                new_candidates_direct = {}
                direct_success = False

                print(f"Attempting to split {S.name}:")
                print("S0:", gcd.smarts_encode(S0))



                if not assn_s:
                    print("No matches.")
                    step_tracker[S.name] = strategy.cursor
                    continue

                print(f"Matched N={len(assn_s)}")
                seen = set()
                for seen_i, (i, x) in enumerate(assn_s.items(), 1):
                    if seen_i > 100:
                        break
                    g = graphs.graph_to_structure(icd.graph_decode(G[i[0]]), i[1], topo) 
                    # if g not in seen:
                    print(
                        f"{seen_i:06d} {str(i):24s}",
                        objective.report([x]),
                        gcd.smarts_encode(g),
                    )
                    # seen.add(g)
                print()

                if objective.single(assn_s.values()) == 0.0:
                    print(f"Skipping {S.name} due to no objective")
                    step_tracker[S.name] = strategy.cursor
                    continue


                if (
                    step.direct_enable
                ):  # and config.splitter.bit_search_limit > 2:
                    assn_i = []
                    if objective.is_discrete():
                        assn_i.extend(groups[S.name])
                    else:
                        # or form matches based on unique smarts
                        assert False
                        lbls = set(a)
                        if len(lbls) < step.direct_limit:
                            lbls = dict()
                            for (i, idx), sg in a.items():
                                lbl_i = lbls.get(a, len(lbls))
                                lbls[a] = lbl_i
                                assn_i.append(lbl_i)

                    if len(set(assn_i)) < step.direct_limit:
                        assert False
                        pcp = step.pcp.copy()
                        pcp.extender = cfg
                        print("Direct splitting....")
                        # pcp.extender.depth_max = pcp.splitter
                        # pcp.extender.depth_min = strategy.bounds.extender.depth_min
                        ret = splits.split_all_partitions(
                            topo,
                            pcp,
                            list(a.values()),
                            assn_i,
                            gcd=gcd,
                            maxmoves=0,
                        )

                        for p_j, (Sj, Sj0, matches, unmatches) in enumerate(ret.value, 0):
                            # Sj = mapper.intersection(Sj, S0, config=configs.mapper_config(3, 1, "high"))
                            print(f"Found {p_j+1}")

                            edits = 0
                            matches = [
                                y
                                for x, y in enumerate(aa)
                                if x in matches
                            ]
                            unmatches = [
                                y
                                for x, y in enumerate(aa)
                                if x in unmatches
                            ]
                            matched_assn = tuple((assn[i] for i in matches))
                            unmatch_assn = tuple((assn[i] for i in unmatches))

                            new_candidates_direct[(step.overlap[0], None, p_j)] = (
                                S,
                                Sj,
                                step,
                                matches,
                                unmatches,
                                matched_assn,
                                unmatch_assn,
                            )
                        if len(new_candidates_direct):
                            direct_success = True
                        else:
                            print("Direct found nothing")


                if step.iterative_enable: #and not direct_success:
                    # Q = mapper.union_list_parallel(
                    #     list(a.values()),
                    #     reference=S0,
                    #     max_depth=graphs.structure_max_depth(S0),
                    #     icd=icd if len(a) > 100000 else None
                    # )
                    Q = mapper.union_list_parallel(
                        G, aa, topo,
                        # list(a.values()),
                        reference=S0,
                        max_depth=graphs.structure_max_depth(S0),
                        icd=icd
                        # icd=icd if len(a) > 100000 else None
                    )
                    # print(f"{datetime.datetime.now()} STOPPING")
                    # time.sleep(1.0)
                    # print(f"{datetime.datetime.now()} DELETING")
                    # del Q
                    # time.sleep(1.0)
                    # print(f"{datetime.datetime.now()} GARBAGE")
                    # gc.collect()
                    # time.sleep(1.0)
                    # print(f"{datetime.datetime.now()} KILLING")
                    # time.sleep(1.0)
                    # assert False
                    t = datetime.datetime.now()
                    print(f"{t} Union is {gcd.smarts_encode(Q)}")

                    # ret = splits.split_structures(
                    #     config.splitter, S0, list(a.values()), Q=Q
                    # )
                    return_matches = config.splitter.return_matches
                    config.splitter.return_matches = True
                    # ret = splits.split_structures_distributed(
                    #     config.splitter,
                    #     S0,
                    #     list(a.values()),
                    #     compute.workqueue_local("", configs.workqueue_port),
                    #     Q=Q,
                    # )
                    ret = splits.split_structures_distributed(
                        config.splitter,
                        S0,
                        G,
                        aa,
                        compute.workqueue_local("", configs.workqueue_port),
                        icd,
                        Q=Q,
                    )
                    config.splitter.return_matches = return_matches

                    backmap = {i: j for i, j in enumerate(cst.mappings[S.name])}
                    print(
                        f"{datetime.datetime.now()} Collecting new candidates"
                    )
                    new_candidates = clustering_collect_split_candidates_serial(
                        S, ret, step
                    )
                    # new_candidates = clustering_collect_split_candidates_parallel(
                    #     S, a, ret, backmap, assn, step
                    # )
                    # new_candidates = clustering_collect_split_candidates_distributed(
                    #     S, a, ret, backmap, assn, step, compute.workqueue_local('', configs.workqueue_port)
                    # )

                # print(f"{datetime.datetime.now()} Organizing new candidates")
                # new_pq, new_candidates = clustering_insert_split_candidates(
                #     new_candidates, assn, objective, S, macro.cursor
                # )

                # print(f"{datetime.datetime.now()} Inserting new candidates")
                # pq.extend(new_pq)
                # pq = sorted(pq)
                # new_pq.clear()

                p_j_max = -1
                if candidates:
                    p_j_max = max(x[2] for x in candidates) + 1
                for k, v in new_candidates.items():
                    k = (k[0], k[1], k[2]+p_j_max)
                    candidates[k] = v
                # candidates.update(new_candidates)
                new_candidates.clear()

                p_j_max = -1
                if candidates:
                    p_j_max = max(x[2] for x in candidates) + 1
                for k, v in new_candidates_direct.items():
                    k = (k[0], k[1], k[2]+p_j_max)
                    candidates[k] = v
                # candidates.update(new_candidates)
                new_candidates_direct.clear()

            elif step.operation == strategy.MERGE:
                # if len(aa) == 1:
                #     step_tracker[S.name] = strategy.cursor
                #     continue

                for p_j, jidx in enumerate(cst.hierarchy.index.below[S.index]):
                    J = cst.hierarchy.index.nodes[jidx]
                    # if (
                    #     objective.single([assn[i] for i in cst.mappings[J.name]])
                    #     == 0.0
                    # ):
                    #     continue
                    for overlap in step.overlap:
                        # obj = objective.merge(
                        #     groups[S.name], groups[J.name], overlap=overlap
                        # )
                        key = (overlap, macro.cursor, p_j)
                        # matched = tuple(
                        #     list(cst.mappings[S.name]) + list(cst.mappings[J.name])
                        # )
                        # Sj = hidx.subgraphs[J.index]
                        cnd = (S, J, step, None, None, None, None)
                        # pq.append((obj, key))
                        candidates[key] = cnd
                        # print("MERGE", matched, "obj", obj)
                # pq = sorted(pq)

        # if accept_max is None:
        #     for n, v in step_tracker.items():
        #         if v < macro_i:
        #             print(f"Setting tracker for {n} to {macro_i}")
        #             step_tracker[n] = macro_i

        if step is None:
            print(
                f"{datetime.datetime.now()} Warning, this macro step had no micro steps"
            )
            continue

        print(f"{datetime.datetime.now()} Scanning done.")

        print(datetime.datetime.now())
        print(f"\n\nGenerating SMARTS on {len(candidates)}")
        Sj_sma = []

        with multiprocessing.pool.Pool(configs.processors) as pool:
            if step.operation == strategy.SPLIT:
                # Sj_lst = [candidates[x[1]][1] for x in pq]
                Sj_lst = [graphs.subgraph_as_structure(x[1], topo) for x in candidates.values()]
            elif step.operation == strategy.MERGE:
                Sj_lst = [
                    graphs.subgraph_as_structure(cst.hierarchy.subgraphs[x[1].index], topo)
                    for x in candidates.values()
                ]
            Sj_sma = pool.map_async(gcd.smarts_encode, Sj_lst).get()
            del Sj_lst

        # header = False
        # pq_uniq = []
        # sma_uniq = []

        # for cnd_i, (x, key) in enumerate(pq, 0):
        #     # if x >= 0.0:
        #     #     continue
        #     if not header:
        #         t = datetime.datetime.now()
        #         print(f"\n\n{t} Candidates from estimated objectives:")
        #         header = True
        #     (S, Sj, step, _, _, _, _) = candidates[key]
        #     if step.operation == strategy.MERGE:
        #         Sj = cst.hierarchy.subgraphs[Sj.index]
        #     sma = Sj_sma[cnd_i]

        #     if sma not in sma_uniq:
        #         pq_uniq.append((x, key))
        #         print(f" > {len(pq_uniq):4d} {x:10.5f}", step.operation, f"Parent: {S.name}", sma)
        #         sma_uniq.append(sma)
        #     else:
        #         # for some reason the hash is letting the same SMARTS through
        #         # more than once... clear it here
        #         candidates.pop(key)

        # Sj_sma = sma_uniq
        # pq_uniq = pq

        print(f"{datetime.datetime.now()} Labeling")
        cur_assignments = labeler.assign(cst.hierarchy, gcd, smiles, topo)
        print(f"{datetime.datetime.now()} Rebuilding assignments")
        cur_mappings = clustering_build_assignment_mappings(
            cst.hierarchy, cur_assignments
        )
        cur_cst = smarts_clustering(
            cst.hierarchy.copy(), cur_assignments, cur_mappings
        )
        print(f"{datetime.datetime.now()} Rebuilding mappings")
        groups = clustering_build_ordinal_mappings(cur_cst, sag)
        check_lbls_data_selections_equal(cst.group, sag)

        cnd_n = len(candidates)

        # pq = [x for x in pq if x[0] < strategy.filter_above]
        t = datetime.datetime.now()
        # print(f"{t} Searching {len(pq)}/{cnd_n} promising parameters for operation below {strategy.filter_above}")

        # cnd_n = len(pq)

        print("Tree:")
        for ei, e in enumerate(
            tree_iterators.tree_iter_dive(
                cur_cst.hierarchy.index,
                trees.tree_index_roots(cur_cst.hierarchy.index),
            )
        ):
            s = trees.tree_index_node_depth(cur_cst.hierarchy.index, e)
            obj_repo = ""
            # if groups[e.name]:
            obj_repo = objective.report(groups[e.name])
            print(
                f"** {s:2d} {ei:3d} {e.name:4s}",
                obj_repo,
                cur_cst.hierarchy.smarts.get(e.index),
            )
        print("=====\n")

        visited.clear()
        repeat.clear()

        find_successful_candidates_ctx.labeler = labeler
        # find_successful_candidates_ctx.pq = pq
        find_successful_candidates_ctx.candidates = candidates
        find_successful_candidates_ctx.hidx = cur_cst.hierarchy.copy()
        # find_successful_candidates_ctx.hidx = cur_cst.hierarchy.topology
        find_successful_candidates_ctx.step = step
        find_successful_candidates_ctx.group_number = group_number
        find_successful_candidates_ctx.Sj_sma = Sj_sma
        find_successful_candidates_ctx.groups = groups
        find_successful_candidates_ctx.assn = assn
        find_successful_candidates_ctx.strategy = strategy
        find_successful_candidates_ctx.gcd = gcd
        find_successful_candidates_ctx.smiles = smiles
        find_successful_candidates_ctx.objective = objective

        pq_idx = 0
        procs = (
            os.cpu_count() if configs.processors is None else configs.processors
        )

        # Here starts the phase where we have all splits, and we need to determine
        # which ones to keep. Theoretically we should relabel each time, but for these
        # nanosteps we will try to determine which to keep. We have some potential
        # to how we handle nanoiterations:
        # - n total, n per param
        # - nonoverlapping
        # However big problem is that we dont want to return 

        # how about we just accept one per parent, that might be the best
        # we already have the groups of base, so just track it that way?


        # for each split, manually manipulate the groups, assuming that 
        # that all that still split are valid, we call this as greedy
        # as possible
        
        # we have groups and cur_cst to grab our candidates.

        # we will need to sort them somehow, but we can add one per parent
        # no problem but we will want to sort them somehow
        
        """
        for cnd in sorted_candidates:
            determine local obj/keep
            if keep,
                modify groups

        """

        # print(datetime.datetime.now(), f"Batching {pq_idx+1} to {len(pq)} with chunk= {procs}")
        # batches = mapper.batched(range(pq_idx, len(pq)), procs)
        # added = False
        # for batch in batches:
        # if added:
        #     break
        # find_successful_candidates_ctx.group_number = group_number
        # find_successful_candidates_ctx.cur_cst = cur_cst

        # best = []
        # with multiprocessing.pool.Pool(configs.processors) as pool:
        #     work = []

        # added = False
        # while pq_idx < len(pq):

        n_keep = None
        # if strategy.accept_max > 0 and n_added == strategy.accept_max:
        #     strategy.repeat_step()
        print(f"Scanning {len(candidates)} candidates for operations")

        macroamt = strategy.macro_accept_max_total
        macroampc = strategy.macro_accept_max_per_cluster

        cnd_n = len(candidates)
        n_added = 0
        added = True
        kept = set()
        macro_count = collections.Counter()
        ignore = set()
        reuse = {}
        wq = compute.workqueue_local("", configs.workqueue_port)
        print(f"{datetime.datetime.now()} workqueue started on {wq.mgr.address}")
        n_nano = 0
        while added:

            case1 = macroamt == 0 or n_added < macroamt
            case2 = macroampc == 0 or all([x < macroampc for x in macro_count.values()])
            if not (case1 and case2):
                break

            n_nano += 1

            added = False
            best = {}

            cout = {}
            cout_sorted_keys = []

            shm = compute.shm_local(1, data={"cst": cur_cst, "sag": sag, "gcd": gcd, "labeler": labeler, "objective": objective, "assn": assn}) 

            iterable = {
                i: ((S, Sj, step.operation, edits), {})
                for i, (
                    (edits, _, p_j),
                    (S, Sj, step, _, _, _, _),
                ) in enumerate(candidates.items(), 1) 
            }


            chunksize = 10

            if n_ics > 100000000:
                procs = max(1, procs // 10)
            elif n_ics > 50000000:
                procs = max(1, procs // 5)
            elif n_ics > 10000000:
                procs = max(1, procs // 3)
            elif n_ics > 5000000:
                procs = max(1, procs // 2)
            if n_ics > len(candidates)*10:
                shm.procs_per_task = 0
                chunksize = 1

            addr = ("", 0)
            if len(iterable) <= procs:
                addr = ('127.0.0.1', 0)
                procs=len(iterable)

            ws = compute.workqueue_new_workspace(wq, address=addr, nproc=procs, shm=shm)

            cnd_keys = {i: k for i, k in enumerate(candidates, 1)}

            for k in kept:
                if k in iterable:
                    iterable.pop(k)

            for k in ignore:
                if k in iterable:
                    iterable.pop(k)

            for k in reuse:
                if k in iterable:
                    iterable.pop(k)

            for k, v in list(candidates.items()):
                S = v[0]
                if S.name in cur_cst.mappings:
                    if objective.single([assn[i] for i in cur_cst.mappings[S.name]]) == 0.0:
                        if k in iterable:
                            iterable.pop(k)
                elif k in iterable:
                    iterable.pop(k)

            work = compute.workspace_submit_and_flush(
                ws,
                find_successful_candidates_distributed,
                iterable,
                chunksize,
                1.0,
                len(iterable),
            )

            threading.Thread(target=ws.close).start()
            ws = None


            print(f"The unfiltered results of the candidate scan N={len(work)} total={len(iterable)}:")

            max_line = 0


            best_reuse = None
            if reuse:
                # just append the best to work and let the loop figure it out
                best_reuse = sorted(reuse.items(), key=lambda y: (-y[1][0], y[1][1], y[1][2], y[1][3]))[0]
                work[best_reuse[0]] = best_reuse[1]
            for j, cnd_i in enumerate(sorted(work), 1):
                (keep, X, obj, match_len) = work[cnd_i]
                # cnd_i, key, unit = unit
                (S, Sj, step, _, _, _, _) = candidates[cnd_keys[cnd_i]]

                if step.operation == strategy.SPLIT:
                    visited.add(S.name)
                elif step.operation == strategy.MERGE:
                    visited.add(Sj.name)

                dX = X - X0
                reused_line = ""
                if best_reuse is not None and cnd_i == best_reuse[0]:
                    reused_line="*"
                C = "Y" if keep else "N"
                cout_line = (
                    f"Cnd. {cnd_i:4d}/{len(work)}"
                    f" {S.name:6s} {reused_line}" 
                    f" X= {X:10.5f}"
                    f" dX= {dX:10.5f} N= {match_len:6d} C= {C} {Sj_sma[cnd_i-1]}"
                )
                max_line = max(len(cout_line), max_line)
                # print(datetime.datetime.now())
                print('\r' + cout_line, end=" " * (max_line - len(cout_line)))
                sys.stdout.flush()
                # find_successful_candidates_ctx.group_number = group_number
                # find_successful_candidates_ctx.groups = groups
                # find_successful_candidates_ctx.hidx = cur_cst.hierarchy.copy()
                # key = cnd_keys[cnd_i]
                # keep, X, obj, match_len, (cst, hent) = find_successful_candidates(
                #     cnd_i - 1, key, return_hier=True
                # )

                # _groups = clustering_build_ordinal_mappings(cst, sag)
                # print("Tree:")
                # for ei, e in enumerate(
                #     tree_iterators.tree_iter_dive(
                #         cst.hierarchy.index,
                #         trees.tree_index_roots(cst.hierarchy.index),
                #     )
                # ):
                #     s = trees.tree_index_node_depth(cst.hierarchy.index, e)
                #     obj_repo = ""
                #     if _groups[e.name]:
                #         obj_repo = objective.report(_groups[e.name])
                #     print(
                #         f"** {s:2d} {ei:3d} {e.name:4s}",
                #         obj_repo,
                #         cst.hierarchy.smarts.get(e.index),
                #     )
                # print("=====\n")

                # print(f"Obj: {X}")
                # print(
                #     f"Parameter {j:4d}/{len(work)}",
                #     f"New Obj {X:10.5f}",
                #     f"dObj: {dX:10.5f} Constraints: {keep}", Sj_sma[cnd_i],
                # )

                if match_len == 0:
                    if step.operation == strategy.SPLIT:
                        keep = False
                        ignore.add(cnd_i)
                        continue

                if not keep:
                    ignore.add(cnd_i)
                    continue


                if cnd_i in kept:
                    ignore.add(cnd_i)
                    continue


                # We prefer to add in this order
                cout_key = None

                # print sorted at the end but only for new
                # this is to speed things up
                cout_key = (-int(keep), X, match_len, cnd_i, S.name)
                cout[cout_key] = cout_line

                # use these below to determine the best ones to keep
                heapq.heappush(cout_sorted_keys, cout_key)

                # if best.get(S.name, None) is None:
                #     # best = cnd_i, key, keep, X, obj, cst, hent, match_len
                #     best[S.name] = heapq.heapify([cout_key])
                #     # best_count[S.name] = 1
                #     print()

                # elif cnd_i not in kept:
                #     if X < best[S.name][2]:
                #         best[S.name] = cnd_i, keep, X, obj, match_len

                #         print()
                #     elif X == best[S.name][2] and match_len < best[S.name][4]:
                #         best[S.name] = cnd_i, keep, X, obj, match_len
                #         print()
                # elif cnd_i in kept:
                # # else:
                #     ignore.add(cnd_i)

            print("\r" + " " * max_line)

            # if best:
            #     for name, v in best.items():
            #         kept.add(v[0])
            #     added = True
            # else:
            #     break

            # print sorted at the end
            print(f"Nanostep {n_nano}: The filtered results of the candidate scan N={len(cout)} total={len(iterable)}:")
            ck_i = 1

            cnd_keep = []
            best_params = [x[0] for x in best.values()]
            macroamt = strategy.macro_accept_max_total
            macroampc = strategy.macro_accept_max_per_cluster
            microamt = strategy.micro_accept_max_total
            microampc = strategy.micro_accept_max_per_cluster
            micro_added = 0
            micro_count = collections.Counter()
            while len(cout_sorted_keys):
                ck = heapq.heappop(cout_sorted_keys)

                keeping = "  "

                dX = ck[1] - X0
                case0 = not (strategy.filter_above is not None and strategy.filter_above < dX)

                if case0:
                    ignore.add(ck[0])

                case1 = macroamt == 0 or n_added < macroamt
                case2 = microamt == 0 or micro_added < microamt
                if case0 and case1 and case2:
                    sname = ck[4]
                    case3 = macroampc == 0 or macro_count[sname] < macroampc
                    case4 = microampc == 0 or micro_count[sname] < microampc
                    if case3 and case4:
                        cnd_keep.append(ck)
                        micro_count[sname] += 1
                        macro_count[sname] += 1
                        micro_added += 1
                        n_added += 1
                # if ck[3] in best_params:
                        keeping = "->"
                        kept.add(ck[0])
                print(f"{keeping} {ck_i:4d}", cout[ck])
                ck_i += 1
            ck = None

            # keys = {x[0]: cnd_keys[x[0]] for x in best.values()}
            keys = {x[3]: cnd_keys[x[3]] for x in cnd_keep}

            print(f"Performing {len(keys)} operations")
            hidx, nodes = perform_operations(
                cur_cst.hierarchy,
                candidates,
                keys,
                group_number,
                Sj_sma,
                strategy
            )

            print(f"There are {len(nodes)} nodes returned")

            print("Operations per parameter for this micro:")
            print(micro_count)
            print(f"Micro total: {sum(micro_count.values())} should be {micro_added}")

            print("Operations per parameter for this macro:")
            print(macro_count)
            print(f"Macro total: {sum(macro_count.values())} should be {n_added}")

            if len(nodes) == 0:
                added = False
                continue

            new_assignments = labeler.assign(hidx, gcd, smiles, topo)
            # print(datetime.datetime.now(), '*** 5')
            new_match = clustering_build_assignment_mappings(hidx, new_assignments)

            cst = smarts_clustering(hidx, new_assignments, new_match)

            groups = clustering_build_ordinal_mappings(cst, sag)

            # print(datetime.datetime.now(), f"Batching {pq_idx+1} to {len(pq)} with chunk= {procs}")
            # batches = mapper.batched(range(pq_idx, len(pq)), procs)
            # added = False
            # for batch in batches:
            #     if added:
            #         break
            #     with multiprocessing.pool.Pool(configs.processors) as pool:
            #         work = []

            #         for cnd_i in batch:
            #             work.append(pool.apply_async(find_successful_candidates, (cnd_i,)))
            #         # work = [unit.get() for unit in work]
            #         for unit in work:
            # cnd_i, keep, X, obj, match_len = best
            # if False:
            #     key = cnd_keys[cnd_i]

            #     # print("Calculating using", cnd_i, keep, X, obj, match_len, key)
            #     print("\nBest candidate is")
            #     cout_key = (-int(keep), X, match_len, cnd_i)
            #     print(cout[cout_key], Sj_sma[cnd_i-1])
            #     print(f"{datetime.datetime.now()} Calculating new hierarchy...")
            #     find_successful_candidates_ctx.group_number = group_number
            #     find_successful_candidates_ctx.groups = groups
            #     find_successful_candidates_ctx.hidx = cur_cst.hierarchy.copy()
            #     keep, X, obj, match_len, (cst, hent) = find_successful_candidates(
            #         cnd_i - 1, key, return_hier=True
            #     )

            #     cout.clear()
            #     dX = X - X0

            #     if not keep:
            #         print(f"{datetime.datetime.now()} Failed. Trying next")
            #         reuse.update(work)
            #         continue
            #     else:

            #         print(f"{datetime.datetime.now()} Success.")
            #         # do this to reevaluate current reuse since work is just
            #         # the subset we calculated
            #         work.update(reuse)
            #         reuse.clear()
            #         # iterate through and find which ones didn't change
            #         for k, (cnd_j, v) in enumerate(work.items(), 1):
            #             # assume we can't "swap" so checking len should work
            #             # (S, Sj, step, _, _, _, _) = candidates[cnd_keys[cnd_i]]
            #             S_old = candidates[cnd_keys[cnd_j]][0]
            #             if len(cur_cst.mappings[S_old.name]) == len(cst.mappings[S_old.name]):
            #                 # update the objective
            #                 reuse[cnd_j] = (v[0], v[1] + dX, v[2], v[3])
            #             else:
            #                 print(f"{k:4d} {cnd_j:4d} {S_old.name} Previous match = {len(cur_cst.mappings[S_old.name])} Current match = {len(cst.mappings[S_old.name])}")
            #         print(f"Reusing {len(reuse)}/{len(work)} calculations")

            #     work.clear()


            # sma = Sj_sma[cnd_i - 1]
            # print("Returned", cnd_i, keep, X, obj, match_len, (hent.index, hent.name), sma)

            # (x, key) = pq[cnd_i]
            # (S, Sj, step, _, _, _, _) = candidates[key]
            # pq_idx = cnd_i+1
            # visited.add(S.name)
            # edits, _, p_j = key

            success = True
            added = True
            
            group_number += len(keys)
            _, X = get_objective(cst, assn, objective.split, step.overlap[0], splitting=False)
            dX = X-X0

            for (cnd_i, key), hent in zip(keys.items(), nodes):
                (S, Sj, step, _, _, _, _) = candidates[key]
                repeat.add(S.name)
                sma = Sj_sma[cnd_i-1]
                kept.add(cnd_i)
                # cnd_i = best[S.name][0] 
                # hent = Sj
                visited.add(hent.name)
                edits = step.overlap[0]

                if step.operation == strategy.SPLIT:

                    obj = edits
                    if groups[S.name] and groups[hent.name]:
                        obj = objective.split(
                            groups[S.name], groups[hent.name], overlap=edits
                        )

                    print(
                        f"\n>>>>> New parameter {cnd_i:4d}/{cnd_n}",
                        hent.name,
                        "parent",
                        S.name,
                        "Objective",
                        f"{X:10.5f}",
                        "Delta",
                        f"{dX:10.5f}",
                        f"Partition {len(cst.mappings[S.name])}|{len(cst.mappings[hent.name])}",
                    )
                    print(" >>>>>", key, f"Local dObj {obj:10.5f}", sma, end="\n\n")

                    repeat.add(hent.name)
                    step_tracker[hent.name] = 0


                elif step.operation == strategy.MERGE:

                    if hent.name in step_tracker:
                        step_tracker.pop(hent.name)
                    else:
                        print("WARNING", hent.name, "missing from the tracker")

                    visited.add(S.name)
                    visited.remove(hent.name)

                    above = cst.hierarchy.index.above.get(S.index)
                    if above is not None:
                        repeat.add(cst.hierarchy.index.nodes[above].name)

                    print(
                        f">>>>> Delete parameter {cnd_i:4d}/{cnd_n}",
                        hent.name,
                        "parent",
                        S.name,
                        "Objective",
                        f"{X:10.5f}",
                        "Delta",
                        f"{dX:10.5f}",
                    )
                    print(" >>>>>", key, f"Local dObj {obj:10.5f}", sma, end="\n\n")

            for ei, e in enumerate(
                tree_iterators.tree_iter_dive(
                    cst.hierarchy.index,
                    trees.tree_index_roots(cst.hierarchy.index),
                )
            ):
                s = trees.tree_index_node_depth(cst.hierarchy.index, e)
                obj_repo = ""
                # if groups[e.name]:
                obj_repo = objective.report(groups[e.name])
                print(
                    f"** {s:2d} {ei:3d} {e.name:4s}",
                    obj_repo,
                    cst.hierarchy.smarts.get(e.index),
                )

            mod_lbls = cluster_assignment.smiles_assignment_str_modified(
                cur_cst.group.assignments, cst.group.assignments
            )
            repeat.update(mod_lbls)
            cur_cst = cst
            cst = None
            X0 = X
            # n_added += 1
            # print(f"Accepted {n_added}/{strategy.accept_max}")
                # else:
                #     print(
                #         f"Parameter {cnd_i+1:4d}/{cnd_n}",
                #         f"New Obj {X:10.5f}",
                #         f"Est. dObj {x:10.5f} dObj: {dX:10.5f} Constraints: {keep}", sma,
                #     )
                #     if step.operation == strategy.SPLIT:
                #         visited.add(S.name)
                #     elif step.operation == strategy.MERGE:
                #         visited.add(Sj.name)

        wq.close()
        wq = None

        if strategy.macro_accept_max_total > 0 and n_added > 0:
            strategy.repeat_step()

        print(f"There were {n_added} successful operations")
        cst = cur_cst

        print(f"{datetime.datetime.now()} Visited", visited)
        for name in (node.name for node in cst.hierarchy.index.nodes.values()):
            if name not in step_tracker:
                continue

            if name not in repeat:
                step_tracker[name] = max(strategy.cursor, step_tracker[name])
            else:
                print(f"Assignments changed for {name}, will retarget")
                step_tracker[name] = 0

        pickle.dump([sag, cst, strategy], open("chk.cst.p", "wb"))

        find_successful_candidates_ctx.labeler = None
        find_successful_candidates_ctx.pq = None
        find_successful_candidates_ctx.candidates = None
        find_successful_candidates_ctx.cur_cst = None
        find_successful_candidates_ctx.step = None
        find_successful_candidates_ctx.group_number = None
        find_successful_candidates_ctx.Sj_sma = None
        find_successful_candidates_ctx.groups = None
        find_successful_candidates_ctx.assn = None
        find_successful_candidates_ctx.strategy = None
        find_successful_candidates_ctx.gcd = None
        find_successful_candidates_ctx.smiles = None
        find_successful_candidates_ctx.objective = None
        # if accept_max is not None:
        #     for n, v in step_tracker.items():
        #         if v != -1:
        #             print(f"Setting tracker for {n} to {macro_i}")
        #             step_tracker[n] += 1

    new_assignments = labeler.assign(cst.hierarchy, gcd, smiles, topo)
    mappings = clustering_build_assignment_mappings(
        cst.hierarchy, new_assignments
    )
    cst = smarts_clustering(cst.hierarchy, new_assignments, mappings)
    pickle.dump([sag, cst, strategy], open("chk.cst.p", "wb"))

    ended = datetime.datetime.now()

    print(f"Start time: {started}")
    print(f"End   time: {ended}")

    return cst


def smarts_clustering_find_max_depth(
    group: assignments.structure_assignment_group, maxdepth, gcd=None
) -> int:
    prev_problems = 99999999
    N = 0
    struct_lbls = {}
    max_depth = 0

    for i in range(0, maxdepth):
        topo = group.topology
        assignments = {}
        struct_lbls = {}
        for moli, mol in enumerate(group.assignments, 0):
            print(
                f"Assigning molecule {moli+1:5d}/{len(group.assignments):d}",
                end="\r",
            )
            N += len(mol.selections)
            for molj, (selection, lbl) in enumerate(mol.selections.items()):
                idx = tuple((selection[i] for i in topo.primary))
                atom = graphs.graph_to_structure(mol.graph, idx, topo)
                suc = mapper.mapper_smarts_extend(
                    configs.smarts_extender_config(i, i, True), [atom]
                )
                atom_lbls = struct_lbls.get(atom, dict())
                assignments[(moli, molj)] = lbl

                if lbl not in atom_lbls:
                    atom_lbls[lbl] = []

                atom_lbls[lbl].append((moli, molj, idx))
                struct_lbls[atom] = atom_lbls

        print()
        print("Labels per unique structure that need more depth")
        problems = set()
        for j, lbl in enumerate(struct_lbls.values()):
            if len(lbl.values()) > 1:
                problems.add(tuple(sorted(set(lbl.keys()))))

        print(
            f"There are {len(set(struct_lbls))}/{N} unique structures at depth",
            i,
        )
        print(f"There are {len(problems)} problems:")
        print(problems)
        if len(problems) < prev_problems:
            max_depth = i
            prev_problems = len(problems)

        if gcd:
            for moli, mol in enumerate(group.assignments, 0):
                print(mol.smiles)
                for molj, (selection, lbl) in enumerate(mol.selections.items()):
                    idx = tuple((selection[i] for i in topo.primary))
                    atom = graphs.graph_to_structure(mol.graph, idx, topo)
                    suc = mapper.mapper_smarts_extend(
                        configs.smarts_extender_config(i, i, True), [atom]
                    )
                    these_probs = []
                    for problem in problems:
                        these_probs = []
                        if lbl in problem:
                            these_probs.append(problem)
                    print(
                        "   ",
                        these_probs,
                        selection,
                        lbl,
                        gcd.smarts_encode(atom),
                    )

        if all(len(x.values()) == 1 for x in struct_lbls.values()):
            break

    if any(len(x) > 1 for x in struct_lbls.values()):
        print(
            "WARNING",
            "there are environments with multiple labels. will be"
            "impossible to split environment",
        )
    print("Max depth is set to", max_depth)
    return max_depth


def clustering_collect_structures(A, matches, topo, extend):
    a = [graphs.subgraph_as_structure(A[i], topo) for i in matches]

    for ai in a:
        ai.select = tuple(ai.select[x] for x in ai.topology.primary)

    if extend.depth_max > 0:
        mapper.mapper_smarts_extend(extend, a)

    a = {i: x for i, x in zip(matches, a)}
    return a


def clustering_update_assignments(
    group: assignments.structure_assignment_group, match
) -> assignments.structure_assignment_group:
    new_group = group.copy()
    inverted_match = {x: lbl for lbl, y in match.items() for x in y}
    topo = group.topology

    for i, assns_i in enumerate(new_group.assignments):
        for idx in assns_i.selections:
            primary_idx = tuple((idx[j] for j in topo.primary))
            assns_i.selections[idx] = inverted_match[(i, primary_idx)]

    return new_group


def clustering_initial_conditions(
    gcd, sag: assignments.smiles_assignment_group
):
    topo = sag.topology

    hidx = hierarchies.structure_hierarchy(trees.tree_index(), {}, {}, topo)

    hidx.index.node_add(None, trees.tree_node(0, "parameter", "", "p0"))
    graph = gcd.smiles_decode(sag.assignments[0].smiles)
    select = next(iter(sag.assignments[0].selections.keys()))

    S0 = graphs.graph_to_structure(graph, select, topo)
    S0 = graphs.structure_remove_unselected(S0)
    S0 = graphs.structure_relabel_nodes(
        S0, {n: i for i, n in enumerate(S0.select, 1)}
    )

    graphs.subgraph_fill(S0)

    hidx.subgraphs[0] = graphs.structure_to_subgraph(S0)
    if gcd:
        hidx.smarts[0] = gcd.smarts_encode(S0)
    # match: Dict[str: List[int]] = {"p0": list(assn)}

    group_prefix_str = "p"
    group_name = group_prefix_str + "0"

    assn = []
    for sag_i in sag.assignments:
        sels = {}
        for idx in sag_i.selections:
            sels[idx] = group_name
        assn.append(
            cluster_assignment.smiles_assignment_str(sag_i.smiles, sels)
        )
    new_assn_group = assignments.smiles_assignment_group(assn, sag.topology)

    groups: assignments.assignment_mapping = {
        group_name: list(
            x for y in sag.assignments for x in list(y.selections.values())
        )
    }

    initial_conditions = smarts_clustering(hidx, new_assn_group, groups)
    initial_conditions.group_prefix_str = group_prefix_str

    return initial_conditions


class clustering_collect_split_candidates_ctx:
    ret = None
    assn = None
    backmap = None


def clustering_collect_split_candidates_single_distributed(
    j, matched, shm=None
):
    # Sj = shm.ret.splits[j]
    # bj = ret.shards[i]
    # matched = shm.ret.matched_idx[j]
    # unmatched = ret.unmatch_idx[i]

    # if not graphs.graph_is_valid(Sj):
    #     return None

    unmatch = [v for k, v in shm.backmap.items() if k not in matched]
    matched = [shm.backmap[i] for i in matched]

    # unmatch = [backmap[i] for i in range(len(a)) if i not in matched]

    matched_assn = tuple((shm.assn[i] for i in matched))
    unmatch_assn = tuple((shm.assn[i] for i in unmatch))

    return j, unmatch, matched, matched_assn, unmatch_assn


def clustering_collect_split_candidates_single(j):
    ret = clustering_collect_split_candidates_ctx.ret
    assn = clustering_collect_split_candidates_ctx.assn
    backmap = clustering_collect_split_candidates_ctx.backmap

    Sj = ret.splits[j]
    # bj = ret.shards[i]
    matched = ret.matched_idx[j]
    # unmatched = ret.unmatch_idx[i]

    # if not graphs.graph_is_valid(Sj):
    #     return None

    unmatch = [v for k, v in backmap.items() if k not in matched]
    matched = [backmap[i] for i in matched]

    # unmatch = [backmap[i] for i in range(len(a)) if i not in matched]

    matched_assn = tuple((assn[i] for i in matched))
    unmatch_assn = tuple((assn[i] for i in unmatch))

    return j, unmatch, matched, matched_assn, unmatch_assn


# def clustering_collect_split_candidates_serial(S, a, ret, backmap, assn, step):

#     candidates = {}


#     for Sj, bj, matched, unmatched in sorted(
#         zip(ret.splits, ret.shards, ret.matched_idx, ret.unmatch_idx),
#         key=lambda x: len(x[2]),
#     ):
#         if not graphs.graph_is_valid(Sj):
#             continue

#         unmatch = [v for k,v in backmap.items() if k not in matched]
#         matched = [backmap[i] for i in matched]

#         # unmatch = [backmap[i] for i in range(len(a)) if i not in matched]

#         matched_assn = tuple((assn[i] for i in matched))
#         unmatch_assn = tuple((assn[i] for i in unmatch))

#         overlaps = step.overlap

#         if overlaps is None:
#             overlaps = [0]

#         for edits in step.overlap:
#             if edits not in candidates:
#                 candidates[edits] = []
#             candidates[edits].append(
#                 (S, Sj, step, matched, unmatch, matched_assn, unmatch_assn)
#             )

#     return candidates



def clustering_collect_split_candidates_parallel(
    S, a, ret, backmap, assn, step
):
    candidates = {}

    work = []
    clustering_collect_split_candidates_ctx.ret = ret
    clustering_collect_split_candidates_ctx.assn = assn
    clustering_collect_split_candidates_ctx.backmap = backmap

    with multiprocessing.Pool(configs.processors) as pool:
        for i in range(len(ret.splits)):
            fut = pool.apply_async(
                clustering_collect_split_candidates_single, (i,)
            )
            work.append(fut)

        done = []
        i = 0
        print(
            f"\r{datetime.datetime.now()} Finished {i: 8d}/{len(work)}", end=""
        )
        for i, unit in enumerate(work, 1):
            unit = unit.get()
            if unit is not None:
                done.append(unit)
            print(
                f"\r{datetime.datetime.now()} Finished {i: 8d}/{len(work)}",
                end="",
            )
        print()
        # work = [unit.get() for unit in work]
        # work = [unit for unit in work if unit is not None]

        for i, unmatch, matched, matched_assn, unmatch_assn in sorted(
            done, key=lambda x: len(x[3])
        ):
            Sj = ret.splits[i]

            overlaps = step.overlap

            if overlaps is None:
                overlaps = [0]

            for edits in step.overlap:
                if edits not in candidates:
                    candidates[edits] = []
                candidates[edits].append(
                    (S, Sj, step, matched, unmatch, matched_assn, unmatch_assn)
                )
    clustering_collect_split_candidates_ctx.ret = None
    clustering_collect_split_candidates_ctx.assn = None
    clustering_collect_split_candidates_ctx.backmap = None

    # for Sj, bj, matched, unmatched in sorted(
    #     zip(ret.splits, ret.shards, ret.matched_idx, ret.unmatch_idx),
    #     key=lambda x: len(x[3]),
    # ):
    #         (i),
    #     if not graphs.graph_is_valid(Sj):
    #         continue

    #     unmatch = [v for k,v in backmap.items() if k not in matched]
    #     matched = [backmap[i] for i in matched]

    #     # unmatch = [backmap[i] for i in range(len(a)) if i not in matched]

    #     matched_assn = tuple((assn[i] for i in matched))
    #     unmatch_assn = tuple((assn[i] for i in unmatch))

    #     overlaps = step.overlap

    #     if overlaps is None:
    #         overlaps = [0]

    #     for edits in step.overlap:
    #         if edits not in candidates:
    #             candidates[edits] = []
    #         candidates[edits].append(
    #             (S, Sj, step, matched, unmatch, matched_assn, unmatch_assn)
    #         )

    return candidates


def clustering_collect_split_candidates_serial(S, ret, step):
    candidates = {}

    for p_j, Sj in enumerate(ret.splits):
        overlaps = step.overlap

        if overlaps is None:
            overlaps = [0]

        for edits in step.overlap:
            # if edits not in candidates:
            # candidates[edits] = []
            key = (edits, None, p_j)
            candidates[key] = (S, Sj, step, None, None, None, None)

    # for Sj, bj, matched, unmatched in sorted(
    #     zip(ret.splits, ret.shards, ret.matched_idx, ret.unmatch_idx),
    #     key=lambda x: len(x[3]),
    # ):
    #         (i),
    #     if not graphs.graph_is_valid(Sj):
    #         continue

    #     unmatch = [v for k,v in backmap.items() if k not in matched]
    #     matched = [backmap[i] for i in matched]

    #     # unmatch = [backmap[i] for i in range(len(a)) if i not in matched]

    #     matched_assn = tuple((assn[i] for i in matched))
    #     unmatch_assn = tuple((assn[i] for i in unmatch))

    #     overlaps = step.overlap

    #     if overlaps is None:
    #         overlaps = [0]

    #     for edits in step.overlap:
    #         if edits not in candidates:
    #             candidates[edits] = []
    #         candidates[edits].append(
    #             (S, Sj, step, matched, unmatch, matched_assn, unmatch_assn)
    #         )

    return candidates


def clustering_node_remove_by_name(
    ph: smarts_clustering,
    gcd: codecs.graph_codec,
    assign: assignments.smarts_hierarchy_assignment,
    name: str,
):
    """
    removes the nodes and reassigns tree
    """
    n = trees.tree_index_node_remove_by_name(ph.hierarchy.index, name)
    clustering_assign(ph, gcd, assign)
    ph.mappings.clear()
    return n


def clustering_assign(
    ph: smarts_clustering,
    gcd: codecs.graph_codec,
    assign: assignments.smarts_hierarchy_assignment,
):
    hierarchy = hierarchies.structure_hierarchy_to_smarts_hierarchy(
        ph.hierarchy, gcd
    )
    for assignment in ph.group.assignments:
        smiles = assignment.smiles
        selections = list(assignment.selections)
        matches = assign.assign(hierarchy, gcd, smiles, selections)
        assignment.selections.update(matches)


def clustering_build_assignment_mappings(
    hierarchy: hierarchies.smarts_hierarchy,
    assns: assignments.smiles_assignment_group,
) -> assignments.assignment_mapping:

    mappings = {n.name: [] for n in hierarchy.index.nodes.values()}
    for i, ag in enumerate(assns.assignments):
        for sel, lbl in ag.selections.items():
            mappings[lbl].append((i, sel))

    return mappings


def clustering_build_ordinal_mappings(
    initial_conditions: smarts_clustering, stuag, select=None
):
    """
    parameter:data mapping
    """
    mapping = {n.name: [] for n in initial_conditions.hierarchy.index.nodes.values()}
    for a, b in zip(initial_conditions.group.assignments, stuag.assignments):

        assert a.smiles == b.smiles

        for sel, x in a.selections.items():
            if select is None or x in select:
                y = b.selections.get(sel)
                mapping[x].append(y)

    return mapping


def clustering_build_label_mappings(
    initial_conditions: smarts_clustering, stuag
):
    mapping = {}
    for a, b in zip(initial_conditions.group.assignments, stuag.assignments):
        sa = a.selections
        sb = b.selections
        for x, y in zip(sa.values(), sb.values()):
            if x not in mapping:
                mapping[x] = set()
            mapping[x].add(y)
    return mapping


def match_group_assignments(
    assignments, topo
) -> Dict[str, List[Tuple[int, Sequence[int]]]]:
    match = {}
    for i, assns_i in enumerate(assignments):
        for idx in assns_i.selections:
            lbl = assns_i.compute(idx)
            idx = tuple((idx[j] for j in topo.primary))
            assns = match.get(lbl, list())
            assns.append((i, idx))
            match[lbl] = assns
    return match


def get_assns(assignments, topo):
    assn = {}
    for i, assns_i in enumerate(assignments):
        for idx, lbl in assns_i.selections.items():
            idx = tuple((idx[j] for j in topo.primary))
            assn[(i, idx)] = lbl
    return assn


def clustering_insert_split_candidates(
    new_candidates, assn, objective, S, micro_i
):
    # from besmarts.codecs.codec_rdkit import graph_codec_rdkit
    # gcd = graph_codec_rdkit()
    pq = []
    candidates = {}
    for overlap, cnd in new_candidates.items():
        for p_j, (
            S,
            Sj,
            step,
            matched,
            unmatch,
            matched_assn,
            unmatch_assn,
        ) in enumerate(cnd):
            # group = tuple((assn[i] for i in matched))
            # un_group = tuple((assn[i] for i in unmatch))

            # print(f"Objective1 for Sj:", gcd.smarts_encode(Sj))
            # print("Matched")
            # print(matched)
            # print("UnMatched")
            # print(unmatch)
            x = objective.split(matched_assn, unmatch_assn, overlap=overlap)
            key = (overlap, micro_i, p_j)
            dx = x  # - objective.merge(un_group, group)

            pq.append((dx, key))
            candidates[key] = (
                S,
                Sj,
                step,
                matched,
                unmatch,
                matched_assn,
                unmatch_assn,
            )

    return pq, candidates


# def smarts_clustering_optimize_with_tiers(
#     gcd: codecs.graph_codec,
#     labeler: assignments.smarts_hierarchy_assignment,
#     sag: assignments.smiles_assignment_group,
#     objective: clustering_objective,
#     strategy: optimization.optimization_strategy,
#     initial_conditions: smarts_clustering,
# ) -> smarts_clustering:

#     smiles = [a.smiles for a in sag.assignments]

#     topo = sag.topology

#     group_prefix_str = initial_conditions.group_prefix_str

#     hidx = initial_conditions.hierarchy.copy()

#     groups = clustering_build_ordinal_mappings(initial_conditions, sag)
#     # print(groups)

#     # match = clustering_build_assignment_mappings(initial_conditions, initial_conditions.group)
#     match = initial_conditions.mappings
#     assn = get_assns(sag.assignments, topo)


#     check_lbls_data_selections_equal(initial_conditions.group, sag)


#     """
#     nomenclature

#     match is node_name:data_idx (mol, ic)
#     assn is data_idx:data
#     group is node_name:data
#     mapping node_name:data_idx
#     """

#     group_number = max(
#         [
#             int(x.name[1:])
#             for x in hidx.index.nodes.values()
#             if x.name[0] == group_prefix_str
#         ]
#     )

#     group_number += 1

#     A = {
#         (i, tuple((s[j] for j in topo.primary))): sg
#         for i, y in enumerate(sag.assignments)
#         for s, sg in zip(
#             y.selections,
#             graphs.graph_to_subgraphs(
#                 gcd.smiles_decode(y.smiles), y.selections
#             ),
#         )
#     }


#     N = len(hidx.index.nodes)
#     try:
#         N = len(set(assn.values()))
#     except Exception:
#         pass

#     repeat = set()
#     visited = set()
#     iteration = 1
#     N_str = "{:"+str(len(str(len(A))))+"d}"

#     success = False

#     roots = trees.tree_index_roots(hidx.index)

#     step_tracker = {
#         x.name: 0 for x in strategy.tree_iterator(hidx.index, roots)
#     }


#     assignments = labeler.assign(hidx, gcd, smiles, topo)
#     cst = smarts_clustering(hidx, assignments, clustering_build_assignment_mappings(hidx, assignments))
#     check_lbls_data_selections_equal(cst.group, sag)

#     while True:

#         if success:
#             print("Restarting optimization search")
#             strategy = optimization.optimization_strategy_restart(strategy)
#             success = False

#         elif optimization.optimization_strategy_is_done(strategy):
#             print("Nothing found. Done.")
#             break

#         groups = clustering_build_ordinal_mappings(cst, sag)
#         _, X0 = get_objective(cst, assn, objective.split, 0)

#         roots = trees.tree_index_roots(cst.hierarchy.index)
#         nodes = [
#             x
#             for x in strategy.tree_iterator(cst.hierarchy.index, roots)
#             if strategy.cursor == -1 or strategy.cursor >= step_tracker.get(x.name, 0)
#         ]

#         print("Targets for this macro step:")
#         for nidx, n in enumerate(nodes, 1):
#             print(nidx, n.name)
#         print(f"N Targets: {len(nodes)}")

#         print(f"Step tracker for current macro step {strategy.cursor+1}")
#         for n, v in step_tracker.items():
#             print(n, v+1)

#         macro: optimization.optimization_iteration = strategy.macro_iteration(
#             nodes
#         )

#         candidates = {}
#         pq = []
#         n_added = 0
#         n_macro = len(strategy.steps)

#         t = datetime.datetime.now()
#         print(
#             f"\n\n*******************\n {t}"
#             f" iteration={iteration:4d}"
#             f" macro={strategy.cursor:3d}/{n_macro}"
#             f" X={X0:9.5g}"
#             f" params=({len(cst.mappings)}|{N})"
#             f" overlap={strategy.overlaps}"
#         )
#         print(f"*******************")
#         print()
#         print("Tree:")
#         for ei, e in enumerate(
#             tree_iterators.tree_iter_dive(
#                 cst.hierarchy.index, trees.tree_index_roots(cst.hierarchy.index)
#             )
#         ):
#             s = trees.tree_index_node_depth(cst.hierarchy.index, e)
#             obj_repo = ""
#             if groups[e.name]:
#                 obj_repo = objective.report(groups[e.name])
#             print(
#                 f"** {s:2d} {ei:3d} {e.name:4s}",
#                 obj_repo,
#                 cst.hierarchy.smarts.get(e.index),
#             )
#         print("=====\n")

#         pickle.dump(cst, open("chk.cst.p", "wb"))

#         # breakpoint()
#         while not optimization.optimization_iteration_is_done(macro):
#             t = datetime.datetime.now()
#             print(f"{t} Initializing new loop")
#             step: optimization.optimization_step = (
#                 optimization.optimization_iteration_next(macro)
#             )

#             n_micro = len(macro.steps)
#             config: configs.smarts_perception_config = step.pcp
#             S = step.cluster
#             S0 = graphs.subgraph_to_structure(cst.hierarchy.subgraphs[S.index], topo)

#             cfg = config.extender.copy()
#             if graphs.structure_max_depth(S0) > config.extender.depth_max:
#                 continue

#             S0_depth = graphs.structure_max_depth(S0)
#             d = max(S0_depth, config.splitter.branch_depth_limit)
#             # print("Depth is", d)
#             cfg.depth_max = d
#             cfg.depth_min = S0_depth


#             t = datetime.datetime.now()
#             print(f"{t} Collecting SMARTS for {S.name} N={len(cst.mappings[S.name])}/{len(A)} and setting to depth={S0_depth}")
#             a = clustering_collect_structures(A, cst.mappings[S.name], topo, cfg)

#             assn_s = {i: assn[i] for i in cst.mappings[S.name]}

#             iteration += 1

#             # X = objective_total(hidx, groups, objective)
#             # if X == 0.0:
#             #     break

#             _, X0 = get_objective(cst, assn, objective.split, 0)

#             if step.operation == strategy.SPLIT:
#                 if objective.single(assn_s.values()) == 0.0:
#                     step_tracker[S.name] = strategy.cursor
#                     continue

#                 if len(set(a)) <= 1:
#                     step_tracker[S.name] = strategy.cursor
#                     continue

#             t = datetime.datetime.now()
#             print(
#                 f" =="
#                 f" iteration={iteration:4d}"
#                 f" macro={strategy.cursor:3d}/{n_macro}"
#                 f" micro={macro.cursor:3d}/{n_micro}"
#                 # f" overlap={strategy.overlaps:3d}"
#                 f" operation={step.operation}"
#                 f" params=({len(cst.mappings)}|{N})"
#                 f" cluster={S.name:4s}"
#                 f" N= " + N_str.format(len(a)) + ""
#                 f" bits={config.splitter.bit_search_min}->{config.splitter.bit_search_limit}"
#                 f" depth={config.splitter.branch_depth_min}->{config.splitter.branch_depth_limit}"
#                 f" branch={config.splitter.branch_min}->{config.splitter.branch_limit}"
#             )
#             print()

#             if step.operation == strategy.SPLIT:
#                 new_pq = []
#                 new_candidates = {}
#                 direct_success = False

#                 print("Attempting to split:")
#                 print("S0:", gcd.smarts_encode(S0))
#                 print("Matched:")
#                 seen = set()
#                 for seen_i, (i, x) in enumerate(assn_s.items(), 1):
#                     g = a[i]
#                     # if g not in seen:
#                     print(f"{seen_i:06d} {str(i):24s}", objective.report([x]), gcd.smarts_encode(g))
#                     # seen.add(g)
#                 print()

#                 if (
#                     step.direct_enable
#                 ):  # and config.splitter.bit_search_limit > 2:

#                     assn_i = []
#                     if objective.is_discrete():
#                         assn_i.extend(groups[S.name])
#                     else:
#                         # or form matches based on unique smarts
#                         lbls = set(a)
#                         if len(lbls) < step.direct_limit:
#                             lbls = dict()
#                             for (i, idx), sg in a.items():
#                                 lbl_i = lbls.get(a, len(lbls))
#                                 lbls[a] = lbl_i
#                                 assn_i.append(lbl_i)

#                     if len(set(assn_i)) < step.direct_limit:
#                         pcp = step.pcp.copy()
#                         pcp.extender = cfg
#                         print("Direct splitting....")
#                         # pcp.extender.depth_max = pcp.splitter
#                         # pcp.extender.depth_min = strategy.bounds.extender.depth_min
#                         ret = splits.split_all_partitions(
#                             topo,
#                             pcp,
#                             list(a.values()),
#                             assn_i,
#                             gcd=gcd,
#                             maxmoves=0,
#                         )

#                         if 0 not in new_candidates:
#                             new_candidates[0] = []
#                         for (Sj, Sj0, matches, unmatches) in ret.value:
#                             # Sj = mapper.intersection(Sj, S0, config=configs.mapper_config(3, 1, "high"))
#                             print("Found", sma)

#                             matches = [
#                                 y
#                                 for x, (y, z) in enumerate(a.items())
#                                 if x in matches
#                             ]
#                             unmatches = [
#                                 y
#                                 for x, (y, z) in enumerate(a.items())
#                                 if x in unmatches
#                             ]
#                             new_candidates[0].append(
#                                 (S, Sj, step, matches, unmatches, None, None)
#                             )
#                         if new_candidates[0]:
#                             direct_success = True
#                         else:
#                             print("Direct found nothing")

#                 if step.iterative_enable and not direct_success:

#                     Q = mapper.union_list_parallel(
#                         list(a.values()), reference=S0, max_depth=graphs.structure_max_depth(S0)
#                     )
#                     # print(f"{datetime.datetime.now()} STOPPING")
#                     # time.sleep(1.0)
#                     # print(f"{datetime.datetime.now()} DELETING")
#                     # del Q
#                     # time.sleep(1.0)
#                     # print(f"{datetime.datetime.now()} GARBAGE")
#                     # gc.collect()
#                     # time.sleep(1.0)
#                     # print(f"{datetime.datetime.now()} KILLING")
#                     # time.sleep(1.0)
#                     # assert False
#                     t = datetime.datetime.now()
#                     print(f"{t} Union is {gcd.smarts_encode(Q)}")

#                     ret = splits.split_structures(
#                         config.splitter, S0, list(a.values()), Q=Q
#                     )

#                     backmap = {i: j for i, j in enumerate(cst.mappings[S.name])}
#                     print(f"{datetime.datetime.now()} Collecting new candidates")
#                     new_candidates = clustering_collect_split_candidates_parallel(
#                         S, a, ret, backmap, assn, step
#                     )

#                 print(f"{datetime.datetime.now()} Organizing new candidates")
#                 new_pq, new_candidates = clustering_insert_split_candidates(
#                     new_candidates, assn, objective, S, macro.cursor
#                 )

#                 print(f"{datetime.datetime.now()} Inserting new candidates")
#                 pq.extend(new_pq)
#                 pq = sorted(pq)
#                 candidates.update(new_candidates)
#                 new_candidates.clear()
#                 new_pq.clear()

#             elif step.operation == strategy.MERGE:
#                 for p_j, jidx in enumerate(cst.hierarchy.index.below[S.index]):
#                     J = cst.hierarchy.index.nodes[jidx]
#                     if (
#                         objective.single([assn[i] for i in cst.mappings[J.name]])
#                         == 0.0
#                     ):
#                         continue
#                     for overlap in step.overlap:
#                         obj = objective.merge(
#                             groups[S.name], groups[J.name], overlap=overlap
#                         )
#                         key = (overlap, macro.cursor, p_j)
#                         matched = tuple(
#                             list(cst.mappings[S.name]) + list(cst.mappings[J.name])
#                         )
#                         # Sj = hidx.subgraphs[J.index]
#                         cnd = (S, J, step, tuple(), matched, None, None)
#                         pq.append((obj, key))
#                         candidates[key] = cnd
#                         # print("MERGE", matched, "obj", obj)
#                 pq = sorted(pq)


#         # if accept_max is None:
#         #     for n, v in step_tracker.items():
#         #         if v < macro_i:
#         #             print(f"Setting tracker for {n} to {macro_i}")
#         #             step_tracker[n] = macro_i

#         print(f"{datetime.datetime.now()} Scanning done.")
#         header = False
#         for cnd_i, (x, key) in enumerate(pq, 1):
#             # if x >= 0.0:
#             #     continue
#             if not header:
#                 t = datetime.datetime.now()
#                 print(f"\n\n{t} Candidates from estimated objectives:")
#                 header = True
#             (S, Sj, step, matched, unmatch, _, _) = candidates[key]
#             if step.operation == strategy.MERGE:
#                 Sj = cst.hierarchy.subgraphs[Sj.index]
#             print(f" > {cnd_i:4d} {x:10.5f}", step.operation, f"Parent: {S.name}", gcd.smarts_encode(Sj))

#         print(f"{datetime.datetime.now()} Labeling")
#         cur_assignments = labeler.assign(cst.hierarchy, gcd, smiles, topo)
#         print(f"{datetime.datetime.now()} Rebuilding assignments")
#         cur_mappings = clustering_build_assignment_mappings(cst.hierarchy, cur_assignments)
#         cur_cst = smarts_clustering(cst.hierarchy.copy(), cur_assignments, cur_mappings)
#         print(f"{datetime.datetime.now()} Rebuilding mappings")
#         groups = clustering_build_ordinal_mappings(cur_cst, sag)
#         check_lbls_data_selections_equal(cst.group, sag)

#         cnd_n = len(pq)

#         pq = [x for x in pq if x[0] < strategy.filter_above]
#         t = datetime.datetime.now()
#         print(f"{t} Searching {len(pq)}/{cnd_n} promising parameters for operation below {strategy.filter_above}")

#         cnd_n = len(pq)


#         print(datetime.datetime.now())
#         print(f"\n\nGenerating SMARTS on {len(pq)}")
#         Sj_sma = []

#         with multiprocessing.pool.Pool(configs.processors) as pool:
#             if step.operation == strategy.SPLIT:
#                 Sj_lst = [candidates[x[1]][1] for x in pq]
#             elif step.operation == strategy.MERGE:
#                 Sj_lst = [cst.hierarchy.subgraphs[candidates[x[1]][1].index] for x in pq]
#             Sj_sma = pool.map_async(gcd.smarts_encode, Sj_lst).get()
#             del Sj_lst

#         visited.clear()
#         repeat.clear()

#         find_successful_candidates_ctx.labeler = labeler
#         find_successful_candidates_ctx.pq = pq
#         find_successful_candidates_ctx.candidates = candidates
#         find_successful_candidates_ctx.cur_cst = cur_cst
#         find_successful_candidates_ctx.step = step
#         find_successful_candidates_ctx.group_number = group_number
#         find_successful_candidates_ctx.Sj_sma = Sj_sma
#         find_successful_candidates_ctx.groups = groups
#         find_successful_candidates_ctx.assn = assn
#         find_successful_candidates_ctx.strategy = strategy
#         find_successful_candidates_ctx.gcd = gcd
#         find_successful_candidates_ctx.smiles = smiles
#         find_successful_candidates_ctx.objective = objective

#         pq_idx = 0
#         procs = os.cpu_count() if configs.processors is None else configs.processors
#         while pq_idx < len(pq):
#             print(datetime.datetime.now(), f"Batching {pq_idx+1} to {len(pq)} with chunk= {procs}")
#             batches = mapper.batched(range(pq_idx, len(pq)), procs)
#             added = False
#             for batch in batches:
#                 if added:
#                     break
#                 find_successful_candidates_ctx.group_number = group_number
#                 find_successful_candidates_ctx.cur_cst = cur_cst
#                 with multiprocessing.pool.Pool(configs.processors) as pool:
#                     work = []
#                     for cnd_i in batch:
#                         work.append(pool.apply_async(find_successful_candidates, (cnd_i,)))
#                     # work = [unit.get() for unit in work]
#                     for unit in work:
#                         cnd_i, keep, X = unit.get()
#                         dX = X - X0

#                         (x, key) = pq[cnd_i]
#                         (S, Sj, step, matched, unmatch, match_assn, unmatch_assn) = candidates[key]
#                         pq_idx = cnd_i+1
#                         sma = Sj_sma[cnd_i]
#                         # visited.add(S.name)

#                         if keep:

#                         # for cnd_i, (x, key) in enumerate(pq, 1):
#                             # print(datetime.datetime.now(), '*** 1', cnd_i)

#                             (edits, _, p_j) = key
#                             param_name = "p."
#                             sma = ""
#                             added = False
#                             dX = 0.0

#                             hidx = cur_cst.hierarchy.copy()

#                             if step.operation == strategy.SPLIT:

#                                 param_name = "p" + str(group_number)

#                                 # print(datetime.datetime.now(), '*** 2')
#                                 hent = hidx.index.node_add(
#                                     S.index,
#                                     trees.tree_node(
#                                         None, "parameter", "", param_name
#                                     ),
#                                     index=0,
#                                 )
#                                 # print(datetime.datetime.now(), '*** 3')
#                                 Sj = graphs.subgraph_relabel_nodes(
#                                     Sj, {n: i for i, n in enumerate(Sj.select, 1)}
#                                 )
#                                 Sj = graphs.subgraph_to_structure(Sj, topo)

#                                 sma = Sj_sma[cnd_i] #gcd.smarts_encode(Sj)

#                                 hidx.subgraphs[hent.index] = Sj
#                                 hidx.smarts[hent.index] = sma

#                                 # print(datetime.datetime.now(), '*** 4')
#                                 new_assignments = labeler.assign(hidx, gcd, smiles, topo)
#                                 # print(datetime.datetime.now(), '*** 5')
#                                 new_match = clustering_build_assignment_mappings(hidx, new_assignments)

#                                 cst = smarts_clustering(hidx, new_assignments, new_match)

#                                 new_match = None
#                                 new_assignments = None
#                                 # print(datetime.datetime.now(), '*** 7')
#                                 keep, X = get_objective(cst, assn, objective.split, edits, splitting=True)
#                                 dX = X - X0
#                                 # if dX > 0:
#                                 #     keep = False

#                                 # print(datetime.datetime.now(), '*** 8')


#                                 # visited.add(S.name)

#                                 if keep:
#                                     visited.add(hent.name)
#                                     # mappings = clustering_build_assignment_mappings(new_assignments)
#                                     groups = clustering_build_ordinal_mappings(cst, sag)


#                                     cst.hierarchy.subgraphs[hent.index] = Sj
#                                     cst.hierarchy.smarts[hent.index] = sma

#                                     obj = objective.split(
#                                         groups[S.name], groups[hent.name], overlap=edits
#                                     )

#                                     success = True
#                                     added = True
#                                     group_number += 1
#                                     print(
#                                         f"\n>>>>> New parameter {cnd_i+1:4d}/{cnd_n}",
#                                         hent.name,
#                                         "parent",
#                                         S.name,
#                                         "Objective",
#                                         f"{X:10.5f}",
#                                         "Delta",
#                                         f"{dX:10.5f}",
#                                         f"Partition {len(cst.mappings[S.name])}|{len(cst.mappings[hent.name])}",
#                                     )
#                                     print(
#                                         " >>>>>",
#                                         key,
#                                         f"x0 {x:10.5f} x1 {obj:10.5f}",
#                                         sma,
#                                         end="\n\n"
#                                     )

#                                     repeat.add(hent.name)
#                                     step_tracker[hent.name] = 0

#                                 # strategy.repeat_step()
#                             elif step.operation == strategy.MERGE:

#                                 hent = Sj
#                                 param_name = hent.name

#                                 visited.add(Sj.name)

#                                 if (S.name not in groups) or (hent.name not in groups):
#                                     continue

#                                 obj = objective.merge(
#                                     groups[S.name], groups[Sj.name], overlap=edits
#                                 )
#                                 keep = True
#                                 if obj > 0.0:
#                                     keep = False

#                                 Sj = hidx.subgraphs[Sj.index]
#                                 sma = Sj_sma[cnd_i]

#                                 if keep:

#                                     trees.tree_index_node_remove(hidx.index, hent.index)
#                                     new_assignments = labeler.assign(hidx, gcd, smiles, topo)
#                                     new_match = clustering_build_assignment_mappings(hidx, new_assignments)
#                                     cst = smarts_clustering(hidx, new_assignments, new_match)
#                                     new_assignments = None
#                                     new_match = None

#                                     # new_match = match_group_assignments(cst.group.assignments, topo)

#                                     _, X = get_objective(cst, assn, objective.split, edits, splitting=False)

#                                     dX = X - X0
#                                     # if dX > 0:
#                                     #     keep = False

#                                     if hent.name in step_tracker:
#                                         step_tracker.pop(hent.name)
#                                     else:
#                                         print("WARNING", hent.name, "missing from the tracker")

#                                     groups = clustering_build_ordinal_mappings(cst, sag)

#                                     visited.add(S.name)
#                                     visited.remove(hent.name)

#                                     above = cst.hierarchy.index.above.get(S.index)
#                                     if above is not None:
#                                         repeat.add(cst.hierarchy.index.nodes[above].name)


#                                     cst.hierarchy.subgraphs.pop(hent.index)
#                                     cst.hierarchy.smarts.pop(hent.index)

#                                     success = True
#                                     added = True

#                                     print(
#                                         f">>>>> Delete parameter {cnd_i:4d}/{cnd_n}",
#                                         hent.name,
#                                         "parent",
#                                         S.name,
#                                         "Objective",
#                                         f"{X:10.5f}",
#                                         "Delta",
#                                         f"{dX:10.5f}",
#                                     )
#                                     print(
#                                         " >>>>>",
#                                         key,
#                                         f"x0 {x:10.5f} x1 {obj:10.5f}",
#                                         gcd.smarts_encode(Sj),
#                                         end="\n\n"
#                                     )

#                             if added:
#                                 # print("Mappings:")
#                                 # pprint.pprint(cst.mappings)
#                                 # print("=========")

#                                 repeat.add(S.name)
#                                 mod_lbls = cluster_assignment.smiles_assignment_str_modified(
#                                     cur_cst.group.assignments, cst.group.assignments
#                                 )
#                                 repeat.update(mod_lbls)
#                                 cur_cst = cst
#                                 cst = None
#                                 X0 = X
#                                 n_added += 1
#                                 if strategy.accept_max > 0 and n_added == strategy.accept_max:
#                                     strategy.repeat_step()
#                                     break
#                             break
#                         else:
#                             print(
#                                 f"Parameter {cnd_i+1:4d}/{cnd_n}",
#                                 f"New Obj {X:10.5f}",
#                                 f"Est. dObj {x:10.5f} dObj: {dX:10.5f} Constraints: {keep}", sma,
#                             )
#                             if step.operation == strategy.SPLIT:
#                                 visited.add(S.name)
#                             elif step.operation == strategy.MERGE:
#                                 visited.add(Sj.name)

#         cst = cur_cst
#         print(f"{datetime.datetime.now()} Visited", visited)
#         for name in (node.name for node in cst.hierarchy.index.nodes.values()):

#             if name not in step_tracker:
#                 continue

#             if name not in repeat:
#                 step_tracker[name] = max(strategy.cursor, step_tracker[name])
#             else:
#                 print(f"Assignments changed for {name}, will retarget")
#                 step_tracker[name] = 0

#         pickle.dump(cst, open("chk.cst.p", "wb"))

#         find_successful_candidates_ctx.labeler = None
#         find_successful_candidates_ctx.pq = None
#         find_successful_candidates_ctx.candidates = None
#         find_successful_candidates_ctx.cur_cst = None
#         find_successful_candidates_ctx.step = None
#         find_successful_candidates_ctx.group_number = None
#         find_successful_candidates_ctx.Sj_sma = None
#         find_successful_candidates_ctx.groups = None
#         find_successful_candidates_ctx.assn = None
#         find_successful_candidates_ctx.strategy = None
#         find_successful_candidates_ctx.gcd = None
#         find_successful_candidates_ctx.smiles = None
#         find_successful_candidates_ctx.objective = None
#         # if accept_max is not None:
#         #     for n, v in step_tracker.items():
#         #         if v != -1:
#         #             print(f"Setting tracker for {n} to {macro_i}")
#         #             step_tracker[n] += 1


#     new_assignments = labeler.assign(cst.hierarchy, gcd, smiles, topo)
#     mappings = clustering_build_assignment_mappings(cst.hierarchy, new_assignments)
#     cst = smarts_clustering(cst.hierarchy, new_assignments, mappings)
#     pickle.dump(cst, open("chk.cst.p", "wb"))

#     return cst
