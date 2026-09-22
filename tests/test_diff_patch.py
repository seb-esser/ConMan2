import pytest
import json
import networkx as nx
from unittest.mock import MagicMock, patch, mock_open
import os
import sys

root_dir = os.path.dirname(os.path.dirname(__file__))
src_dir = os.path.join(root_dir, 'src')
sys.path.insert(0, src_dir)

from graph_diff.GraphDiff import GraphDiff
from graph_patch.GraphPatch import GraphPatch
from neo4j_core.neo4j_model import PrimaryNode, ConnectionNode

# ----------------------------------------------------------------------
# Helper function: Create neomodel Node Mock object for testing
# ----------------------------------------------------------------------

def create_mock_node(global_id, element_id, entity_type, timestamp, node_class=MagicMock, **kwargs):
    """Build a node containing relationship managers based on GraphDiff and GraphPatch source code logic"""
    node = node_class()
    
    # Basic attributes
    node.GlobalId = global_id
    node.element_id = element_id
    node.EntityType = entity_type
    node.timestamp = timestamp
    
    # Build __properties__ dict (GraphPatch source code iterates over this dict directly)
    node.__properties__ = {
        "GlobalId": global_id,
        "EntityType": entity_type,
        "timestamp": timestamp,
        **kwargs
    }
    
    # Mock relationship managers (neomodel core components)
    node.relation_to = MagicMock()
    node.relation_from = MagicMock()
    node.equivalent_to = MagicMock()
    
    # Return empty lists by default to avoid iteration errors when not configured
    node.relation_to.all.return_value = []
    node.relation_from.all.return_value = []
    node.equivalent_to.all.return_value = []
    node.equivalent_to.filter.return_value = []
    
    return node

# ----------------------------------------------------------------------
# Helper function: Build a small NetworkX graph for networkx-path tests
# ----------------------------------------------------------------------

def build_nx_graph(nodes, edges=None):
    """nodes=[(node_id, attrs_dict), ...], edges=[(src_id, tgt_id, attrs_dict), ...]"""
    g = nx.MultiDiGraph()
    g.add_nodes_from(nodes)
    for src, tgt, attrs in (edges or []):
        g.add_edge(src, tgt, **attrs)
    return g

# ----------------------------------------------------------------------
# Tests for GraphDiff
# ----------------------------------------------------------------------

