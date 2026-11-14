import glob
import json
import os
import sys

import pytest

root_dir = os.path.dirname(os.path.dirname(__file__))
src_dir = os.path.join(root_dir, "src")
sys.path.insert(0, src_dir)

from geojson_graph_interface.GeoJsonGraphInterface import (  # noqa: E402
    GeoJsonGraphInterface, escape_key, unescape_key, ESC)
from networkX_core.networkx_connection import networkxConnection  # noqa: E402

SAMPLE_DIR = os.path.join(src_dir, "00_sampleData", "GeoJSON")
SAMPLE_FILES = sorted(glob.glob(os.path.join(SAMPLE_DIR, "*", "*.geojson")))

# Neo4j integration tests only run against an explicitly configured (throwaway!) database, e.g.
#   CONMAN2_TEST_NEO4J_URI=bolt://neo4j:password@localhost:7688 pytest tests
# They delete all data in that database.
NEO4J_TEST_URI = os.environ.get("CONMAN2_TEST_NEO4J_URI")
requires_neo4j = pytest.mark.skipif(not NEO4J_TEST_URI, reason="CONMAN2_TEST_NEO4J_URI not set")


def write(tmp_path, obj, name="in.geojson"):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def nx_roundtrip(tmp_path, path, project_id=None, ts="ts1"):
    gi = GeoJsonGraphInterface("networkx")
    graph_file = str(tmp_path / f"g_{ts}.json")
    d = gi.geojson_2_graph(path, ts, project_id=project_id, graph_file=graph_file)
    out = gi.graph_2_geojson(None, ts, graph_file=graph_file)
    return d, out, graph_file


def load_nx(graph_file):
    c = networkxConnection()
    c.load_graph(graph_file)
    return c.graph


@pytest.fixture
def minimal_fc():
    return {
        "type": "FeatureCollection",
        "id": "proj",
        "features": [
            {"type": "Feature", "id": "a", "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
             "properties": {"name": "A"}},
            {"type": "Feature", "geometry": None, "properties": None},
        ],
    }


# ----------------------------------------------------------------------
# Round trip of all sample files
# ----------------------------------------------------------------------

@pytest.mark.parametrize("path", SAMPLE_FILES, ids=[os.path.basename(p) for p in SAMPLE_FILES])
def test_sample_roundtrip_networkx(tmp_path, path):
    orig = json.load(open(path, encoding="utf-8"))
    pid = None if "id" in orig else "explicit-project"
    _, out, _ = nx_roundtrip(tmp_path, path, project_id=pid)
    assert out == orig


def test_samples_exist():
    assert len(SAMPLE_FILES) >= 10


# ----------------------------------------------------------------------
# Mapping onto the meta model
# ----------------------------------------------------------------------

def test_node_classification(tmp_path, minimal_fc):
    d, _, graph_file = nx_roundtrip(tmp_path, write(tmp_path, minimal_fc))
    g = load_nx(graph_file)
    by_label = {}
    for _, data in g.nodes(data=True):
        by_label.setdefault(data["label"], []).append(data["EntityType"])
    assert sorted(by_label["PrimaryNode"]) == ["Feature", "FeatureCollection"]
    assert by_label["ConnectionNode"] == ["FeatureMembership"]
    # id-less feature, the Point geometry, the Properties node
    assert sorted(by_label["SecondaryNode"]) == ["Feature", "Point", "Properties"]
    assert by_label["InlineNode"] == ["Position"]


def test_membership_connection_node(tmp_path, minimal_fc):
    _, _, graph_file = nx_roundtrip(tmp_path, write(tmp_path, minimal_fc))
    g = load_nx(graph_file)
    conn = [n for n, data in g.nodes(data=True) if data["label"] == "ConnectionNode"][0]
    assert g.nodes[conn]["GlobalId"] == "proj::a"
    assert g.nodes[conn]["member_index"] == 0
    targets = {data["rel_type"]: g.nodes[v]["EntityType"] for _, v, data in g.out_edges(conn, data=True)}
    assert targets == {"RelatingCollection": "FeatureCollection", "RelatedFeature": "Feature"}


def test_idless_feature_attached_by_position(tmp_path, minimal_fc):
    _, _, graph_file = nx_roundtrip(tmp_path, write(tmp_path, minimal_fc))
    g = load_nx(graph_file)
    root = [n for n, data in g.nodes(data=True) if data["EntityType"] == "FeatureCollection"][0]
    edges = [data for _, v, data in g.out_edges(root, data=True) if g.nodes[v]["EntityType"] == "Feature"]
    assert edges == [{"rel_type": "features", "list_index": 1}]


