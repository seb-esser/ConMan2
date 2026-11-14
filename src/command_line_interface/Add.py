from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
from neo4j_core.neo4j_connection import Neo4jConnection
from version_timeline.VersionTimeline import VersionTimeline
from command_line_interface.ModelFormats import file_format

def add(model_path: str, timestamp: str, project_id: str = None):

    version_timeline = VersionTimeline()
    Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    fmt = file_format(model_path)
    if fmt == "ifc":
        project_id = IfcGraphInterface.get_project_id_from_ifc_path(model_path)
        timestamps = IfcGraphInterface.get_timestamp_from_project_id(project_id)
        if len(timestamps) > 1:
            raise Exception(f"Error: 2 or more timestamps for project ID {project_id} already exist in the database.")
        ifc_graph_interface = IfcGraphInterface()
        print(f"Adding files from path {model_path} with timestamp {timestamp}. Project: {project_id}")
        ifc_graph_interface.ifc_2_graph(model_path, timestamp)
    elif fmt == "geojson":
        project_id = project_id or GeoJsonGraphInterface.get_project_id_from_geojson_path(model_path)
        if project_id is None:
            raise Exception(f"{model_path} has no FeatureCollection 'id'. Pass the project id with -i/--project_id.")
        timestamps = GeoJsonGraphInterface.get_timestamp_from_project_id(project_id)
        if len(timestamps) > 1:
            raise Exception(f"Error: 2 or more timestamps for project ID {project_id} already exist in the database.")
        if not timestamp:
            timestamp = VersionTimeline.create_timestamp()
        print(f"Adding files from path {model_path} with timestamp {timestamp}. Project: {project_id}")
        GeoJsonGraphInterface().geojson_2_graph(model_path, timestamp, project_id=project_id)