class TestGraphDiff:
    
    @pytest.fixture
    def diff_tool(self):
        diff = GraphDiff()
        # Source code calls self.unique_paths in create_equivalence_relations_connection
        diff.unique_paths = {} 
        return diff

    def test_create_equivalence_relations_primary(self, diff_tool):
        """Test recursive equivalence logic for PrimaryNode: establish connection when attributes and structure perfectly match"""
        init_node = create_mock_node("P1", "e1", "IfcWall", "v1")
        updt_node = create_mock_node("P1", "e2", "IfcWall", "v2")
        
        child_init = create_mock_node("C1", "e3", "IfcPropertySet", "v1")
        child_updt = create_mock_node("C1", "e4", "IfcPropertySet", "v2")
        
        init_node.relation_to.all.return_value = [child_init]
        updt_node.relation_to.all.return_value = [child_updt]
        
        # Mock rel_init and rel_updt from source code
        mock_rel_init = MagicMock(rel_type="IsDefinedBy", list_index=0)
        mock_rel_updt = MagicMock(rel_type="IsDefinedBy", list_index=0)
        init_node.relation_to.relationship.return_value = mock_rel_init
        updt_node.relation_to.relationship.return_value = mock_rel_updt
        
        diff_tool.create_equivalence_relations_primary(init_node, updt_node)
        
        # Verify equivalent_to.connect is called between child nodes
        child_init.equivalent_to.connect.assert_called_once_with(child_updt)

    def test_create_equivalence_relations_connection_global_id(self, diff_tool):
        """Test fast matching for ConnectionNode with identical GlobalId"""
        conn_init = create_mock_node("Rel_1", "c1", "IfcRelConnects", "v1")
        conn_updt = create_mock_node("Rel_1", "c2", "IfcRelConnects", "v2")
        
        diff_tool.create_equivalence_relations_connection(conn_init, conn_updt)
        conn_init.equivalent_to.connect.assert_called_once_with(conn_updt)

    def test_create_equivalence_relations_connection_iou(self, diff_tool):
        """Test IoU (Intersection over Union) matching logic for ConnectionNode without GlobalId"""
        conn_init = create_mock_node(None, "c1", "IfcRelConnects", "v1")
        conn_updt = create_mock_node(None, "c2", "IfcRelConnects", "v2")
        
        # Remove GlobalId attribute to force entering the IoU calculation branch
        del conn_init.GlobalId
        del conn_updt.GlobalId
        
        child_init = create_mock_node("w1", "e1", "IfcWall", "v1")
        child_updt = create_mock_node("w1", "e2", "IfcWall", "v2")
        
        conn_init.relation_to.all.return_value = [child_init]
        conn_updt.relation_to.all.return_value = [child_updt]
        
        # Mock condition for common_children_count += 1: child_init can find child_updt as equivalent node
        child_init.equivalent_to.relationship.return_value = MagicMock()
        
        diff_tool.create_equivalence_relations_connection(conn_init, conn_updt)
        
        # IoU calculates to 1.0, verify equivalent connection is established and unique_paths are recorded
        # IoU calculates to 1.0, verify equivalent connection is established without requiring a GlobalId
        conn_init.equivalent_to.connect.assert_called_once_with(conn_updt)

        assert diff_tool.unique_paths == {}

    @patch('graph_diff.GraphDiff.Node')
    @patch('graph_diff.GraphDiff.PrimaryNode')
    @patch('graph_diff.GraphDiff.ConnectionNode')
    def test_run_diff(self, mock_conn, mock_primary, mock_node, diff_tool):
        """Test the entry call for the full Diff pipeline"""
        proj_init = create_mock_node("proj1", "p1", "IfcProject", "v1")
        proj_updt = create_mock_node("proj1", "p2", "IfcProject", "v2")
        mock_node.nodes.get.side_effect = [proj_init, proj_updt]
        
        mock_primary.nodes.filter.return_value = []
        mock_conn.nodes.filter.return_value = []
        
        diff_tool.run_diff("v1", "v2")
        proj_init.equivalent_to.connect.assert_called_once_with(proj_updt)

# ----------------------------------------------------------------------
# Tests for GraphDiff (NetworkX)
# ----------------------------------------------------------------------

