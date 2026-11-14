import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from graph_patch.context_relations import context_relation_delta  # noqa: E402

# GeomRepresentation_01: proxy c2 switches its Representation from its own shape s35 (pushout) ... here
# modelled with both shapes equivalent: c2 -> s35 in v1 becomes c2 -> s31 in v2.
PARTNER = {"v1": {"c1": "C1", "c2": "C2", "s31": "S31", "s35": "S35"},
           "v2": {"C1": "c1", "C2": "c2", "S31": "s31", "S35": "s35"}}
PATHS = {"v1": {"c1": "P1", "c2": "P2", "s31": "P1/r", "s35": "P2/r"},
         "v2": {"C1": "P1", "C2": "P2", "S31": "P1/r", "S35": "P2/r"}}


def test_unchanged_relations_produce_no_delta():
    edges = {"v1": [("c1", "s31", "Representation", 0)], "v2": [("C1", "S31", "Representation", 0)]}
    assert context_relation_delta(edges, PARTNER, PATHS, "v1", "v2") == {"v1": [], "v2": []}


def test_retargeted_relation():
    edges = {"v1": [("c1", "s31", "Representation", 0), ("c2", "s35", "Representation", 0)],
             "v2": [("C1", "S31", "Representation", 0), ("C2", "S31", "Representation", 0)]}
    delta = context_relation_delta(edges, PARTNER, PATHS, "v1", "v2")
    assert delta["v1"] == [{"source": {"v1": "P2", "v2": "P2"}, "target": {"v1": "P2/r", "v2": "P2/r"},
                            "rel_type": "Representation", "list_index": 0}]
    assert delta["v2"] == [{"source": {"v2": "P2", "v1": "P2"}, "target": {"v2": "P1/r", "v1": "P1/r"},
                            "rel_type": "Representation", "list_index": 0}]


def test_list_index_change_is_a_delta():
    edges = {"v1": [("c1", "s31", "Items", 0)], "v2": [("C1", "S31", "Items", 1)]}
    delta = context_relation_delta(edges, PARTNER, PATHS, "v1", "v2")
    assert len(delta["v1"]) == 1 and len(delta["v2"]) == 1
