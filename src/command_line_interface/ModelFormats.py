"""
Model format helpers shared by the CLI commands: which interface parses a file, and which format a
project that is already in the graph DB has (IFC projects are anchored by an IfcProject node, GeoJSON
projects by a FeatureCollection node with the same GlobalId).
"""
from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface, ET_FEATURE_COLLECTION
from rdf_graph_interface.RdfGraphInterface import RdfGraphInterface, RDF_EXTENSIONS, ET_DATASET

GEOJSON_EXTENSIONS = (".geojson", ".json")

ROOT_ENTITY_TYPES = {"ifc": "IfcProject", "geojson": ET_FEATURE_COLLECTION, "rdf": ET_DATASET}


def file_format(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".ifc"):
        return "ifc"
    if lower.endswith(GEOJSON_EXTENSIONS):
        return "geojson"
    if lower.endswith(RDF_EXTENSIONS):
        return "rdf"
    raise ValueError(f"Unsupported model file {path!r}. Supported: .ifc, {', '.join(GEOJSON_EXTENSIONS + RDF_EXTENSIONS)}")


def project_format(project_id: str):
    """'ifc', 'geojson' or None if the project is not in the DB."""
    if IfcGraphInterface.get_timestamp_from_project_id(project_id):
        return "ifc"
    if GeoJsonGraphInterface.get_timestamp_from_project_id(project_id):
        return "geojson"
    if RdfGraphInterface.get_timestamp_from_project_id(project_id):
        return "rdf"
    return None


def timestamps_in_db(project_id: str) -> list:
    """All timestamps under which the project (IFC or GeoJSON) exists in the DB."""
    return (IfcGraphInterface.get_timestamp_from_project_id(project_id) or []) + \
           (GeoJsonGraphInterface.get_timestamp_from_project_id(project_id) or []) + \
           (RdfGraphInterface.get_timestamp_from_project_id(project_id) or [])


def root_entity_type(project_id: str) -> str:
    return ROOT_ENTITY_TYPES[project_format(project_id) or "ifc"]
