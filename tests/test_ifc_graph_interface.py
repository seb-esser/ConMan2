import pytest
import ifcopenshell
import ifcopenshell.api.project
import networkx as nx
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock, call
from collections import defaultdict
import sys

root_dir = os.path.dirname(os.path.dirname(__file__))
src_dir = os.path.join(root_dir, 'src')
sys.path.insert(0, src_dir)

from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
from neo4j_core.neo4j_connection import Neo4jConnection
from networkX_core.networkx_connection import networkxConnection

# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------

@pytest.fixture
def sample_ifc_file(tmp_path):
    # create an empty in-memory IFC file
    ifc_file = ifcopenshell.file(schema="IFC4")
    
    # create IfcProject entity and set attributes
    project = ifc_file.create_entity("IfcProject")
    project.GlobalId = "proj_123"
    project.Name = "Test Project"
    
    # create IfcWall entity and set attributes
    wall = ifc_file.create_entity("IfcWall")
    wall.GlobalId = "wall_456"
    wall.Name = "Test Wall"
    
    # create IfcRelContainedInSpatialStructure relationship entity
    rel = ifc_file.create_entity("IfcRelContainedInSpatialStructure")
    rel.GlobalId = "rel_789"
    rel.RelatingStructure = project
    rel.RelatedElements = [wall]
    
    # create IfcLocalPlacement（SecondaryNode）
    placement = ifc_file.create_entity("IfcLocalPlacement")
    
    # skip IfcLengthMeasure inline entity for now (id=0)
    
    return ifc_file

@pytest.fixture
def sample_model(sample_ifc_file):
    """Return the ifcopenshell model (already loaded)."""
    return sample_ifc_file

@pytest.fixture
def graph_interface():
    return IfcGraphInterface(graph_provider="neo4j")

@pytest.fixture
def nx_interface():
    return IfcGraphInterface(graph_provider="networkx")

# ----------------------------------------------------------------------
# Test content
# ----------------------------------------------------------------------


def test_sample_ifc_file_content(sample_ifc_file):
    """basic sanity check: test created ifc file contains expected entities and relationships"""
    ifc_file = sample_ifc_file
    
    # 1. PrimaryNode: IfcProject and IfcWall
    projects = ifc_file.by_type("IfcProject")
    assert len(projects) == 1, "There should be one IfcProject"
    assert projects[0].GlobalId == "proj_123"
    assert projects[0].Name == "Test Project"
    
    walls = ifc_file.by_type("IfcWall")
    assert len(walls) == 1, "There should be one IfcWall"
    assert walls[0].GlobalId == "wall_456"
    assert walls[0].Name == "Test Wall"
    
    # 2. ConnectionNode
    rels = ifc_file.by_type("IfcRelContainedInSpatialStructure")
    assert len(rels) == 1, "There should be one IfcRelContainedInSpatialStructure"
    assert rels[0].RelatingStructure == projects[0]
    assert walls[0] in rels[0].RelatedElements
    
    # 3. SecondaryNode
    placements = ifc_file.by_type("IfcLocalPlacement")
    assert len(placements) == 1, "There should be one IfcLocalPlacement"
    
    # 4. Skip inline entities and mixed list validation (not included yet)

# ----------------------------------------------------------------------
# Tests for __process_ifc_attributes (middle layer)
# ----------------------------------------------------------------------

class TestProcessIfcAttributes:
    def test_primitive_attributes(self, sample_model, graph_interface):
        """basic attributes should be stored in props_map"""
        entity = sample_model.by_type("IfcWall")[0]
        timestamp = "ts123"
        props_map = {}
        relationships = []
        related_nodes = set()
        inline_patterns = []
        
        graph_interface._IfcGraphInterface__process_ifc_attributes(
            entity, timestamp, props_map, relationships, related_nodes, inline_patterns
        )
        
        p21_id = f"#{entity.id()}"
        assert p21_id in props_map
        # Name attribute should be a basic type
        assert props_map[p21_id].get("Name") == "Test Wall"
        # GlobalId should be skipped
        assert "GlobalId" not in props_map[p21_id]
        assert "EntityType" not in props_map[p21_id]
    
    def test_single_entity_reference(self, sample_model, graph_interface):
        """single entity reference should create a relationship entry"""
        rel_entity = sample_model.by_type("IfcRelContainedInSpatialStructure")[0]
        timestamp = "ts123"
        props_map = {}
        relationships = []
        related_nodes = set()
        inline_patterns = []
        
        graph_interface._IfcGraphInterface__process_ifc_attributes(
            rel_entity, timestamp, props_map, relationships, related_nodes, inline_patterns
        )
        
        project = sample_model.by_type("IfcProject")[0]
        source_id = f"#{rel_entity.id()}"
        target_id = f"#{project.id()}"
        
        expected_rel = {
            "source_p21_id": source_id,
            "target_p21_id": target_id,
            "timestamp": timestamp,
            "rel_type": "RelatingStructure",
            "list_index": 0
        }
        assert expected_rel in relationships
        assert target_id in related_nodes
    
    def test_list_of_entities(self, sample_model, graph_interface):
        """list of entity references should create multiple relationship entries (one per element)"""
        rel_entity = sample_model.by_type("IfcRelContainedInSpatialStructure")[0]
        timestamp = "ts123"
        props_map = {}
        relationships = []
        related_nodes = set()
        inline_patterns = []
        
        graph_interface._IfcGraphInterface__process_ifc_attributes(
            rel_entity, timestamp, props_map, relationships, related_nodes, inline_patterns
        )
        
        wall = sample_model.by_type("IfcWall")[0]
        source_id = f"#{rel_entity.id()}"
        target_id = f"#{wall.id()}"
        
        expected_rel = {
            "source_p21_id": source_id,
            "target_p21_id": target_id,
            "timestamp": timestamp,
            "rel_type": "RelatedElements",
            "list_index": 0
        }
        assert expected_rel in relationships
        assert target_id in related_nodes

