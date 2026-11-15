"""
RDF interface: TBox/ABox partitioning, round trips, and ConMan2 diff/patch on RDF graphs.

NetworkX tests need no database; Neo4j tests are opt-in via CONMAN2_TEST_NEO4J_URI (they wipe that DB).
"""
import contextlib
import io
import os
import sys

import pytest
from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import OWL, RDF, RDFS, XSD

root_dir = os.path.dirname(os.path.dirname(__file__))
src_dir = os.path.join(root_dir, "src")
sys.path.insert(0, src_dir)

from rdf_graph_interface.RdfGraphInterface import (  # noqa: E402
    RdfGraphInterface, load_rdf, project_slug, validate_project_id)
from rdf_graph_interface.tbox_abox import partition, tbox_fingerprint  # noqa: E402
from graph_diff.GraphDiffNx import GraphDiffNx  # noqa: E402
from graph_patch.GraphPatchNx import GraphPatchNx  # noqa: E402

OFFICE = [os.path.join(src_dir, "00_sampleData", "RDF", "lbd_office", f"office_v{i}.ttl") for i in range(1, 5)]
PAIRS = list(zip(OFFICE, OFFICE[1:]))
PAIR_IDS = [f"v{i + 1}-v{i + 2}" for i in range(len(PAIRS))]
PID = "example.org_tum_office-building"
EX = Namespace("https://example.org/tum/office#")
INST = Namespace("https://example.org/tum/office-building/")
NEO4J_TEST_URI = os.environ.get("CONMAN2_TEST_NEO4J_URI")
requires_neo4j = pytest.mark.skipif(not NEO4J_TEST_URI, reason="CONMAN2_TEST_NEO4J_URI not set")


