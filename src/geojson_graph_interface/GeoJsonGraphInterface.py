"""
GeoJsonGraphInterface: translation between GeoJSON (RFC 7946) FeatureCollections and the ConMan2
labeled property graph meta model (PrimaryNode / ConnectionNode / SecondaryNode / InlineNode with
generic ``rel`` edges carrying ``rel_type`` and ``list_index``).

The structure intentionally mirrors ``IfcGraphInterface``:
  * the file is first decomposed into the same intermediate collections that the IFC parser builds
    (``primary_nodes``, ``connection_nodes``, ``secondary_nodes``, ``relationships``,
    ``inline_patterns``),
  * these are then bulk-written with the same Cypher (Neo4j) or the same NetworkX layout,
  * the reverse direction reads all nodes of one ``timestamp`` and rebuilds the GeoJSON document.

See ``README.md`` in this folder for the complete mapping table and the rationale.
"""
import json
import re
from collections import defaultdict

from graph_io.lpg_io import Decomposition as _Decomposition, send_to_neo4j, send_to_nx, retrieve_from_neo4j, retrieve_from_nx
from neo4j_core.neo4j_model import PrimaryNode, ConnectionNode, SecondaryNode, InlineNode

#################
### Constants ###
#################

GEOMETRY_TYPES = ("Point", "MultiPoint", "LineString", "MultiLineString",
                  "Polygon", "MultiPolygon", "GeometryCollection")

# EntityTypes of synthetic nodes (no direct GeoJSON object type exists for them).
ET_FEATURE_COLLECTION = "FeatureCollection"
ET_FEATURE = "Feature"
ET_MEMBERSHIP = "FeatureMembership"        # ConnectionNode: FeatureCollection <-> Feature
ET_PROPERTIES = "Properties"                # SecondaryNode: the "properties" member of a Feature
ET_JSON_OBJECT = "JsonObject"               # SecondaryNode: nested JSON object
ET_JSON_ARRAY = "JsonArray"                 # SecondaryNode: nested JSON array inside an array
ET_JSON_VALUE = "JsonValue"                 # InlineNode: primitive element of a structured array
ET_POSITION = "Position"                    # InlineNode: one GeoJSON position [x, y(, z)]
ET_LINEAR_RING = "LinearRing"               # SecondaryNode: ring of a (Multi)Polygon
ET_LINESTRING_COORDS = "LineStringCoordinates"  # SecondaryNode: one line of a MultiLineString
ET_POLYGON_COORDS = "PolygonCoordinates"    # SecondaryNode: one polygon of a MultiPolygon

# rel_types of structural edges (they are the GeoJSON member names, like IFC attribute names).
REL_FEATURES = "features"                   # FeatureCollection -> id-less Feature (SecondaryNode)
REL_RELATING_COLLECTION = "RelatingCollection"  # FeatureMembership -> FeatureCollection
REL_RELATED_FEATURE = "RelatedFeature"      # FeatureMembership -> Feature
REL_GEOMETRY = "geometry"
REL_PROPERTIES = "properties"
REL_COORDINATES = "coordinates"
REL_GEOMETRIES = "geometries"
REL_ITEMS = "items"

# Node properties used for bookkeeping. They are part of the node and therefore take part in the
# semantic diff (e.g. a value turning from string into null changes meta__json_keys).
# They must not start with "_": neomodel silently drops such attributes when GraphPatch.apply_patch
# creates nodes via the OGM.
META_JSON_KEYS = "meta__json_keys"     # keys whose value is stored as JSON text (null, primitive arrays)
META_ARRAY_KEYS = "meta__array_keys"   # rel_types whose targets form a JSON array (sorted by list_index)
META_ID_TYPE = "meta__id_type"         # "number" or "none" if the GeoJSON id was not a string
META_MEMBER_INDEX = "member_index"  # position of a Feature inside FeatureCollection.features

STRUCTURAL_KEYS = {"EntityType", "timestamp", "p21_id", "GlobalId", "label", "wrappedValue",
                   "element_id_property"}
META_KEYS = {META_JSON_KEYS, META_ARRAY_KEYS, META_ID_TYPE}

# GeoJSON member/property keys are escaped when they
#   * collide with node bookkeeping or with attributes of the neomodel classes (GraphPatch.apply_patch
#     uses setattr / constructor kwargs), or
#   * are no plain identifiers. neomodel writes properties as unquoted "SET n.<key> = $<key>", so keys
#     such as OSM's "addr:city" or "name:ru" break the OGM write path (CypherSyntaxError),
#   * start with "_" (neomodel drops those attributes on save), or with the escape/meta prefixes.
# Escaped form: ESC + every UTF-8 byte outside [A-Za-z0-9] written as "_hh". Reversible.
ESC = "esc__"
META_PREFIX = "meta__"
RESERVED_KEYS = (STRUCTURAL_KEYS | META_KEYS
                 | {a for cls in (PrimaryNode, ConnectionNode, SecondaryNode, InlineNode) for a in dir(cls)})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ALNUM = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")


