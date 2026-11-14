import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from neo4j_core.neo4j_model import Node, PrimaryNode  # noqa: E402

# A module-level name "Node" in an importing module (like pytest's runner) must not hijack the
# relationship target class.
from _pytest.nodes import Node as PytestNode  # noqa: E402,F401


def test_relationships_target_the_model_node_class():
    for rel in (Node.relation_to, Node.relation_from, Node.equivalent_to, PrimaryNode.equivalent_to):
        rel.lookup_node_class()
        assert rel.definition["node_class"] is Node
