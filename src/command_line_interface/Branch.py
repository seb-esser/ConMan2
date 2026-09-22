from neo4j_core.neo4j_connection import Neo4jConnection
from version_timeline.VersionTimeline import VersionTimeline

def branch(project_id: str, branch_name: str, graph_provider: str="neo4j"):
    version_timeline = VersionTimeline()
    
    if graph_provider == "neo4j":
        Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)
    
    version_timeline.branch(project_id, branch_name, graph_provider=graph_provider)