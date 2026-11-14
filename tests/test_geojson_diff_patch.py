"""
Diff & patch tests for GeoJSON graphs.

* NetworkX tests run without a database.
* Neo4j tests (incl. cross-provider patch application) are opt-in via CONMAN2_TEST_NEO4J_URI and wipe
  that database, e.g.  CONMAN2_TEST_NEO4J_URI=bolt://neo4j:password@localhost:7688 pytest tests
"""
import contextlib
import io
import json
import os
import sys
from collections import Counter

import pytest

root_dir = os.path.dirname(os.path.dirname(__file__))
src_dir = os.path.join(root_dir, "src")
sys.path.insert(0, src_dir)

from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface  # noqa: E402
from graph_diff.GraphDiffNx import GraphDiffNx  # noqa: E402
from graph_patch.GraphPatchNx import GraphPatchNx  # noqa: E402

GEOJSON = os.path.join(src_dir, "00_sampleData", "GeoJSON")
CAMPUS = [os.path.join(GEOJSON, "citygml_campus", f"campus_v{i}.geojson") for i in range(1, 6)]
CAMPUS_PAIRS = list(zip(CAMPUS, CAMPUS[1:]))
OSM = sorted(os.path.join(GEOJSON, "osm_tum_campus", f) for f in os.listdir(os.path.join(GEOJSON, "osm_tum_campus")))
CAMPUS_ID = "tum-campus-citygml3-demo"
ROOT = "FeatureCollection"

NEO4J_TEST_URI = os.environ.get("CONMAN2_TEST_NEO4J_URI")
requires_neo4j = pytest.mark.skipif(not NEO4J_TEST_URI, reason="CONMAN2_TEST_NEO4J_URI not set")


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class NxPipeline:
    """parse -> diff -> create_patch -> apply (NetworkX provider), all files below tmp_path."""

    def __init__(self, tmp_path):
        self.dir = tmp_path
        self.gi = quiet(GeoJsonGraphInterface, "networkx")
        self.patch_dir = str(tmp_path / "patch_data")

    def gf(self, ts, tag="src"):
        return str(self.dir / f"{tag}_{ts}.json")

    def commit(self, project_id, file_init, file_updt, ts_init="ts1", ts_updt="ts2"):
        quiet(self.gi.geojson_2_graph, file_init, ts_init, graph_file=self.gf(ts_init))
        quiet(self.gi.geojson_2_graph, file_updt, ts_updt, graph_file=self.gf(ts_updt))
        diff = GraphDiffNx.from_files(self.gf(ts_init), self.gf(ts_updt))
        eq = diff.run_diff(ts_init, ts_updt, root_entity_type=ROOT)
        patch = GraphPatchNx()
        patch.create_patch(project_id, ts_init, ts_updt, diff.graph_init, diff.graph_updt, eq, patch_dir=self.patch_dir)
        return diff, patch

    def checkout(self, project_id, file_src, ts_src, ts_dst, patch_dir=None):
        quiet(self.gi.geojson_2_graph, file_src, ts_src, graph_file=self.gf(ts_src, "apply"))
        GraphPatchNx().apply_patch(project_id, ts_src, ts_dst, graph_file_init=self.gf(ts_src, "apply"),
                                   graph_file_updt=self.gf(ts_dst, "applied"), patch_dir=patch_dir or self.patch_dir)
        return quiet(self.gi.graph_2_geojson, None, ts_dst, graph_file=self.gf(ts_dst, "applied"))


@pytest.fixture
def nx_pipeline(tmp_path):
    return NxPipeline(tmp_path)


def pushout(diff, ts_init="ts1", ts_updt="ts2"):
    """EntityType counts of nodes without equivalent on each side."""
    init = Counter(d["EntityType"] for n, d in diff.graph_init.nodes(data=True) if n not in diff.init_to_updt)
    updt = Counter(d["EntityType"] for n, d in diff.graph_updt.nodes(data=True) if n not in diff.updt_to_init)
    return init, updt


# ----------------------------------------------------------------------
# NetworkX: patch application reproduces the target version (both directions)
# ----------------------------------------------------------------------

@pytest.mark.parametrize("file_init,file_updt", CAMPUS_PAIRS,
                         ids=[f"v{i + 1}-v{i + 2}" for i in range(len(CAMPUS_PAIRS))])
