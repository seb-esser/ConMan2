from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
from neo4j_core.neo4j_connection import Neo4jConnection
from command_line_interface.ModelFormats import file_format

def get(model_path: str, timestamp: str):

    Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    fmt = file_format(model_path)
    if fmt == "ifc":
        ifc_graph_interface = IfcGraphInterface()
        ifc_graph_interface.graph_2_ifc(model_path, timestamp)
    elif fmt == "geojson":
        GeoJsonGraphInterface().graph_2_geojson(model_path, timestamp)
