from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
from neo4j_core.neo4j_connection import Neo4jConnection

def get(model_path: str, timestamp: str, graph_provider: str = "neo4j"):

    if graph_provider == "neo4j":
        Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    if model_path.endswith(".ifc"):
        ifc_graph_interface = IfcGraphInterface(graph_provider=graph_provider)
        ifc_graph_interface.graph_2_ifc(model_path, timestamp)