def test_nx_patch_forward_and_reverse(nx_pipeline, file_init, file_updt):
    nx_pipeline.commit(CAMPUS_ID, file_init, file_updt)
    assert nx_pipeline.checkout(CAMPUS_ID, file_init, "ts1", "ts2") == load(file_updt)
    assert nx_pipeline.checkout(CAMPUS_ID, file_updt, "ts2", "ts1") == load(file_init)


@pytest.mark.parametrize("file_init,file_updt", list(zip(OSM, OSM[1:])), ids=["2020-2024", "2024-2026"])
def test_nx_patch_real_osm_data(nx_pipeline, file_init, file_updt):
    pid = load(file_init)["id"]
    nx_pipeline.commit(pid, file_init, file_updt)
    assert nx_pipeline.checkout(pid, file_init, "ts1", "ts2") == load(file_updt)
    assert nx_pipeline.checkout(pid, file_updt, "ts2", "ts1") == load(file_init)


def test_nx_chain_of_patches(nx_pipeline):
    """Like VersionTimeline.checkout: apply v1->v2->...->v5 consecutively on the same graph."""
    for i, (a, b) in enumerate(CAMPUS_PAIRS):
        nx_pipeline.commit(CAMPUS_ID, a, b, f"v{i + 1}", f"v{i + 2}")
    gi = nx_pipeline.gi
    quiet(gi.geojson_2_graph, CAMPUS[0], "v1", graph_file=nx_pipeline.gf("v1", "chain"))
    for i in range(len(CAMPUS_PAIRS)):
        GraphPatchNx().apply_patch(CAMPUS_ID, f"v{i + 1}", f"v{i + 2}", graph_file_init=nx_pipeline.gf(f"v{i + 1}", "chain"),
                                   graph_file_updt=nx_pipeline.gf(f"v{i + 2}", "chain"), patch_dir=nx_pipeline.patch_dir)
    assert quiet(gi.graph_2_geojson, None, "v5", graph_file=nx_pipeline.gf("v5", "chain")) == load(CAMPUS[-1])
    for i in reversed(range(len(CAMPUS_PAIRS))):
        GraphPatchNx().apply_patch(CAMPUS_ID, f"v{i + 2}", f"v{i + 1}", graph_file_init=nx_pipeline.gf(f"v{i + 2}", "chain"),
                                   graph_file_updt=nx_pipeline.gf(f"v{i + 1}", "chain"), patch_dir=nx_pipeline.patch_dir)
    assert quiet(gi.graph_2_geojson, None, "v1", graph_file=nx_pipeline.gf("v1", "chain")) == load(CAMPUS[0])


# ----------------------------------------------------------------------
# NetworkX: the diff/patch content matches the documented changes (CHANGELOG.json)
# ----------------------------------------------------------------------

def test_equivalence_is_one_to_one(nx_pipeline):
    for a, b in CAMPUS_PAIRS:
        diff, _ = nx_pipeline.commit(CAMPUS_ID, a, b)
        assert len(set(diff.init_to_updt.values())) == len(diff.init_to_updt)


def test_v1_v2_semantic_only(nx_pipeline):
    diff, patch = nx_pipeline.commit(CAMPUS_ID, CAMPUS[0], CAMPUS[1])
    assert pushout(diff) == (Counter(), Counter())
    sema = patch.semantic_patch_pattern
    props = sema["[primary_node=bldg-0001]|[EntityType=Properties,list_index=0,rel_type=properties]"]
    assert props["energyRating"] == {"ts1": None, "ts2": "B"}            # key added
    assert props["comment"] == {"ts1": "null", "ts2": None}              # key (holding null) removed
    assert props["measuredHeight"] == {"ts1": 23.5, "ts2": 24.1}
    address = "[primary_node=bldg-0001]|[EntityType=Properties,list_index=0,rel_type=properties]|[EntityType=JsonObject,list_index=0,rel_type=address]"
    assert sema[address] == {"houseNumber": {"ts1": "21", "ts2": "21a"}}
    assert all("p21_id" not in changes for changes in sema.values())     # stable structural keys