def quiet(f, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return f(*a, **k)


def abox(path):
    return partition(load_rdf(path))[0]


def nx_roundtrip(tmp_path, g, mode="exclude", ts="t1", project_id="test"):
    gi = RdfGraphInterface("networkx", tbox_mode=mode)
    graph_file = str(tmp_path / f"{ts}.json")
    versioned, tbox_meta = gi.split(g)
    gi.rdflib_2_graph(versioned, ts, project_id, tbox_meta, graph_file=graph_file)
    return gi.graph_2_rdflib(ts, graph_file=graph_file)


# ----------------------------------------------------------------------
# TBox / ABox partitioning
# ----------------------------------------------------------------------

def test_partition_counts():
    g = load_rdf(OFFICE[0])
    a, t = partition(g)
    assert (len(g), len(a), len(t)) == (79, 64, 15)


def test_partition_rules():
    a, t = partition(load_rdf(OFFICE[0]))
    assert (EX.Office, RDFS.subClassOf, URIRef("https://w3id.org/bot#Space")) in t       # class axiom
    assert (EX.Office, RDFS.label, Literal("Office", lang="en")) in t                    # label of a class
    assert any(t.triples((None, OWL.onProperty, EX.hasProperty)))                         # restriction bnode
    assert (URIRef("https://example.org/tum/office-building"), OWL.imports, URIRef("https://w3id.org/bot")) in t  # header
    assert (INST.space001, RDF.type, EX.Office) in a                                      # instance typing = ABox
    assert (INST.door1, RDF.type, EX.FireDoor) in a
    assert not any(a.triples((None, OWL.onProperty, None)))


def test_tbox_only_change_leaves_abox_unchanged():
    g1 = load_rdf(OFFICE[0])
    g2 = load_rdf(OFFICE[0])
    g2.add((EX.MeetingRoom, RDF.type, OWL.Class))
    a1, t1 = partition(g1)
    a2, t2 = partition(g2)
    assert isomorphic(a1, a2)
    assert tbox_fingerprint(t1)["sha256"] != tbox_fingerprint(t2)["sha256"]


def test_fingerprint_independent_of_serialisation_and_bnode_labels(tmp_path):
    g = load_rdf(OFFICE[0])
    nt = tmp_path / "office.nt"
    g.serialize(destination=str(nt), format="nt", encoding="utf-8")
    t_ttl = partition(g)[1]
    t_nt = partition(load_rdf(str(nt)))[1]
    assert tbox_fingerprint(t_ttl) == tbox_fingerprint(t_nt)
    assert tbox_fingerprint(t_ttl)["imports"] == ["https://w3id.org/bot"]


# ----------------------------------------------------------------------
# Round trip
# ----------------------------------------------------------------------

@pytest.mark.parametrize("path", OFFICE, ids=[os.path.basename(p) for p in OFFICE])
@pytest.mark.parametrize("mode", ["exclude", "include"])
def test_sample_roundtrip_networkx(tmp_path, path, mode):
    g = load_rdf(path)
    out, meta = nx_roundtrip(tmp_path, g, mode)
    assert isomorphic(out, partition(g)[0] if mode == "exclude" else g)
    assert (meta["tbox"] is not None) == (mode == "exclude")


def test_file_api_and_project_id(tmp_path):
    gi = RdfGraphInterface("networkx")
    quiet(gi.rdf_2_graph, OFFICE[0], "t1", graph_file=str(tmp_path / "g.json"))
    out_file = tmp_path / "out.ttl"
    out = quiet(gi.graph_2_rdf, str(out_file), "t1", graph_file=str(tmp_path / "g.json"))
    assert isomorphic(load_rdf(str(out_file)), abox(OFFICE[0]))
    assert dict(out.namespaces())["bot"] == URIRef("https://w3id.org/bot#")
    _, meta = gi.graph_2_rdflib("t1", graph_file=str(tmp_path / "g.json"))
    assert meta["project_id"] == PID and meta["dataset_iri"] == "https://example.org/tum/office-building"
    assert RdfGraphInterface.get_project_id_from_rdf_path(OFFICE[0]) == PID


def test_literal_fidelity_root_bnodes_cycles_and_lists(tmp_path):
    g = Graph()
    s = URIRef("urn:x:s")
    for lit in [Literal("1.0", datatype=XSD.decimal), Literal("1.00", datatype=XSD.decimal), Literal("Wand", lang="de"),
                Literal("wall", lang="en"), Literal('multi\nline "quoted"'), Literal(True), Literal(42)]:
        g.add((s, URIRef("urn:x:p"), lit))
    root = BNode()
    g.add((root, RDFS.comment, Literal("root bnode")))
    b1, b2 = BNode(), BNode()               # a blank-node cycle without IRI anchor
    g.add((b1, URIRef("urn:x:next"), b2))
    g.add((b2, URIRef("urn:x:next"), b1))
    shared = BNode()                        # shared by two subjects
    g.add((s, URIRef("urn:x:q"), shared))
    g.add((URIRef("urn:x:t"), URIRef("urn:x:q"), shared))
    g.add((shared, RDFS.label, Literal("shared")))
    out, _ = nx_roundtrip(tmp_path, g, "include")
    assert isomorphic(out, g)


def test_project_ids():
    assert project_slug("https://example.org/tum/office-building") == "example.org_tum_office-building"
    with pytest.raises(ValueError):
        validate_project_id("https://bad/id")


def test_missing_project_id_raises(tmp_path):
    f = tmp_path / "x.ttl"
    f.write_text("<urn:a> <urn:b> <urn:c> .\n")
    with pytest.raises(ValueError, match="project_id"):
        quiet(RdfGraphInterface("networkx").rdf_2_graph, str(f), "t1", graph_file=str(tmp_path / "g.json"))


def test_unsupported_extension():
    with pytest.raises(ValueError):
        load_rdf("model.xml")


# ----------------------------------------------------------------------
# ConMan2 diff / patch on RDF (NetworkX)
# ----------------------------------------------------------------------

def nx_commit(tmp_path, a_file, b_file):
    gi = RdfGraphInterface("networkx")
    quiet(gi.rdf_2_graph, a_file, "t1", graph_file=str(tmp_path / "a.json"))
    quiet(gi.rdf_2_graph, b_file, "t2", graph_file=str(tmp_path / "b.json"))
    diff = GraphDiffNx.from_files(str(tmp_path / "a.json"), str(tmp_path / "b.json"))
    eq = diff.run_diff("t1", "t2", root_entity_type="RdfDataset")
    patch = GraphPatchNx()
    patch.create_patch(PID, "t1", "t2", diff.graph_init, diff.graph_updt, eq, patch_dir=str(tmp_path / "patches"))
    return gi, diff, patch


def nx_apply(tmp_path, gi, src_file, src, dst):
    quiet(gi.rdf_2_graph, src_file, src, graph_file=str(tmp_path / f"apply_{src}.json"))
    GraphPatchNx().apply_patch(PID, src, dst, graph_file_init=str(tmp_path / f"apply_{src}.json"),
                               graph_file_updt=str(tmp_path / f"applied_{dst}.json"), patch_dir=str(tmp_path / "patches"))
    return gi.graph_2_rdflib(dst, graph_file=str(tmp_path / f"applied_{dst}.json"))[0]


@pytest.mark.parametrize("a_file,b_file", PAIRS, ids=PAIR_IDS)
def test_nx_conman_patch_on_rdf_forward_and_reverse(tmp_path, a_file, b_file):
    gi, _, _ = nx_commit(tmp_path, a_file, b_file)
    assert isomorphic(nx_apply(tmp_path, gi, a_file, "t1", "t2"), abox(b_file))
    assert isomorphic(nx_apply(tmp_path, gi, b_file, "t2", "t1"), abox(a_file))


def test_v1_v2_tbox_change_is_only_a_fingerprint_change(tmp_path):
    _, _, patch = nx_commit(tmp_path, OFFICE[0], OFFICE[1])
    root = patch.semantic_patch_pattern[f"[primary_node={PID}]"]
    assert set(root) == {"meta__tbox"}
    assert not any("MeetingRoom" in k for k in patch.semantic_patch_pattern)
    literal_changes = {str(c["wrappedValue"]["t1"]): str(c["wrappedValue"]["t2"])
                       for c in patch.semantic_patch_pattern.values() if "wrappedValue" in c}
    assert literal_changes['"F90"'] == '"F120"'


def test_renamed_resource_is_not_matched_to_its_old_iri(tmp_path):
    diff = nx_commit(tmp_path, OFFICE[2], OFFICE[3])[1]
    desk1 = f"r:{INST.desk1}"
    assert desk1 not in diff.init_to_updt


def test_retargeted_relation_is_a_context_relation(tmp_path):
    _, _, patch = nx_commit(tmp_path, OFFICE[1], OFFICE[2])
    ctx = patch.topological_patch_pattern["context_relations"]
    removed = [(e["source"]["t1"], e["target"]["t1"]) for e in ctx["t1"] if e["rel_type"].endswith("containsElement")]
    added = [(e["source"]["t2"], e["target"]["t2"]) for e in ctx["t2"] if e["rel_type"].endswith("containsElement")]
    assert removed == [(f"[primary_node={INST.space001}]", f"[primary_node={INST.desk1}]")]
    assert (f"[primary_node={INST.space101}]", f"[primary_node={INST.desk1}]") in added


# ----------------------------------------------------------------------
# Neo4j (opt-in)
# ----------------------------------------------------------------------

@pytest.fixture
def neo4j_db(tmp_path, monkeypatch):
    from neomodel import config, db
    config.DATABASE_URL = NEO4J_TEST_URI
    monkeypatch.chdir(tmp_path)
    db.cypher_query("MATCH (n) DETACH DELETE n")
    yield db
    db.cypher_query("MATCH (n) DETACH DELETE n")


@requires_neo4j
@pytest.mark.parametrize("path", OFFICE, ids=[os.path.basename(p) for p in OFFICE])
def test_sample_roundtrip_neo4j(neo4j_db, path):
    gi = RdfGraphInterface("neo4j")
    quiet(gi.rdf_2_graph, path, "t1")
    assert isomorphic(gi.graph_2_rdflib("t1")[0], abox(path))
    assert RdfGraphInterface.get_timestamp_from_project_id(PID) == ["t1"]


@requires_neo4j
@pytest.mark.parametrize("a_file,b_file", PAIRS, ids=PAIR_IDS)
def test_neo4j_conman_patch_on_rdf_forward_and_reverse(neo4j_db, a_file, b_file):
    from graph_diff.GraphDiff import GraphDiff
    from graph_patch.GraphPatch import GraphPatch
    gi = RdfGraphInterface("neo4j")
    quiet(gi.rdf_2_graph, a_file, "t1")
    quiet(gi.rdf_2_graph, b_file, "t2")
    quiet(GraphDiff().run_diff, "t1", "t2", root_entity_type="RdfDataset")
    quiet(GraphPatch().create_patch, PID, "t1", "t2")
    for src_file, src, dst, ref in ((a_file, "t1", "t2", b_file), (b_file, "t2", "t1", a_file)):
        neo4j_db.cypher_query("MATCH (n) DETACH DELETE n")
        quiet(gi.rdf_2_graph, src_file, src)
        quiet(GraphPatch().apply_patch, PID, src, dst)
        assert isomorphic(gi.graph_2_rdflib(dst)[0], abox(ref)), f"{src}->{dst}"
