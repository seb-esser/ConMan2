from version_timeline.VersionTimeline import VersionTimeline
from neo4j_core.neo4j_connection import Neo4jConnection
from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface


def checkout(project_id: str, branch_updt: str, timestamp_updt: str, graph_provider: str = "neo4j"):
    version_timeline = VersionTimeline()
    
    if graph_provider == "neo4j":
        Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)
    
    version_timeline.checkout(project_id, branch_updt, timestamp_updt, graph_provider)