def test_v2_v3_geometry(nx_pipeline):
    diff, patch = nx_pipeline.commit(CAMPUS_ID, CAMPUS[1], CAMPUS[2])
    init, updt = pushout(diff)
    assert init == Counter({"LinearRing": 1, "Position": 5})   # courtyard hole removed
    assert updt == Counter({"Position": 1})                    # road extended by one vertex
    moved = [p for p in patch.semantic_patch_pattern if p.startswith("[primary_node=bldg-0002]")]
    assert moved == ["[primary_node=bldg-0002]|[EntityType=Polygon,list_index=0,rel_type=geometry]"
                     "|[EntityType=LinearRing,list_index=0,rel_type=coordinates]"
                     "|[EntityType=Position,list_index=1,rel_type=coordinates]"]


def test_v3_v4_feature_topology(nx_pipeline):
    diff, patch = nx_pipeline.commit(CAMPUS_ID, CAMPUS[2], CAMPUS[3])
    init, updt = pushout(diff)
    # tree-0003 removed: Feature + membership + Point + Position + Properties
    assert init == Counter({"Feature": 1, "FeatureMembership": 1, "Point": 1, "Position": 1, "Properties": 1})
    # bldg-0003 added (Feature, membership, Polygon, ring, 5 positions, Properties) + 4th bench point
    assert updt == Counter({"Feature": 1, "FeatureMembership": 1, "Polygon": 1, "LinearRing": 1,
                            "Position": 6, "Properties": 1})
    topo_updt = patch.topological_patch_pattern["ts2"]
    assert any(e["properties"].get("GlobalId") == "bldg-0003" for e in topo_updt.values())
    # insertion shifts the member_index of the following features -> semantic changes on memberships
    shifted = [p for p, c in patch.semantic_patch_pattern.items() if "member_index" in c]
    assert "[connection_node=tum-campus-citygml3-demo::road-0001]" in shifted


def test_v4_v5_geometry_type_change(nx_pipeline):
    diff, _ = nx_pipeline.commit(CAMPUS_ID, CAMPUS[3], CAMPUS[4])
    init, updt = pushout(diff)
    assert init["Polygon"] == 1 and updt["MultiPolygon"] == 1   # water-0001 Polygon -> MultiPolygon


def test_patch_files_written(nx_pipeline):
    nx_pipeline.commit(CAMPUS_ID, CAMPUS[0], CAMPUS[1])
    names = sorted(os.listdir(nx_pipeline.patch_dir))
    assert names == [f"Patch_Sema_{CAMPUS_ID}_ts1_ts2.json", f"Patch_Topo_{CAMPUS_ID}_ts1_ts2.json"]


def test_equivalences_roundtrip(nx_pipeline, tmp_path):
    diff, _ = nx_pipeline.commit(CAMPUS_ID, CAMPUS[0], CAMPUS[1])
    path = str(tmp_path / "eq" / GraphDiffNx.equivalence_file("ts1", "ts2"))
    diff.save_equivalences(path)
    assert GraphDiffNx.load_equivalences(path) == diff.init_to_updt


# ----------------------------------------------------------------------
# NetworkX diff/patch also works for IFC graphs (same meta model)
# ----------------------------------------------------------------------

IFC_CASES = ["GeomRepresentation_01", "GeomRepresentation_03", "LocalPlacement_01"]


@pytest.mark.parametrize("case", IFC_CASES)
def test_nx_diff_patch_ifc(tmp_path, monkeypatch, case):
    import ifcopenshell
    from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
    d = os.path.join(src_dir, "00_sampleData", "IFC_stepP21", case)
    files = sorted(f for f in os.listdir(d) if f.endswith(".ifc"))
    init = os.path.join(d, next(f for f in files if f.lower().startswith("init")))
    updt = os.path.join(d, next(f for f in files if f.lower().startswith("upd")))
    monkeypatch.chdir(tmp_path)
    gi = quiet(IfcGraphInterface, "networkx")
    quiet(gi.ifc_2_graph, init, "ts1")
    quiet(gi.ifc_2_graph, updt, "ts2")
    pid = IfcGraphInterface.get_project_id_from_ifc_path(init)
    diff = GraphDiffNx.from_files("networkx_graph_ts1.gpickle", "networkx_graph_ts2.gpickle")
    eq = diff.run_diff("ts1", "ts2")
    GraphPatchNx().create_patch(pid, "ts1", "ts2", diff.graph_init, diff.graph_updt, eq)
    quiet(gi.ifc_2_graph, init, "ts1")
    GraphPatchNx().apply_patch(pid, "ts1", "ts2")
    quiet(gi.graph_2_ifc, "out.ifc", "ts2")
    counts = lambda p: Counter(e.is_a() for e in ifcopenshell.open(p))
    assert counts("out.ifc") == counts(updt)