def test_polygon_decomposition(tmp_path):
    fc = {"type": "FeatureCollection", "id": "p", "features": [{
        "type": "Feature", "id": "f", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [
            [[0, 0], [1, 0], [1, 1], [0, 0]],
            [[0.2, 0.2], [0.2, 0.4], [0.4, 0.2], [0.2, 0.2]]]}}]}
    d, out, _ = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert [n["EntityType"] for n in d.secondary_nodes].count("LinearRing") == 2
    assert len([p for p in d.inline_patterns if p["props"]["EntityType"] == "Position"]) == 8
    assert out == fc


def test_null_vs_empty_vs_missing(tmp_path):
    fc = {"type": "FeatureCollection", "id": "p", "features": [
        {"type": "Feature", "id": "1", "geometry": None, "properties": None},
        {"type": "Feature", "id": "2", "geometry": None, "properties": {}},
        {"type": "Feature", "id": "3", "geometry": None, "properties": {"v": None, "e": [], "o": {}}},
    ]}
    _, out, _ = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert out == fc


def test_value_types_are_preserved(tmp_path):
    props = {"s": "1", "i": 1, "f": 1.0, "b": True, "n": None, "arr": [1, "x", None],
             "objs": [{"k": 1}, {"k": [1, 2]}], "mixed": [1, {"a": 2}, [3, {"b": 4}]],
             "nested": {"deep": {"deeper": "x"}}, "paren": "(not a tuple)"}
    fc = {"type": "FeatureCollection", "id": "p",
          "features": [{"type": "Feature", "id": "f", "geometry": None, "properties": props}]}
    _, out, _ = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert out == fc
    assert type(out["features"][0]["properties"]["f"]) is float
    assert type(out["features"][0]["properties"]["i"]) is int


def test_numeric_ids(tmp_path):
    fc = {"type": "FeatureCollection", "id": 7,
          "features": [{"type": "Feature", "id": 42, "geometry": None, "properties": {}},
                       {"type": "Feature", "id": 4.5, "geometry": None, "properties": {}}]}
    _, out, _ = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert out == fc
    assert out["features"][0]["id"] == 42 and isinstance(out["features"][0]["id"], int)


def test_reserved_keys_are_escaped(tmp_path):
    props = {"timestamp": "2020", "EntityType": "x", "GlobalId": "g", "id": 3, "save": "s",
             "label": "l", ESC + "already": 1, "_json_keys": "meta?"}
    fc = {"type": "FeatureCollection", "id": "p",
          "features": [{"type": "Feature", "id": "f", "geometry": None, "properties": props}]}
    d, out, graph_file = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert out == fc
    pnode = [n for n in d.secondary_nodes if n["EntityType"] == "Properties"][0]
    assert pnode["timestamp"] == "ts1"            # bookkeeping not overwritten
    assert pnode[ESC + "timestamp"] == "2020"


def test_escape_is_reversible():
    for k in ["name", "timestamp", ESC + "x", "addr:city", "_private", "name:ru", "Straße", "1st", "",
              "a b", "a_b", "emoji\U0001F600", "_esc_", "with-dash"]:
        assert unescape_key(escape_key(k)) == k


def test_escaped_keys_are_identifiers():
    import re
    for k in ["addr:city", "name:ru", "Straße", "1st", "a b", "timestamp", "id", "save"]:
        assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", escape_key(k)), k
    assert escape_key("addr:city") == "_esc_addr_3acity"
    assert escape_key("name") == "name"


def test_foreign_members_and_bbox(tmp_path):
    fc = {"type": "FeatureCollection", "id": "p", "bbox": [0, 0, 1, 1], "name": "n",
          "meta": {"author": "x"},
          "features": [{"type": "Feature", "id": "f", "bbox": [0, 0, 1, 1], "title": "t",
                        "geometry": {"type": "Point", "coordinates": [0, 0], "bbox": [0, 0, 0, 0]},
                        "properties": {}}]}
    _, out, _ = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert out == fc


def test_empty_geometries(tmp_path):
    fc = {"type": "FeatureCollection", "id": "p", "features": [
        {"type": "Feature", "id": "a", "properties": {}, "geometry": {"type": "MultiPoint", "coordinates": []}},
        {"type": "Feature", "id": "b", "properties": {}, "geometry": {"type": "GeometryCollection", "geometries": []}},
        {"type": "Feature", "id": "c", "properties": {}, "geometry": {"type": "Point", "coordinates": []}},
    ]}
    _, out, _ = nx_roundtrip(tmp_path, write(tmp_path, fc))
    assert out == fc


# ----------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------

def test_missing_project_id_raises(tmp_path):
    with pytest.raises(ValueError, match="no 'id'"):
        nx_roundtrip(tmp_path, write(tmp_path, {"type": "FeatureCollection", "features": []}))


def test_contradicting_project_id_raises(tmp_path):
    with pytest.raises(ValueError, match="contradicts"):
        nx_roundtrip(tmp_path, write(tmp_path, {"type": "FeatureCollection", "id": "a", "features": []}),
                     project_id="b")