class TestGraphDiffNetworkX:

    @pytest.fixture
    def nx_diff_tool(self):
        return GraphDiff(graph_provider="networkx")

    def test_record_equivalence_both_directions(self, nx_diff_tool):
        """_record_equivalence must write both directions so lookups work from either side"""
        nx_diff_tool._record_equivalence("v1", "#1", "v2", "#10")
        assert nx_diff_tool.equivalences[("v1", "#1")] == ("v2", "#10")
        assert nx_diff_tool.equivalences[("v2", "#10")] == ("v1", "#1")

    def test_create_equivalence_relations_primary_matches_children(self, nx_diff_tool):
        """Children matched by rel_type + list_index + EntityType, recursively"""
        graph_init = build_nx_graph(
            nodes=[
                ("#1", {"EntityType": "IfcProject", "timestamp": "v1", "label": "PrimaryNode"}),
                ("#2", {"EntityType": "IfcWall", "timestamp": "v1", "label": "PrimaryNode"}),
            ],
            edges=[("#1", "#2", {"rel_type": "Decomposes", "list_index": 0})],
        )
        graph_updt = build_nx_graph(
            nodes=[
                ("#10", {"EntityType": "IfcProject", "timestamp": "v2", "label": "PrimaryNode"}),
                ("#20", {"EntityType": "IfcWall", "timestamp": "v2", "label": "PrimaryNode"}),
            ],
            edges=[("#10", "#20", {"rel_type": "Decomposes", "list_index": 0})],
        )
        nx_diff_tool._nx_graph_cache["v1"] = graph_init
        nx_diff_tool._nx_graph_cache["v2"] = graph_updt

        project_init = ("#1", graph_init.nodes["#1"])
        project_updt = ("#10", graph_updt.nodes["#10"])
        nx_diff_tool.create_equivalence_relations_primary(project_init, project_updt)

        assert nx_diff_tool.equivalences[("v1", "#2")] == ("v2", "#20")
        assert nx_diff_tool.equivalences[("v2", "#20")] == ("v1", "#2")

    def test_create_equivalence_relations_connection_global_id(self, nx_diff_tool):
        """ConnectionNodes with matching GlobalId are matched without IoU"""
        graph_init = build_nx_graph(nodes=[
            ("#5", {"EntityType": "IfcRelContainedInSpatialStructure", "GlobalId": "Rel_1", "timestamp": "v1", "label": "ConnectionNode"}),
        ])
        graph_updt = build_nx_graph(nodes=[
            ("#50", {"EntityType": "IfcRelContainedInSpatialStructure", "GlobalId": "Rel_1", "timestamp": "v2", "label": "ConnectionNode"}),
        ])
        nx_diff_tool._nx_graph_cache["v1"] = graph_init
        nx_diff_tool._nx_graph_cache["v2"] = graph_updt

        conn_init = ("#5", graph_init.nodes["#5"])
        conn_updt = ("#50", graph_updt.nodes["#50"])
        nx_diff_tool.create_equivalence_relations_connection(conn_init, conn_updt)

        assert nx_diff_tool.equivalences[("v1", "#5")] == ("v2", "#50")

    def test_create_equivalence_relations_connection_iou(self, nx_diff_tool):
        """ConnectionNodes without GlobalId are matched via IoU when all children are equivalent"""
        graph_init = build_nx_graph(
            nodes=[
                ("#5", {"EntityType": "IfcRelConnects", "timestamp": "v1", "label": "ConnectionNode"}),
                ("#6", {"EntityType": "IfcWall", "timestamp": "v1", "label": "PrimaryNode"}),
            ],
            edges=[("#5", "#6", {"rel_type": "RelatedElement", "list_index": 0})],
        )
        graph_updt = build_nx_graph(
            nodes=[
                ("#50", {"EntityType": "IfcRelConnects", "timestamp": "v2", "label": "ConnectionNode"}),
                ("#60", {"EntityType": "IfcWall", "timestamp": "v2", "label": "PrimaryNode"}),
            ],
            edges=[("#50", "#60", {"rel_type": "RelatedElement", "list_index": 0})],
        )
        nx_diff_tool._nx_graph_cache["v1"] = graph_init
        nx_diff_tool._nx_graph_cache["v2"] = graph_updt
        # Simulate that create_equivalence_relations_primary already matched the children
        nx_diff_tool._record_equivalence("v1", "#6", "v2", "#60")

        conn_init = ("#5", graph_init.nodes["#5"])
        conn_updt = ("#50", graph_updt.nodes["#50"])
        nx_diff_tool.create_equivalence_relations_connection(conn_init, conn_updt)

        assert nx_diff_tool.equivalences[("v1", "#5")] == ("v2", "#50")
        # Neither side had a GlobalId, so unique_paths must not be populated.
        assert nx_diff_tool.unique_paths == {}

    def test_create_equivalence_relations_connection_iou_zero_denominator(self, nx_diff_tool):
        """Two childless, GlobalId-less ConnectionNodes must not raise ZeroDivisionError"""
        graph_init = build_nx_graph(nodes=[
            ("#5", {"EntityType": "IfcRelConnects", "timestamp": "v1", "label": "ConnectionNode"}),
        ])
        graph_updt = build_nx_graph(nodes=[
            ("#50", {"EntityType": "IfcRelConnects", "timestamp": "v2", "label": "ConnectionNode"}),
        ])
        nx_diff_tool._nx_graph_cache["v1"] = graph_init
        nx_diff_tool._nx_graph_cache["v2"] = graph_updt

        conn_init = ("#5", graph_init.nodes["#5"])
        conn_updt = ("#50", graph_updt.nodes["#50"])
        # Should return quietly, not raise
        nx_diff_tool.create_equivalence_relations_connection(conn_init, conn_updt)

        assert ("v1", "#5") not in nx_diff_tool.equivalences

    def test_run_diff_networkx_end_to_end(self, nx_diff_tool):
        """Full run_diff over a small Project + Wall + Connection graph pair"""
        graph_init = build_nx_graph(
            nodes=[
                ("#1", {"EntityType": "IfcProject", "GlobalId": "P1", "timestamp": "v1", "label": "PrimaryNode"}),
                ("#2", {"EntityType": "IfcWall", "GlobalId": "W1", "timestamp": "v1", "label": "PrimaryNode"}),
                ("#3", {"EntityType": "IfcRelConnects", "timestamp": "v1", "label": "ConnectionNode"}),
            ],
            edges=[
                ("#1", "#2", {"rel_type": "Decomposes", "list_index": 0}),
                ("#3", "#2", {"rel_type": "RelatedElement", "list_index": 0}),
            ],
        )
        graph_updt = build_nx_graph(
            nodes=[
                ("#10", {"EntityType": "IfcProject", "GlobalId": "P1", "timestamp": "v2", "label": "PrimaryNode"}),
                ("#20", {"EntityType": "IfcWall", "GlobalId": "W1", "timestamp": "v2", "label": "PrimaryNode"}),
                ("#30", {"EntityType": "IfcRelConnects", "timestamp": "v2", "label": "ConnectionNode"}),
            ],
            edges=[
                ("#10", "#20", {"rel_type": "Decomposes", "list_index": 0}),
                ("#30", "#20", {"rel_type": "RelatedElement", "list_index": 0}),
            ],
        )
        nx_diff_tool._nx_graph_cache["v1"] = graph_init
        nx_diff_tool._nx_graph_cache["v2"] = graph_updt

        nx_diff_tool.run_diff("v1", "v2")

        assert nx_diff_tool.equivalences[("v1", "#1")] == ("v2", "#10")  # project
        assert nx_diff_tool.equivalences[("v1", "#2")] == ("v2", "#20")  # wall via GlobalId
        assert nx_diff_tool.equivalences[("v1", "#3")] == ("v2", "#30")  # connection via IoU

    def test_run_diff_networkx_p21_id_collision_safe(self, nx_diff_tool):
        """
        Regression test: v1's IfcProject and v2's IfcWall deliberately share the same
        raw node id "#1" (p21_ids are local to each STEP file and can collide across
        versions). Equivalences must be keyed by (timestamp, node_id), not the bare
        node_id, or these two unrelated nodes would clobber each other's record.
        """
        graph_init = build_nx_graph(
            nodes=[
                ("#1", {"EntityType": "IfcProject", "GlobalId": "P1", "timestamp": "v1", "label": "PrimaryNode"}),
                ("#2", {"EntityType": "IfcWall", "GlobalId": "W1", "timestamp": "v1", "label": "PrimaryNode"}),
            ],
            edges=[("#1", "#2", {"rel_type": "Decomposes", "list_index": 0})],
        )
        graph_updt = build_nx_graph(
            nodes=[
                ("#10", {"EntityType": "IfcProject", "GlobalId": "P1", "timestamp": "v2", "label": "PrimaryNode"}),
                ("#1", {"EntityType": "IfcWall", "GlobalId": "W1", "timestamp": "v2", "label": "PrimaryNode"}),  # collides with v1's project id
            ],
            edges=[("#10", "#1", {"rel_type": "Decomposes", "list_index": 0})],
        )
        nx_diff_tool._nx_graph_cache["v1"] = graph_init
        nx_diff_tool._nx_graph_cache["v2"] = graph_updt

        nx_diff_tool.run_diff("v1", "v2")

        assert nx_diff_tool.equivalences[("v1", "#1")] == ("v2", "#10")  # project, unaffected by the collision
        assert nx_diff_tool.equivalences[("v2", "#1")] == ("v1", "#2")   # v2's wall (id "#1") maps to v1's wall, not v1's project
        assert len(nx_diff_tool.equivalences) == 4

