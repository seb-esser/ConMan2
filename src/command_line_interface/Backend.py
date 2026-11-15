"""
Graph backends used by the CLI. The backend is selected with `conman2.py config` (graph_backend).

Both backends offer the same operations, so the CLI commands do not depend on where graph versions live:

    add(path, timestamp, project_id)       parse a model file into a new graph version
    export(path, timestamp)                write a graph version back to a file
    timestamps(project_id)                 versions of a project currently stored
    project_format(project_id)             "ifc" | "geojson" | ... of a stored project
    create_increment(project_id, a, b)     diff + patch between two stored versions -> increment type
    apply_increment(project_id, a, b, inc) move the stored version a to b using a stored increment
    drop(timestamp) / reset()

Patches (patch_data/) and the timeline (timeline_data/) are backend-independent.
"""
import json
import os

from cli_config import ConMan2Config as cfgmod
from command_line_interface.ModelFormats import file_format, ROOT_ENTITY_TYPES

PATCH_DIR = "patch_data"
INCREMENT_CONMAN = "conman"


def project_id_of_file(path: str, project_id: str = None) -> str:
    """Persistent project id of a model file (IfcProject GlobalId, FeatureCollection id, ...)."""
    fmt = file_format(path)
    if fmt == "ifc":
        from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
        return IfcGraphInterface.get_project_id_from_ifc_path(path)
    if fmt == "geojson":
        from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
        pid = project_id or GeoJsonGraphInterface.get_project_id_from_geojson_path(path)
        if pid is None:
            raise Exception(f"{path} has no FeatureCollection 'id'. Pass the project id with -i/--project_id.")
        return pid
    raise ValueError(f"Unsupported format {fmt!r}")


class Neo4jBackend:
    name = "neo4j"

    def __init__(self):
        from neo4j_core.neo4j_connection import Neo4jConnection
        self.connection = Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    def add(self, path: str, timestamp: str, project_id: str = None):
        fmt = file_format(path)
        if fmt == "ifc":
            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            IfcGraphInterface("neo4j").ifc_2_graph(path, timestamp)
        elif fmt == "geojson":
            from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
            GeoJsonGraphInterface("neo4j").geojson_2_graph(path, timestamp, project_id=project_id)

    def export(self, path: str, timestamp: str):
        fmt = file_format(path)
        if fmt == "ifc":
            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            IfcGraphInterface("neo4j").graph_2_ifc(path, timestamp)
        elif fmt == "geojson":
            from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
            GeoJsonGraphInterface("neo4j").graph_2_geojson(path, timestamp)

    def timestamps(self, project_id: str) -> list:
        from command_line_interface.ModelFormats import timestamps_in_db
        return timestamps_in_db(project_id)

    def project_format(self, project_id: str):
        from command_line_interface.ModelFormats import project_format
        return project_format(project_id)

    def create_increment(self, project_id: str, timestamp_init: str, timestamp_updt: str) -> str:
        from graph_diff.GraphDiff import GraphDiff
        from graph_patch.GraphPatch import GraphPatch
        root = ROOT_ENTITY_TYPES[self.project_format(project_id) or "ifc"]
        GraphDiff().run_diff(timestamp_init, timestamp_updt, root_entity_type=root)
        GraphPatch().create_patch(project_id, timestamp_init, timestamp_updt)
        return INCREMENT_CONMAN

    def apply_increment(self, project_id: str, timestamp_from: str, timestamp_to: str, increment: str = INCREMENT_CONMAN):
        from graph_patch.GraphPatch import GraphPatch
        GraphPatch().apply_patch(project_id, timestamp_from, timestamp_to)

    def drop(self, timestamp: str):
        self.connection.cypher_query("MATCH (n) WHERE n.timestamp = $ts DETACH DELETE n", {"ts": timestamp})

    def reset(self):
        self.connection.cypher_query("MATCH (n) DETACH DELETE n")


