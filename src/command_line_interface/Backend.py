"""
Graph backends used by the CLI. The backend is selected with `conman2.py config` (graph_backend).

Both backends offer the same operations, so the CLI commands do not depend on where graph versions live:

    add(path, timestamp, project_id)       parse a model file into a new graph version
    export(path, timestamp)                write a graph version back to a file
    timestamps(project_id)                 versions of a project currently stored
    project_format(project_id)             "ifc" | "geojson" | "rdf"
    create_increment(project_id, a, b)     increment between two stored versions -> increment type
    apply_increment(project_id, a, b, inc) move the stored version a to b using a stored increment
    drop(timestamp) / reset()

Increment types (config increment_representation, recorded per commit in the timeline):
    conman     graph-based topological + semantic patch (patch_data/Patch_{Topo,Sema}_*.json), all formats
    rdf-patch  RDF Patch (patch_data/Patch_RDF_*.rdfp), RDF projects only

Patches and the timeline are backend-independent.
"""
import json
import os

from cli_config import ConMan2Config as cfgmod
from command_line_interface.ModelFormats import file_format, ROOT_ENTITY_TYPES

PATCH_DIR = "patch_data"
INCREMENT_CONMAN = "conman"
INCREMENT_RDF_PATCH = "rdf-patch"


def project_id_of_file(path: str, project_id: str = None) -> str:
    """Persistent project id of a model file (IfcProject GlobalId, FeatureCollection id, dataset IRI slug)."""
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
    if fmt == "rdf":
        from rdf_graph_interface.RdfGraphInterface import RdfGraphInterface, validate_project_id
        pid = project_id or RdfGraphInterface.get_project_id_from_rdf_path(path)
        if pid is None:
            raise Exception(f"{path} has no unique owl:Ontology / void:Dataset / dcat:Dataset IRI. "
                            f"Pass the project id with -i/--project_id.")
        return validate_project_id(pid)
    raise ValueError(f"Unsupported format {fmt!r}")


class _Backend:
    """Format and increment dispatch shared by both backends."""
    name = None

    # --- provider specific hooks ---------------------------------------------------------------------
    def _graph_file(self, timestamp: str):                    # NetworkX file of a version (None for Neo4j)
        return None

    def _new_graph_file(self, timestamp: str):
        return None

    def _registered(self, timestamp: str, project_id: str, fmt: str):
        pass

    def _create_conman(self, project_id, timestamp_init, timestamp_updt):
        raise NotImplementedError

    def _apply_conman(self, project_id, timestamp_from, timestamp_to):
        raise NotImplementedError

    def project_format(self, project_id: str):
        raise NotImplementedError

    def drop(self, timestamp: str):
        raise NotImplementedError

    # --- interfaces ----------------------------------------------------------------------------------
    def _rdf(self, tbox_mode: str = None):
        from rdf_graph_interface.RdfGraphInterface import RdfGraphInterface
        return RdfGraphInterface(self.name, tbox_mode=tbox_mode or cfgmod.get("rdf_tbox"))

    def add(self, path: str, timestamp: str, project_id: str = None):
        fmt = file_format(path)
        pid = project_id_of_file(path, project_id)
        graph_file = self._new_graph_file(timestamp)
        if fmt == "ifc":
            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            IfcGraphInterface(self.name).ifc_2_graph(path, timestamp, graph_file=graph_file)
        elif fmt == "geojson":
            from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
            GeoJsonGraphInterface(self.name).geojson_2_graph(path, timestamp, project_id=project_id, graph_file=graph_file)
        elif fmt == "rdf":
            self._rdf().rdf_2_graph(path, timestamp, project_id=pid, graph_file=graph_file)
        self._registered(timestamp, pid, fmt)

    def export(self, path: str, timestamp: str):
        fmt = file_format(path)
        graph_file = self._graph_file(timestamp)
        if fmt == "ifc":
            from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
            IfcGraphInterface(self.name).graph_2_ifc(path, timestamp, graph_file=graph_file)
        elif fmt == "geojson":
            from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface
            GeoJsonGraphInterface(self.name).graph_2_geojson(path, timestamp, graph_file=graph_file)
        elif fmt == "rdf":
            self._rdf().graph_2_rdf(path, timestamp, graph_file=graph_file)

    # --- increments ----------------------------------------------------------------------------------
    def _rdf_version(self, timestamp: str):
        g, meta = self._rdf().graph_2_rdflib(timestamp, graph_file=self._graph_file(timestamp))
        meta["prefixes"] = sorted((p, str(ns)) for p, ns in g.namespaces())
        return g, meta

    def create_increment(self, project_id: str, timestamp_init: str, timestamp_updt: str) -> str:
        fmt = self.project_format(project_id)
        wanted = cfgmod.get("increment_representation")
        if wanted == INCREMENT_RDF_PATCH and fmt == "rdf":
            from graph_patch.RdfPatch import create_rdf_patch, write_rdf_patch
            g_init, meta_init = self._rdf_version(timestamp_init)
            g_updt, meta_updt = self._rdf_version(timestamp_updt)
            text = create_rdf_patch(g_init, g_updt, project_id, timestamp_init, timestamp_updt, meta_init, meta_updt)
            path = write_rdf_patch(text, project_id, timestamp_init, timestamp_updt, PATCH_DIR)
            print(f"Wrote RDF patch {path}.")
            return INCREMENT_RDF_PATCH
        if wanted == INCREMENT_RDF_PATCH:
            print(f"Note: increment_representation is rdf-patch, but project {project_id} is {fmt}; using conman patches.")
        self._create_conman(project_id, timestamp_init, timestamp_updt)
        return INCREMENT_CONMAN

    def apply_increment(self, project_id: str, timestamp_from: str, timestamp_to: str, increment: str = INCREMENT_CONMAN):
        if increment == INCREMENT_CONMAN:
            self._apply_conman(project_id, timestamp_from, timestamp_to)
            return
        if increment != INCREMENT_RDF_PATCH:
            raise Exception(f"Unknown increment type {increment!r} between {timestamp_from} and {timestamp_to}.")
        from graph_patch.RdfPatch import apply_rdf_patch, find_rdf_patch, parse_rdf_patch, target_meta
        path, reverse = find_rdf_patch(project_id, timestamp_from, timestamp_to, PATCH_DIR)
        with open(path, encoding="utf-8") as f:
            patch = parse_rdf_patch(f.read())
        current, _ = self._rdf_version(timestamp_from)
        result = apply_rdf_patch(current, patch, reverse=reverse)
        meta = target_meta(patch, reverse)
        for prefix, ns in meta.get("prefixes", []):
            result.bind(prefix, ns, override=True)
        self.drop(timestamp_from)
        self._rdf(meta.get("tbox_mode")).rdflib_2_graph(result, timestamp_to, project_id, meta.get("tbox"),
                                                        graph_file=self._new_graph_file(timestamp_to),
                                                        dataset_iri=meta.get("dataset_iri"))
        self._registered(timestamp_to, project_id, "rdf")