def test_duplicate_feature_ids_raise(tmp_path):
    fc = {"type": "FeatureCollection", "id": "p", "features": [
        {"type": "Feature", "id": "x", "geometry": None, "properties": {}},
        {"type": "Feature", "id": "x", "geometry": None, "properties": {}}]}
    with pytest.raises(ValueError, match="Duplicate"):
        nx_roundtrip(tmp_path, write(tmp_path, fc))


def test_non_featurecollection_raises(tmp_path):
    with pytest.raises(NotImplementedError):
        nx_roundtrip(tmp_path, write(tmp_path, {"type": "Point", "coordinates": [0, 0]}))


def test_unknown_geometry_type_raises(tmp_path):
    fc = {"type": "FeatureCollection", "id": "p", "features": [
        {"type": "Feature", "id": "x", "geometry": {"type": "Circle", "coordinates": [0, 0]}, "properties": {}}]}
    with pytest.raises(ValueError, match="Circle"):
        nx_roundtrip(tmp_path, write(tmp_path, fc))


def test_invalid_provider():
    with pytest.raises(ValueError):
        GeoJsonGraphInterface("rdf")


def test_project_id_from_path(tmp_path, minimal_fc):
    assert GeoJsonGraphInterface.get_project_id_from_geojson_path(write(tmp_path, minimal_fc)) == "proj"


# ----------------------------------------------------------------------
# Neo4j integration (opt-in)
# ----------------------------------------------------------------------

@pytest.fixture
def neo4j_db():
    from neomodel import config, db
    config.DATABASE_URL = NEO4J_TEST_URI
    db.cypher_query("MATCH (n) DETACH DELETE n")
    yield db
    db.cypher_query("MATCH (n) DETACH DELETE n")


@requires_neo4j
@pytest.mark.parametrize("path", SAMPLE_FILES, ids=[os.path.basename(p) for p in SAMPLE_FILES])
def test_sample_roundtrip_neo4j(neo4j_db, path):
    orig = json.load(open(path, encoding="utf-8"))
    pid = None if "id" in orig else "explicit-project"
    gi = GeoJsonGraphInterface("neo4j")
    gi.geojson_2_graph(path, "ts1", project_id=pid)
    assert gi.graph_2_geojson(None, "ts1") == orig


@requires_neo4j
def test_neo4j_and_networkx_build_same_graph(neo4j_db, tmp_path):
    path = os.path.join(SAMPLE_DIR, "citygml_campus", "campus_v1.geojson")
    GeoJsonGraphInterface("neo4j").geojson_2_graph(path, "ts1")
    _, _, graph_file = nx_roundtrip(tmp_path, path)
    g = load_nx(graph_file)
    rows, _ = neo4j_db.cypher_query("MATCH (n:Node {timestamp:'ts1'}) RETURN n.EntityType, count(*)")
    neo = dict(rows)
    nx_counts = {}
    for _, data in g.nodes(data=True):
        nx_counts[data["EntityType"]] = nx_counts.get(data["EntityType"], 0) + 1
    assert neo == nx_counts
    rows, _ = neo4j_db.cypher_query("MATCH (:Node {timestamp:'ts1'})-[r:rel]->() RETURN count(r)")
    assert rows[0][0] == g.number_of_edges()


@requires_neo4j
def test_project_timestamps_neo4j(neo4j_db):
    path = os.path.join(SAMPLE_DIR, "citygml_campus", "campus_v1.geojson")
    GeoJsonGraphInterface("neo4j").geojson_2_graph(path, "ts1")
    GeoJsonGraphInterface("neo4j").geojson_2_graph(path, "ts2")
    assert sorted(GeoJsonGraphInterface.get_timestamp_from_project_id("tum-campus-citygml3-demo")) == ["ts1", "ts2"]


def test_p21_ids_are_stable_across_feature_insertion(tmp_path, minimal_fc):
    d1, _, _ = nx_roundtrip(tmp_path, write(tmp_path, minimal_fc, "a.geojson"), ts="a")
    shifted = json.loads(json.dumps(minimal_fc))
    shifted["features"].insert(0, {"type": "Feature", "id": "new", "geometry": None, "properties": {}})
    d2, _, _ = nx_roundtrip(tmp_path, write(tmp_path, shifted, "b.geojson"), ts="b")
    keys = lambda d: {n["p21_id"] for n in d.primary_nodes + d.connection_nodes + d.secondary_nodes}
    # all identified nodes of version a keep their key; only the id-less feature moves (by position)
    assert keys(d1) - keys(d2) == {"fc/features/1"}
    all_keys = [n["p21_id"] for n in d2.primary_nodes + d2.connection_nodes + d2.secondary_nodes]
    assert len(all_keys) == len(set(all_keys))