# ----------------------------------------------------------------------
# Tests for GraphPatch
# ----------------------------------------------------------------------

class TestGraphPatch:
    
    @pytest.fixture
    def patch_tool(self):
        patch = GraphPatch()
        patch.node_ids_to_unique_paths_mapping = {"v1": {}, "v2": {}}
        patch.init_side_node_ids_to_unique_paths_mapping = {"v1": {}, "v2": {}}
        patch.topological_patch_pattern = {"v1": {}, "v2": {}}
        patch.semantic_patch_pattern = {}
        patch.nodes_to_delete = []
        return patch

    @patch('graph_patch.GraphPatch.DataHandler')
    def test_create_unique_path_mappings(self, mock_data_handler, patch_tool):
        """Verify recursive generation logic for unique node paths"""
        mock_data_handler.path_to_string.return_value = "mock_path_string"
        
        node = create_mock_node("Global_1", "e1", "IfcWall", "v1")
        # Force masquerade the node as a PrimaryNode instance to enter the corresponding path reset branch
        node.__class__ = PrimaryNode 
        
        patch_tool.create_unique_path_mappings(node, "v1")
        
        # Verify the converted string path is correctly stored in the dict
        assert "e1" in patch_tool.node_ids_to_unique_paths_mapping["v1"]
        assert patch_tool.node_ids_to_unique_paths_mapping["v1"]["e1"] == "mock_path_string"

    def test_create_semantic_patch_pattern(self, patch_tool):
        """Verify correct generation of semantic difference patches when modifying node attributes"""
        node_init = create_mock_node("P1", "e1", "IfcWall", "v1", Name="Wall A")
        node_updt = create_mock_node("P1", "e2", "IfcWall", "v2", Name="Wall B")
        
        # Remove element_id_property to prevent interception
        node_init.__properties__.pop("element_id_property", None)
        node_init.equivalent_to.all.return_value = [node_updt]
        
        path_string = "path_to_wall"
        patch_tool.node_ids_to_unique_paths_mapping["v1"]["e1"] = path_string
        
        patch_tool.create_semantic_patch_pattern([node_init], "v1", "v2")
        
        assert path_string in patch_tool.semantic_patch_pattern
        assert patch_tool.semantic_patch_pattern[path_string]["Name"]["v1"] == "Wall A"
        assert patch_tool.semantic_patch_pattern[path_string]["Name"]["v2"] == "Wall B"

    def test_create_topological_patch_pattern(self, patch_tool):
        """Verify serialization extraction of new nodes (pushout) and their topological context"""
        pushout_node = create_mock_node("P2", "e3", "IfcDoor", "v2")
        pushout_node.timestamp = "v2"
        
        # Mock an adjacent node without equivalent nodes (purely newly added) as relation_to
        adjacent_new = create_mock_node("P3", "e4", "IfcProperty", "v2")
        adjacent_new.equivalent_to.all.return_value = []
        
        # Mock an adjacent node with an equivalent node as context_to
        adjacent_context = create_mock_node("P4", "e5", "IfcWall", "v2")
        adjacent_context.equivalent_to.all.return_value = [True]
        patch_tool.node_ids_to_unique_paths_mapping["v2"]["e5"] = "context_path"
        
        pushout_node.relation_to.all.return_value = [adjacent_new, adjacent_context]
        
        # Mock relationship attribute extraction
        mock_rel = MagicMock()
        mock_rel.__properties__ = {"rel_type": "FillsVoid", "list_index": 0}
        pushout_node.relation_to.relationship.return_value = mock_rel
        
        patch_tool.create_topological_patch_pattern([pushout_node], "v2")
        
        # Verify the structure of the result dictionary
        pattern = patch_tool.topological_patch_pattern["v2"]["e3"]
        assert pattern["node_type"] == "MagicMock"
        assert "e4" in pattern["relation_to"]
        assert "e5" in pattern["context_to"]
        assert pattern["context_to"]["e5"]["path"] == "context_path"

    @patch('graph_patch.GraphPatch.os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    @patch('graph_patch.GraphPatch.Node')
    @patch('graph_patch.GraphPatch.PrimaryNode')
    @patch('graph_patch.GraphPatch.ConnectionNode')
    def test_create_patch_pipeline(self, mock_conn, mock_primary, mock_node, mock_file, mock_makedirs, patch_tool):
        """Test the complete Patch generation lifecycle and JSON writing"""
        # Simplify querysets to directly verify the pipeline runs smoothly
        mock_primary.nodes.filter.return_value = []
        mock_conn.nodes.filter.return_value = []
        
        # Mock Node.nodes.filter(timestamp=...).has(equivalent_to=False).all()
        mock_filter_qs = MagicMock()
        mock_filter_qs.has.return_value.all.return_value = []
        mock_node.nodes.filter.return_value = mock_filter_qs
        
        patch_tool.create_patch("Proj1", "v1", "v2")
        
        mock_makedirs.assert_called_with("patch_data", exist_ok=True)
        assert mock_file.call_count == 2