class Neo4jBackend(_Backend):
    name = "neo4j"

    def __init__(self):
        from neo4j_core.neo4j_connection import Neo4jConnection
        self.connection = Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    def timestamps(self, project_id: str) -> list:
        from command_line_interface.ModelFormats import timestamps_in_db
        return timestamps_in_db(project_id)

    def project_format(self, project_id: str):
        from command_line_interface.ModelFormats import project_format
        return project_format(project_id)

    def _create_conman(self, project_id, timestamp_init, timestamp_updt):
        from graph_diff.GraphDiff import GraphDiff
        from graph_patch.GraphPatch import GraphPatch
        root = ROOT_ENTITY_TYPES[self.project_format(project_id) or "ifc"]
        GraphDiff().run_diff(timestamp_init, timestamp_updt, root_entity_type=root)
        GraphPatch().create_patch(project_id, timestamp_init, timestamp_updt)

    def _apply_conman(self, project_id, timestamp_from, timestamp_to):
        from graph_patch.GraphPatch import GraphPatch
        GraphPatch().apply_patch(project_id, timestamp_from, timestamp_to)

    def drop(self, timestamp: str):
        self.connection.cypher_query("MATCH (n) WHERE n.timestamp = $ts DETACH DELETE n", {"ts": timestamp})

    def reset(self):
        self.connection.cypher_query("MATCH (n) DETACH DELETE n")


class NetworkXBackend(_Backend):
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

    def _entry(self, timestamp: str) -> dict:
        entry = self._index().get(timestamp)
        if entry is None:
            raise Exception(f"No graph version with timestamp {timestamp} in {self.data_dir}.")
        return entry

    def _graph_file(self, timestamp: str):
        return self._entry(timestamp)["file"]

    def _new_graph_file(self, timestamp: str):
        if timestamp in self._index():
            raise Exception(f"Timestamp {timestamp} already exists in {self.data_dir}.")
        os.makedirs(self.data_dir, exist_ok=True)
        return self.graph_file(timestamp)

    def _registered(self, timestamp: str, project_id: str, fmt: str):
        index = self._index()
        index[timestamp] = {"project_id": project_id, "format": fmt, "file": self.graph_file(timestamp)}
        self._save_index(index)

    # --- operations ----------------------------------------------------------------------------------
    def export(self, path: str, timestamp: str):
        entry = self._entry(timestamp)
        if file_format(path) != entry["format"]:
            raise Exception(f"Version {timestamp} is a {entry['format']} model; choose a matching file extension.")
        super().export(path, timestamp)

    def timestamps(self, project_id: str) -> list:
        return [ts for ts, e in self._index().items() if e["project_id"] == project_id]

    def project_format(self, project_id: str):
        return next((e["format"] for e in self._index().values() if e["project_id"] == project_id), None)

    def _create_conman(self, project_id, timestamp_init, timestamp_updt):
        from graph_diff.GraphDiffNx import GraphDiffNx
        from graph_patch.GraphPatchNx import GraphPatchNx
        root = ROOT_ENTITY_TYPES[self.project_format(project_id)]
        diff = GraphDiffNx.from_files(self._graph_file(timestamp_init), self._graph_file(timestamp_updt))
        equivalence = diff.run_diff(timestamp_init, timestamp_updt, root_entity_type=root)
        GraphPatchNx().create_patch(project_id, timestamp_init, timestamp_updt, diff.graph_init, diff.graph_updt,
                                    equivalence, patch_dir=PATCH_DIR)

    def _apply_conman(self, project_id, timestamp_from, timestamp_to):
        from graph_patch.GraphPatchNx import GraphPatchNx
        entry = self._entry(timestamp_from)
        GraphPatchNx().apply_patch(project_id, timestamp_from, timestamp_to, graph_file_init=entry["file"],
                                   graph_file_updt=self.graph_file(timestamp_to), patch_dir=PATCH_DIR)
        self._registered(timestamp_to, project_id, entry["format"])
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