# -----------------------------------------------------------------------
# Tests for __send_to_nx (top layer)
# -----------------------------------------------------------------------

def test_networkx_graph_structure(sample_ifc_file, nx_interface, tmp_path):
    timestamp = "test_nx"
    # save the in-memory IFC file to a temporary location for processing
    temp_ifc = tmp_path / "test.ifc"
    sample_ifc_file.write(temp_ifc)
    
    nx_interface.ifc_2_graph(str(temp_ifc), timestamp, batch_size=100)
    
    # reload the graph and check structure
    import pickle
    from networkX_core.networkx_connection import networkxConnection
    graph_file = f"networkx_graph_{timestamp}.gpickle"
    nx_conn = networkxConnection()
    nx_conn.load_graph(graph_file)
    graph = nx_conn.graph
    
    primary_nodes = [n for n, d in graph.nodes(data=True) if d.get("label") == "PrimaryNode"]
    assert len(primary_nodes) == 2
    connection_nodes = [n for n, d in graph.nodes(data=True) if d.get("label") == "ConnectionNode"]
    assert len(connection_nodes) == 1
    secondary_nodes = [n for n, d in graph.nodes(data=True) if d.get("label") == "SecondaryNode"]
    assert len(secondary_nodes) == 1
    
    edges = list(graph.edges(data=True))
    assert len(edges) == 2
    for _, _, data in edges:
        assert "rel_type" in data
        assert "list_index" in data
    
    # cleanup
    if os.path.exists(graph_file):
        os.remove(graph_file)
        
# -----------------------------------------------------------------------
# Tests for Neo4j (mock-based unit tests)
# -----------------------------------------------------------------------

class TestNeo4jAdapter:
    def test_neo4j_cypher_payload(self, sample_ifc_file, tmp_path):
        timestamp = "neo4j_test_ts"
        temp_ifc = tmp_path / "test_neo4j.ifc"
        sample_ifc_file.write(temp_ifc)

        # need to patch two targets:
        # 1. Neo4J_Helper (imported in ifc_graph_interface module)
        # 2. db.cypher_query (possibly from neomodel)
        with patch('ifc_graph_interface.IfcGraphInterface.Neo4J_Helper') as MockNeo4J_Helper, \
             patch('ifc_graph_interface.IfcGraphInterface.db.cypher_query') as mock_db_cypher:

            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            graph_interface = IfcGraphInterface(graph_provider="neo4j")

            captured_batches = {}

            def side_effect_bulk_query(query, batch, batch_size):
                if "PrimaryNode" in query:
                    captured_batches["primary"] = batch
                elif "ConnectionNode" in query:
                    captured_batches["connection"] = batch
                elif "SecondaryNode" in query:
                    captured_batches["secondary"] = batch
                elif "SET n += row.properties" in query:
                    captured_batches["properties"] = batch
                elif "CREATE (a)-[:rel" in query and "InlineNode" not in query:
                    captured_batches["relationships"] = batch

            mock_helper_instance = MockNeo4J_Helper.return_value
            mock_helper_instance.bulk_cypher_query.side_effect = side_effect_bulk_query

            graph_interface.ifc_2_graph(str(temp_ifc), timestamp, batch_size=100)

            # verify payload
            primary_batch = captured_batches.get("primary", [])
            assert len(primary_batch) == 2
            entity_types = [node["EntityType"] for node in primary_batch]
            assert "IfcProject" in entity_types
            assert "IfcWall" in entity_types
            assert primary_batch[0]["timestamp"] == timestamp

            connection_batch = captured_batches.get("connection", [])
            assert len(connection_batch) == 1
            assert connection_batch[0]["EntityType"] == "IfcRelContainedInSpatialStructure"

            secondary_batch = captured_batches.get("secondary", [])
            assert len(secondary_batch) == 1
            assert secondary_batch[0]["EntityType"] == "IfcLocalPlacement"

            relationships_batch = captured_batches.get("relationships", [])
            rel_types = [rel["rel_type"] for rel in relationships_batch]
            assert "RelatingStructure" in rel_types
            assert "RelatedElements" in rel_types

            # verify db.cypher_query was called at least twice (index creation)
            assert mock_db_cypher.call_count >= 2