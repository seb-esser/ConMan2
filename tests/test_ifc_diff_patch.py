"""
Diff & patch on IFC fixtures, checked with a structural signature (ids and order independent): the
patched graph exported with graph_2_ifc must equal the target version exported with graph_2_ifc.

NetworkX tests run without DB; Neo4j tests are opt-in via CONMAN2_TEST_NEO4J_URI (wipes that DB).
"""
import contextlib
import io
import os
import sys

import pytest

root_dir = os.path.dirname(os.path.dirname(__file__))
src_dir = os.path.join(root_dir, "src")
sys.path.insert(0, src_dir)
sys.path.insert(0, os.path.dirname(__file__))

from ifc_signature import ifc_signature  # noqa: E402
from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface  # noqa: E402
from graph_diff.GraphDiffNx import GraphDiffNx  # noqa: E402
from graph_patch.GraphPatchNx import GraphPatchNx  # noqa: E402

IFC_DIR = os.path.join(src_dir, "00_sampleData", "IFC_stepP21")
NEO4J_TEST_URI = os.environ.get("CONMAN2_TEST_NEO4J_URI")
requires_neo4j = pytest.mark.skipif(not NEO4J_TEST_URI, reason="CONMAN2_TEST_NEO4J_URI not set")


def init_updt_pairs():
    pairs = []
    for case in sorted(os.listdir(IFC_DIR)):
        files = sorted(f for f in os.listdir(os.path.join(IFC_DIR, case)) if f.endswith(".ifc"))
        init = [f for f in files if f.lower().startswith("init")]
        updt = [f for f in files if f.lower().startswith("upd")]
        if init and updt:
            pairs.append(pytest.param(os.path.join(IFC_DIR, case, init[0]), os.path.join(IFC_DIR, case, updt[0]), id=case))
    return pairs


PAIRS = init_updt_pairs()
V8 = os.path.join(IFC_DIR, "8VersionsTest")
# IfcColumnType gets a new GlobalId in every version; its IfcRepresentationMap is shared with the column's
# IfcMappedItem. The re-created type ends up with two RepresentationMaps (open issue, see
# docs/GeoJSON_CityGML_DiffPatch.md, "Known open issues"). master is wrong from v1->v2 on and crashes at v5->v6.
V8_PAIRS = [pytest.param(os.path.join(V8, f"v{i}.ifc"), os.path.join(V8, f"v{i + 1}.ifc"), id=f"8Versions-v{i}-v{i + 1}",
                         marks=[] if i < 2 else pytest.mark.xfail(reason="regenerated type GlobalId + shared RepresentationMap", strict=False))
            for i in range(7)]


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def nx_check(tmp_path, init, updt):
    gi = quiet(IfcGraphInterface, "networkx")
    quiet(gi.ifc_2_graph, init, "ts1")
    quiet(gi.ifc_2_graph, updt, "ts2")
    quiet(gi.graph_2_ifc, "ref_ts1.ifc", "ts1")
    quiet(gi.graph_2_ifc, "ref_ts2.ifc", "ts2")
    pid = IfcGraphInterface.get_project_id_from_ifc_path(init)
    diff = GraphDiffNx.from_files("networkx_graph_ts1.gpickle", "networkx_graph_ts2.gpickle")
    eq = diff.run_diff("ts1", "ts2")
    GraphPatchNx().create_patch(pid, "ts1", "ts2", diff.graph_init, diff.graph_updt, eq)
    results = {}
    for src, dst, f in (("ts1", "ts2", init), ("ts2", "ts1", updt)):
        quiet(gi.ifc_2_graph, f, src)
        GraphPatchNx().apply_patch(pid, src, dst)
        quiet(gi.graph_2_ifc, f"out_{dst}.ifc", dst)
        results[dst] = ifc_signature(f"out_{dst}.ifc") == ifc_signature(f"ref_{dst}.ifc")
    return results


@pytest.mark.parametrize("init,updt", PAIRS)
def test_nx_ifc_patch_forward_and_reverse(tmp_path, monkeypatch, init, updt):
    monkeypatch.chdir(tmp_path)
    assert nx_check(tmp_path, init, updt) == {"ts2": True, "ts1": True}


@pytest.mark.parametrize("init,updt", V8_PAIRS)
def test_nx_ifc_8versions(tmp_path, monkeypatch, init, updt):
    monkeypatch.chdir(tmp_path)
    assert nx_check(tmp_path, init, updt)["ts2"]


def test_shared_representation_retarget_is_patched(tmp_path, monkeypatch):
    """GeomRepresentation_01: Cuboid2 switches to the representation shared with Cuboid1 (context relation)."""
    import ifcopenshell
    monkeypatch.chdir(tmp_path)
    d = os.path.join(IFC_DIR, "GeomRepresentation_01")
    nx_check(tmp_path, os.path.join(d, "Initial_GeomRepresentation_01.ifc"), os.path.join(d, "Update_GeomRepresentation_01.ifc"))
    proxies = {p.Name: p for p in ifcopenshell.open("out_ts2.ifc").by_type("IfcBuildingElementProxy")}
    assert proxies["Cuboid2"].Representation is not None
    assert proxies["Cuboid1"].Representation == proxies["Cuboid2"].Representation


@pytest.fixture
def neo4j_db(tmp_path, monkeypatch):
    from neomodel import config, db
    config.DATABASE_URL = NEO4J_TEST_URI
    monkeypatch.chdir(tmp_path)
    db.cypher_query("MATCH (n) DETACH DELETE n")
    yield db
    db.cypher_query("MATCH (n) DETACH DELETE n")


@requires_neo4j
@pytest.mark.parametrize("init,updt", PAIRS)
def test_neo4j_ifc_patch_forward_and_reverse(neo4j_db, init, updt):
    from graph_diff.GraphDiff import GraphDiff
    from graph_patch.GraphPatch import GraphPatch
    gi = quiet(IfcGraphInterface, "neo4j")
    pid = IfcGraphInterface.get_project_id_from_ifc_path(init)
    quiet(gi.ifc_2_graph, init, "ts1")
    quiet(gi.ifc_2_graph, updt, "ts2")
    quiet(gi.graph_2_ifc, "ref_ts1.ifc", "ts1")
    quiet(gi.graph_2_ifc, "ref_ts2.ifc", "ts2")
    quiet(GraphDiff().run_diff, "ts1", "ts2")
    quiet(GraphPatch().create_patch, pid, "ts1", "ts2")
    for src, dst, f in (("ts1", "ts2", init), ("ts2", "ts1", updt)):
        neo4j_db.cypher_query("MATCH (n) DETACH DELETE n")
        quiet(gi.ifc_2_graph, f, src)
        quiet(GraphPatch().apply_patch, pid, src, dst)
        quiet(gi.graph_2_ifc, f"out_{dst}.ifc", dst)
        assert ifc_signature(f"out_{dst}.ifc") == ifc_signature(f"ref_{dst}.ifc"), f"{src}->{dst}"