class NetworkXBackend:
    """Graph versions as NetworkX JSON files in networkx_data_dir, plus an index.json."""
    name = "networkx"

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or cfgmod.get("networkx_data_dir")
        self.index_file = os.path.join(self.data_dir, "index.json")

    # --- index -------------------------------------------------------------------------------------
    def _index(self) -> dict:
        if not os.path.exists(self.index_file):
            return {}
        with open(self.index_file, encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, index: dict):
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=4)

    def graph_file(self, timestamp: str) -> str:
        return os.path.join(self.data_dir, f"networkx_graph_{timestamp}.gpickle")

    def _register(self, timestamp: str, project_id: str, fmt: str):
        index = self._index()
        index[timestamp] = {"project_id": project_id, "format": fmt, "file": self.graph_file(timestamp)}
        self._save_index(index)

    def _entry(self, timestamp: str) -> dict:
        entry = self._index().get(timestamp)
        if entry is None:
            raise Exception(f"No graph version with timestamp {timestamp} in {self.data_dir}.")
        return entry

    # --- operations ----------------------------------------------------------------------------------
    def add(self, path: str, timestamp: str, project_id: str = None):
        if timestamp in self._index():
            raise Exception(f"Timestamp {timestamp} already exists in {self.data_dir}.")
        os.makedirs(self.data_dir, exist_ok=True)
        fmt = file_format(path)
        pid = project_id_of_file(path, project_id)
        if fmt == "ifc":
            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            IfcGraphInterface("networkx").ifc_2_graph(path, timestamp, graph_file=self.graph_file(timestamp))
        elif fmt == "geojson":
            from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
            GeoJsonGraphInterface("networkx").geojson_2_graph(path, timestamp, project_id=project_id,
                                                              graph_file=self.graph_file(timestamp))
        self._register(timestamp, pid, fmt)

    def export(self, path: str, timestamp: str):
        entry = self._entry(timestamp)
        if file_format(path) != entry["format"]:
            raise Exception(f"Version {timestamp} is a {entry['format']} model; choose a matching file extension.")
        if entry["format"] == "ifc":
            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            IfcGraphInterface("networkx").graph_2_ifc(path, timestamp, graph_file=entry["file"])
        elif entry["format"] == "geojson":
            from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
            GeoJsonGraphInterface("networkx").graph_2_geojson(path, timestamp, graph_file=entry["file"])

    def timestamps(self, project_id: str) -> list:
        return [ts for ts, e in self._index().items() if e["project_id"] == project_id]

    def project_format(self, project_id: str):
        return next((e["format"] for e in self._index().values() if e["project_id"] == project_id), None)

    def create_increment(self, project_id: str, timestamp_init: str, timestamp_updt: str) -> str:
        from graph_diff.GraphDiffNx import GraphDiffNx
        from graph_patch.GraphPatchNx import GraphPatchNx
        root = ROOT_ENTITY_TYPES[self.project_format(project_id)]
        diff = GraphDiffNx.from_files(self._entry(timestamp_init)["file"], self._entry(timestamp_updt)["file"])
        equivalence = diff.run_diff(timestamp_init, timestamp_updt, root_entity_type=root)
        GraphPatchNx().create_patch(project_id, timestamp_init, timestamp_updt, diff.graph_init, diff.graph_updt,
                                    equivalence, patch_dir=PATCH_DIR)
        return INCREMENT_CONMAN

    def apply_increment(self, project_id: str, timestamp_from: str, timestamp_to: str, increment: str = INCREMENT_CONMAN):
        from graph_patch.GraphPatchNx import GraphPatchNx
        entry = self._entry(timestamp_from)
        GraphPatchNx().apply_patch(project_id, timestamp_from, timestamp_to, graph_file_init=entry["file"],
                                   graph_file_updt=self.graph_file(timestamp_to), patch_dir=PATCH_DIR)
        self._register(timestamp_to, project_id, entry["format"])
        self.drop(timestamp_from)

    def drop(self, timestamp: str):
        index = self._index()
        entry = index.pop(timestamp, None)
        if entry and os.path.exists(entry["file"]):
            os.remove(entry["file"])
        self._save_index(index)

    def reset(self):
        for ts in list(self._index()):
            self.drop(ts)


def get_backend(name: str = None):
    name = name or cfgmod.get("graph_backend")
    if name == "neo4j":
        return Neo4jBackend()
    if name == "networkx":
        return NetworkXBackend()
    raise cfgmod.ConfigError(f"Unknown graph backend {name!r}")