def escape_key(key: str) -> str:
    if (_IDENTIFIER.fullmatch(key) and key not in RESERVED_KEYS
            and not key.startswith(("_", ESC, META_PREFIX))):
        return key
    return ESC + "".join(c if c in _ALNUM else "".join(f"_{b:02x}" for b in c.encode("utf-8")) for c in key)


def unescape_key(key: str) -> str:
    if not key.startswith(ESC):
        return key
    body, out, i = key[len(ESC):], bytearray(), 0
    while i < len(body):
        if body[i] == "_":
            out.append(int(body[i + 1:i + 3], 16))
            i += 3
        else:
            out += body[i].encode("utf-8")
            i += 1
    return out.decode("utf-8")


class GeoJsonGraphInterface:

    # Same providers as IfcGraphInterface.
    graph_providers = ("neo4j", "networkx")

    def __init__(self, graph_provider: str = "neo4j") -> None:
        if graph_provider not in self.graph_providers:
            raise ValueError(
                f"Graph provider '{graph_provider}' not supported. Available providers: {self.graph_providers}")
        self.graph_provider = graph_provider
        print("Selected provider: ", self.graph_provider)

    #####################################
    ### Helper Functions: GeoJSON->LPG ###
    #####################################

    def __encode_members(self, d: _Decomposition, node: dict, obj: dict, skip=()):
        """
        Store the members of a JSON object on a node. Primitives become node properties, nested
        objects/structured arrays become child nodes connected via rel(rel_type=<key>).
        """
        json_keys, array_keys = [], []
        for key, val in obj.items():
            if key in skip:
                continue
            skey = escape_key(key)
            if isinstance(val, dict):
                child = d.node("SecondaryNode", ET_JSON_OBJECT, d.child_key(node, skey, 0))
                self.__encode_members(d, child, val)
                d.rel(node, child, skey, 0)
            elif isinstance(val, list) and any(isinstance(x, (dict, list)) for x in val):
                array_keys.append(skey)
                for i, x in enumerate(val):
                    self.__encode_array_element(d, node, skey, i, x)
            elif val is None or isinstance(val, list):
                # null and arrays of primitives: stored losslessly as JSON text.
                node[skey] = json.dumps(val, ensure_ascii=False)
                json_keys.append(skey)
            else:
                node[skey] = val
        if json_keys:
            node[META_JSON_KEYS] = json.dumps(sorted(json_keys), ensure_ascii=False)
        if array_keys:
            node[META_ARRAY_KEYS] = json.dumps(sorted(array_keys), ensure_ascii=False)

    def __encode_array_element(self, d: _Decomposition, parent: dict, rel_type: str, index: int, val):
        if isinstance(val, dict):
            child = d.node("SecondaryNode", ET_JSON_OBJECT, d.child_key(parent, rel_type, index))
            self.__encode_members(d, child, val)
            d.rel(parent, child, rel_type, index)
        elif isinstance(val, list):
            child = d.node("SecondaryNode", ET_JSON_ARRAY, d.child_key(parent, rel_type, index))
            for j, x in enumerate(val):
                self.__encode_array_element(d, child, REL_ITEMS, j, x)
            d.rel(parent, child, rel_type, index)
        else:
            d.inline(parent, rel_type, index, ET_JSON_VALUE, json.dumps(val, ensure_ascii=False))

    def __encode_positions(self, d: _Decomposition, parent: dict, positions: list):
        for i, pos in enumerate(positions):
            d.inline(parent, REL_COORDINATES, i, ET_POSITION, json.dumps(pos))

    def __encode_rings(self, d: _Decomposition, parent: dict, rings: list, entity_type: str):
        for i, ring in enumerate(rings):
            ring_node = d.node("SecondaryNode", entity_type, d.child_key(parent, REL_COORDINATES, i))
            self.__encode_positions(d, ring_node, ring)
            d.rel(parent, ring_node, REL_COORDINATES, i)

    def __encode_geometry(self, d: _Decomposition, geometry: dict, key: str) -> dict:
        gtype = geometry.get("type")
        if gtype not in GEOMETRY_TYPES:
            raise ValueError(f"Unknown GeoJSON geometry type: {gtype!r}")
        node = d.node("SecondaryNode", gtype, key)
        # Foreign members and bbox of the geometry object.
        self.__encode_members(d, node, geometry, skip=("type", "coordinates", "geometries"))

        if gtype == "GeometryCollection":
            for i, sub in enumerate(geometry.get("geometries", [])):
                d.rel(node, self.__encode_geometry(d, sub, d.child_key(node, REL_GEOMETRIES, i)), REL_GEOMETRIES, i)
            return node

        coords = geometry.get("coordinates", [])
        if gtype == "Point":
            if coords:
                d.inline(node, REL_COORDINATES, 0, ET_POSITION, json.dumps(coords))
        elif gtype in ("MultiPoint", "LineString"):
            self.__encode_positions(d, node, coords)
        elif gtype == "Polygon":
            self.__encode_rings(d, node, coords, ET_LINEAR_RING)
        elif gtype == "MultiLineString":
            self.__encode_rings(d, node, coords, ET_LINESTRING_COORDS)
        elif gtype == "MultiPolygon":
            for i, polygon in enumerate(coords):
                poly_node = d.node("SecondaryNode", ET_POLYGON_COORDS, d.child_key(node, REL_COORDINATES, i))
                self.__encode_rings(d, poly_node, polygon, ET_LINEAR_RING)
                d.rel(node, poly_node, REL_COORDINATES, i)
        return node

    @staticmethod
    def __id_type(value):
        if value is None:
            return "none"
        return None if isinstance(value, str) else "number"

    def __decompose(self, fc: dict, timestamp: str, project_id: str = None) -> _Decomposition:
        if fc.get("type") != "FeatureCollection":
            raise NotImplementedError(
                f"Only FeatureCollections can be version-controlled (got type {fc.get('type')!r}). "
                "Wrap single Features/Geometries into a FeatureCollection.")
        fc_id = fc.get("id")
        if project_id is not None and fc_id is not None and str(fc_id) != str(project_id):
            raise ValueError(f"project_id {project_id!r} contradicts the FeatureCollection id {fc_id!r}.")
        global_id = project_id if project_id is not None else fc_id
        if global_id is None:
            raise ValueError("The FeatureCollection has no 'id' member. Provide a project_id explicitly.")

        d = _Decomposition(timestamp)
        root = d.node("PrimaryNode", ET_FEATURE_COLLECTION, "fc", str(global_id))
        if self.__id_type(fc_id):
            root[META_ID_TYPE] = self.__id_type(fc_id)
        self.__encode_members(d, root, fc, skip=("type", "id", "features"))

        seen_ids = set()
        for index, feature in enumerate(fc.get("features", [])):
            if feature.get("type") != "Feature":
                raise ValueError(f"features[{index}] is not a Feature.")
            fid = feature.get("id")
            if fid is None:
                # No persistent identity: identified by its position (unique path) like IFC secondary entities.
                fnode = d.node("SecondaryNode", ET_FEATURE, d.child_key(root, REL_FEATURES, index))
                d.rel(root, fnode, REL_FEATURES, index)
            else:
                if str(fid) in seen_ids:
                    raise ValueError(f"Duplicate Feature id {fid!r}; ids must be unique within a collection.")
                seen_ids.add(str(fid))
                fnode = d.node("PrimaryNode", ET_FEATURE, f"f:{fid}", str(fid))
                if self.__id_type(fid):
                    fnode[META_ID_TYPE] = self.__id_type(fid)
                # Membership is objectified like IfcRelAggregates. Its GlobalId is derived from both ends
                # so it is stable across versions; its member_index carries the feature order.
                membership = d.node("ConnectionNode", ET_MEMBERSHIP, f"m:{fid}", f"{global_id}::{fid}")
                membership[META_MEMBER_INDEX] = index
                d.rel(membership, root, REL_RELATING_COLLECTION, 0)
                d.rel(membership, fnode, REL_RELATED_FEATURE, 0)

            if feature.get("geometry") is not None:
                d.rel(fnode, self.__encode_geometry(d, feature["geometry"], d.child_key(fnode, REL_GEOMETRY, 0)),
                      REL_GEOMETRY, 0)
            if isinstance(feature.get("properties"), dict):
                pnode = d.node("SecondaryNode", ET_PROPERTIES, d.child_key(fnode, REL_PROPERTIES, 0))
                self.__encode_members(d, pnode, feature["properties"])
                d.rel(fnode, pnode, REL_PROPERTIES, 0)
            # Foreign members of the Feature (e.g. bbox, title).
            self.__encode_members(d, fnode, feature, skip=("type", "id", "geometry", "properties"))
        return d

    #####################################
    ### Helper Functions: LPG->GeoJSON ###
    #####################################

    @staticmethod
    def __decode_members(nodes, children, nid, skip_rels=()) -> dict:
        props = nodes[nid]["props"]
        json_keys = set(json.loads(props.get(META_JSON_KEYS, "[]")))
        array_keys = set(json.loads(props.get(META_ARRAY_KEYS, "[]")))
        obj = {}
        for key, val in props.items():
            if key in STRUCTURAL_KEYS or key in META_KEYS or key == META_MEMBER_INDEX:
                continue
            obj[unescape_key(key)] = json.loads(val) if key in json_keys else val
        grouped = defaultdict(list)
        for rel_type, list_index, child in children.get(nid, []):
            if rel_type not in skip_rels:
                grouped[rel_type].append((list_index or 0, child))
        for rel_type, items in grouped.items():
            items.sort(key=lambda x: x[0])
            values = [GeoJsonGraphInterface.__decode_value(nodes, children, c) for _, c in items]
            obj[unescape_key(rel_type)] = values if rel_type in array_keys else values[0]
        return dict(sorted(obj.items()))

    @staticmethod
    def __decode_value(nodes, children, nid):
        node = nodes[nid]
        if node["kind"] == "InlineNode":
            return json.loads(node["props"]["wrappedValue"])
        if node["props"]["EntityType"] == ET_JSON_ARRAY:
            items = sorted(((li or 0, c) for rt, li, c in children.get(nid, []) if rt == REL_ITEMS), key=lambda x: x[0])
            return [GeoJsonGraphInterface.__decode_value(nodes, children, c) for _, c in items]
        return GeoJsonGraphInterface.__decode_members(nodes, children, nid)

    @staticmethod
    def __sorted_children(children, nid, rel_type):
        return [c for _, c in sorted(((li or 0, c) for rt, li, c in children.get(nid, []) if rt == rel_type),
                                     key=lambda x: x[0])]

    def __decode_positions(self, nodes, children, nid):
        return [json.loads(nodes[c]["props"]["wrappedValue"]) for c in self.__sorted_children(children, nid, REL_COORDINATES)]

    def __decode_geometry(self, nodes, children, nid) -> dict:
        gtype = nodes[nid]["props"]["EntityType"]
        geometry = {"type": gtype}
        foreign = self.__decode_members(nodes, children, nid, skip_rels=(REL_COORDINATES, REL_GEOMETRIES))
        if "bbox" in foreign:
            geometry["bbox"] = foreign.pop("bbox")
        if gtype == "GeometryCollection":
            geometry["geometries"] = [self.__decode_geometry(nodes, children, c)
                                      for c in self.__sorted_children(children, nid, REL_GEOMETRIES)]
        elif gtype == "Point":
            positions = self.__decode_positions(nodes, children, nid)
            geometry["coordinates"] = positions[0] if positions else []
        elif gtype in ("MultiPoint", "LineString"):
            geometry["coordinates"] = self.__decode_positions(nodes, children, nid)
        elif gtype in ("Polygon", "MultiLineString"):
            geometry["coordinates"] = [self.__decode_positions(nodes, children, r)
                                       for r in self.__sorted_children(children, nid, REL_COORDINATES)]
        elif gtype == "MultiPolygon":
            geometry["coordinates"] = [[self.__decode_positions(nodes, children, r)
                                        for r in self.__sorted_children(children, p, REL_COORDINATES)]
                                       for p in self.__sorted_children(children, nid, REL_COORDINATES)]
        geometry.update(foreign)
        return geometry

    @staticmethod
    def __decode_id(props):
        id_type = props.get(META_ID_TYPE)
        if id_type == "none":
            return None
        if id_type == "number":
            return json.loads(props["GlobalId"])
        return props["GlobalId"]

    def __decode_feature(self, nodes, children, nid) -> dict:
        props = nodes[nid]["props"]
        feature = {"type": "Feature"}
        if nodes[nid]["kind"] == "PrimaryNode":
            feature["id"] = self.__decode_id(props)
        foreign = self.__decode_members(nodes, children, nid, skip_rels=(REL_GEOMETRY, REL_PROPERTIES))
        if "bbox" in foreign:
            feature["bbox"] = foreign.pop("bbox")
        geometry = self.__sorted_children(children, nid, REL_GEOMETRY)
        feature["geometry"] = self.__decode_geometry(nodes, children, geometry[0]) if geometry else None
        properties = self.__sorted_children(children, nid, REL_PROPERTIES)
        feature["properties"] = self.__decode_members(nodes, children, properties[0]) if properties else None
        feature.update(foreign)
        return feature

    def __assemble(self, nodes: dict, edges: list) -> dict:
        """
        Rebuild the GeoJSON document from a provider-independent view of one graph version.

        @param nodes: {node_id: {"kind": <PrimaryNode|ConnectionNode|SecondaryNode|InlineNode>, "props": {...}}}
        @param edges: [(source_id, target_id, rel_type, list_index)]
        """
        children = defaultdict(list)
        for src, tgt, rel_type, list_index in edges:
            children[src].append((rel_type, list_index, tgt))

        roots = [n for n, v in nodes.items()
                 if v["kind"] == "PrimaryNode" and v["props"].get("EntityType") == ET_FEATURE_COLLECTION]
        if len(roots) != 1:
            raise Exception(f"Expected exactly one FeatureCollection node, found {len(roots)}.")
        root = roots[0]

        members = [(li or 0, c) for rt, li, c in children.get(root, []) if rt == REL_FEATURES]
        for nid, node in nodes.items():
            if node["kind"] != "ConnectionNode" or node["props"].get("EntityType") != ET_MEMBERSHIP:
                continue
            targets = {rt: c for rt, li, c in children.get(nid, [])}
            if targets.get(REL_RELATING_COLLECTION) == root and REL_RELATED_FEATURE in targets:
                members.append((node["props"].get(META_MEMBER_INDEX, 0), targets[REL_RELATED_FEATURE]))
        members.sort(key=lambda x: x[0])

        root_props = nodes[root]["props"]
        fc = {"type": "FeatureCollection"}
        fc_id = self.__decode_id(root_props)
        if fc_id is not None:
            fc["id"] = fc_id
        fc.update(self.__decode_members(nodes, children, root, skip_rels=(REL_FEATURES,)))
        fc["features"] = [self.__decode_feature(nodes, children, f) for _, f in members]
        return fc

    ######################
    ### Main Functions ###
    ######################

    @staticmethod
    def default_graph_file(timestamp: str) -> str:
        """File name convention of the NetworkX provider (same as IfcGraphInterface)."""
        return f"networkx_graph_{timestamp}.gpickle"

    def geojson_2_graph(self, geojson_path: str, timestamp: str, project_id: str = None,
                        batch_size: int = 20000, graph_file: str = None):
        """
        Parse a GeoJSON FeatureCollection into the graph.

        @param geojson_path: Path of the .geojson/.json file.
        @param timestamp: Graph version identifier.
        @param project_id: Persistent project id. Defaults to the FeatureCollection's "id" member.
        @param graph_file: NetworkX only: target file, defaults to networkx_graph_<timestamp>.gpickle.
        """
        print("Loading GeoJSON model.")
        with open(geojson_path, encoding="utf-8") as f:
            fc = json.load(f)
        d = self.__decompose(fc, timestamp, project_id)
        if self.graph_provider == "neo4j":
            send_to_neo4j(d, batch_size)
        elif self.graph_provider == "networkx":
            send_to_nx(d, graph_file or self.default_graph_file(timestamp))
        print("Finished GeoJSON parsing.")
        return d

    def graph_2_geojson(self, geojson_path: str, timestamp: str, graph_file: str = None) -> dict:
        """
        Generate a GeoJSON file from the graph version identified by timestamp.
        """
        if self.graph_provider == "neo4j":
            nodes, edges = retrieve_from_neo4j(timestamp)
        elif self.graph_provider == "networkx":
            nodes, edges = retrieve_from_nx(timestamp, graph_file or self.default_graph_file(timestamp))
        fc = self.__assemble(nodes, edges)
        if geojson_path:
            print("Write model to file. ")
            with open(geojson_path, "w", encoding="utf-8") as f:
                json.dump(fc, f, indent=2, ensure_ascii=False)
            print("Finished GeoJSON file generation. ")
        return fc

    @staticmethod
    def get_project_id_from_geojson_path(geojson_path: str):
        try:
            with open(geojson_path, encoding="utf-8") as f:
                fc_id = json.load(f).get("id")
            return None if fc_id is None else str(fc_id)
        except Exception as e:
            print(f"Error retrieving project ID from GeoJSON file {geojson_path}: {e}")
            return None

    @staticmethod
    def get_timestamp_from_project_id(project_id: str):
        """Neo4j only: all timestamps under which this FeatureCollection exists in the DB."""
        try:
            nodes = PrimaryNode.nodes.filter(GlobalId=project_id, EntityType=ET_FEATURE_COLLECTION).all()
            return [n.timestamp for n in nodes]
        except Exception as e:
            print(f"Error retrieving timestamps for project ID {project_id}: {e}")
            return None