# ----------------------------------------------------------------------
# Neo4j (opt-in): same pipeline, same results, interchangeable patch files
# ----------------------------------------------------------------------

@pytest.fixture
def neo4j_db(tmp_path, monkeypatch):
    from neomodel import config, db
    config.DATABASE_URL = NEO4J_TEST_URI
    monkeypatch.chdir(tmp_path)   # GraphPatch writes to ./patch_data
    db.cypher_query("MATCH (n) DETACH DELETE n")
    yield db
    db.cypher_query("MATCH (n) DETACH DELETE n")


def neo4j_commit(db, file_init, file_updt, ts_init="ts1", ts_updt="ts2"):
    from graph_diff.GraphDiff import GraphDiff
    from graph_patch.GraphPatch import GraphPatch
    gi = quiet(GeoJsonGraphInterface, "neo4j")
    quiet(gi.geojson_2_graph, file_init, ts_init)
    quiet(gi.geojson_2_graph, file_updt, ts_updt)
    quiet(GraphDiff().run_diff, ts_init, ts_updt, root_entity_type=ROOT)
    quiet(GraphPatch().create_patch, load(file_init)["id"], ts_init, ts_updt)
    db.cypher_query("MATCH (n) DETACH DELETE n")


def neo4j_checkout(db, file_src, ts_src, ts_dst):
    from graph_patch.GraphPatch import GraphPatch
    gi = quiet(GeoJsonGraphInterface, "neo4j")
    db.cypher_query("MATCH (n) DETACH DELETE n")
    quiet(gi.geojson_2_graph, file_src, ts_src)
    quiet(GraphPatch().apply_patch, load(file_src)["id"], ts_src, ts_dst)
    return quiet(gi.graph_2_geojson, None, ts_dst)


@requires_neo4j
@pytest.mark.parametrize("file_init,file_updt", CAMPUS_PAIRS,
                         ids=[f"v{i + 1}-v{i + 2}" for i in range(len(CAMPUS_PAIRS))])
def test_neo4j_patch_forward_and_reverse(neo4j_db, file_init, file_updt):
    neo4j_commit(neo4j_db, file_init, file_updt)
    assert neo4j_checkout(neo4j_db, file_init, "ts1", "ts2") == load(file_updt)
    assert neo4j_checkout(neo4j_db, file_updt, "ts2", "ts1") == load(file_init)


@requires_neo4j
@pytest.mark.parametrize("file_init,file_updt", CAMPUS_PAIRS,
                         ids=[f"v{i + 1}-v{i + 2}" for i in range(len(CAMPUS_PAIRS))])
def test_providers_create_identical_semantic_patches_and_interchangeable_files(neo4j_db, tmp_path, file_init, file_updt):
    neo4j_commit(neo4j_db, file_init, file_updt)            # writes ./patch_data (cwd = tmp_path)
    nx_pipeline = NxPipeline(tmp_path / "nx")
    os.makedirs(tmp_path / "nx")
    nx_pipeline.commit(CAMPUS_ID, file_init, file_updt)
    name = f"Patch_Sema_{CAMPUS_ID}_ts1_ts2.json"
    assert load(os.path.join("patch_data", name)) == load(os.path.join(nx_pipeline.patch_dir, name))
    # Neo4j-created patch applied with NetworkX
    assert nx_pipeline.checkout(CAMPUS_ID, file_init, "ts1", "ts2", patch_dir="patch_data") == load(file_updt)
    # NetworkX-created patch applied on Neo4j
    for f in os.listdir(nx_pipeline.patch_dir):
        os.replace(os.path.join(nx_pipeline.patch_dir, f), os.path.join("patch_data", f))
    assert neo4j_checkout(neo4j_db, file_init, "ts1", "ts2") == load(file_updt)
