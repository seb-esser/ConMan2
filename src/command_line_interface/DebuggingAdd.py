from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
from command_line_interface.ModelFormats import file_format
from neo4j_core.neo4j_connection import Neo4jConnection
from version_timeline.VersionTimeline import VersionTimeline
from cli_config import ConMan2Config as cfgmod

def debugging_add(model_path: str, timestamp: str, project_id: str = None):

    if cfgmod.get("graph_backend") != "neo4j":
        raise Exception("debugging_add/debugging_commit keep equivalence edges in the database for inspection and "
                        "require graph_backend = neo4j (conman2.py config set graph_backend neo4j).")
    version_timeline = VersionTimeline()
    Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    if file_format(model_path) == "ifc":
        project_id = IfcGraphInterface.get_project_id_from_ifc_path(model_path)
        ifc_graph_interface = IfcGraphInterface()
        print(f"Adding files from path {model_path} with timestamp {timestamp}. Project: {project_id}")
        ifc_graph_interface.ifc_2_graph(model_path, timestamp)
    else:
        project_id = project_id or GeoJsonGraphInterface.get_project_id_from_geojson_path(model_path)
        print(f"Adding files from path {model_path} with timestamp {timestamp}. Project: {project_id}")
        GeoJsonGraphInterface().geojson_2_graph(model_path, timestamp, project_id=project_id)
