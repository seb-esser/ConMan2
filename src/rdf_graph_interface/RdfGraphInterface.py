"""
RdfGraphInterface: RDF graphs (Turtle, N-Triples, N3, RDF/XML, JSON-LD) <-> ConMan2 graph meta model.

Mapping (docs/rdf-and-aec-artifacts.md, section 1.1):

  dataset (project anchor)      PrimaryNode  EntityType "RdfDataset", GlobalId = project id
  IRI (subject or object)       PrimaryNode  EntityType "Resource",   GlobalId = IRI
  blank node                    SecondaryNode EntityType "BlankNode", identified by its unique path
  literal                       InlineNode   EntityType "Literal",    wrappedValue = N-Triples form
                                             ("24.5"^^<xsd:decimal>, "Buero"@de) - lossless
  triple s p o                  rel edge s -> o, rel_type = predicate IRI

Predicates are sets in RDF, so list_index has no meaning. Objects of the same (subject, predicate) are
ranked by a deterministic sort key (IRI string, literal N-Triples form, blank-node content hash) to
give stable list indices as long as the set does not change. Blank nodes that are never an object
("root" blank nodes, e.g. `[] a ex:Note`) hang off the dataset node via rel "subjects".

With tbox_mode="exclude" (default) only the ABox is stored. The TBox is replaced by a fingerprint on
the dataset node (meta__tbox: hash, size, imports), so a TBox change shows up as one semantic change
of the dataset node and not as a diff of the ontology.
"""
import hashlib
import json
import os
import re

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF
from rdflib.util import from_n3

from graph_io.lpg_io import Decomposition, send_to_neo4j, send_to_nx, retrieve_from_neo4j, retrieve_from_nx
from neo4j_core.neo4j_model import PrimaryNode
from rdf_graph_interface.tbox_abox import partition, tbox_fingerprint

ET_DATASET = "RdfDataset"
ET_RESOURCE = "Resource"
ET_BLANK = "BlankNode"
ET_LITERAL = "Literal"
REL_SUBJECTS = "subjects"
META_PREFIXES = "meta__prefixes"
META_TBOX = "meta__tbox"
META_TBOX_MODE = "meta__tbox_mode"
META_DATASET_IRI = "meta__dataset_iri"

DATASET_TYPES = (URIRef("http://rdfs.org/ns/void#Dataset"), URIRef("http://www.w3.org/ns/dcat#Dataset"))

FORMATS = {".ttl": "turtle", ".nt": "nt", ".n3": "n3", ".rdf": "xml", ".owl": "xml", ".jsonld": "json-ld"}
RDF_EXTENSIONS = tuple(FORMATS)


def rdf_format(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext not in FORMATS:
        raise ValueError(f"Unsupported RDF file {path!r}. Supported: {', '.join(FORMATS)}")
    return FORMATS[ext]


def load_rdf(path: str) -> Graph:
    g = Graph()
    g.parse(path, format=rdf_format(path))
    return g


_PROJECT_ID = re.compile(r"[A-Za-z0-9._-]+")


def project_slug(iri: str) -> str:
    """Filename-safe project id from a dataset IRI (patch files are named after the project id, and the
    anchor's GlobalId must not collide with the Resource node of the same IRI)."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", iri)).strip("_")
    return slug or "dataset"


def validate_project_id(project_id: str) -> str:
    if not _PROJECT_ID.fullmatch(project_id or ""):
        raise ValueError(f"RDF project id {project_id!r} must match [A-Za-z0-9._-]+ (it is used in patch file names).")
    return project_id


def dataset_iri_from_graph(g: Graph):
    """owl:Ontology header IRI, or the single void:/dcat:Dataset subject."""
    candidates = sorted({str(s) for s in g.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)})
    if not candidates:
        candidates = sorted({str(s) for t in DATASET_TYPES for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)})
    return candidates[0] if len(candidates) == 1 else None


class RdfGraphInterface:

    graph_providers = ("neo4j", "networkx")
    tbox_modes = ("exclude", "include")

    def __init__(self, graph_provider: str = "neo4j", tbox_mode: str = "exclude") -> None:
        if graph_provider not in self.graph_providers:
            raise ValueError(f"Graph provider '{graph_provider}' not supported. Available providers: {self.graph_providers}")
        if tbox_mode not in self.tbox_modes:
            raise ValueError(f"tbox_mode must be one of {self.tbox_modes}")
        self.graph_provider = graph_provider
        self.tbox_mode = tbox_mode

    ########################
    ### Helper Functions ###
    ########################

    @staticmethod
    def __bnode_hashes(g: Graph) -> dict:
        """Content hash per blank node (recursive over its outgoing triples, cycle-safe)."""
        cache = {}

        def h(node, stack):
            if node in cache:
                return cache[node]
            if node in stack:
                return "cycle"
            stack = stack | {node}
            parts = sorted(f"{p}|{key(o, stack)}" for p, o in g.predicate_objects(node))
            cache[node] = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
            return cache[node]

        def key(o, stack):
            if isinstance(o, BNode):
                return "b:" + h(o, stack)
            return ("i:" if isinstance(o, URIRef) else "l:") + o.n3()

        for b in {t for t in g.all_nodes() if isinstance(t, BNode)}:
            h(b, frozenset())
        return cache

    @staticmethod
    def __sort_key(o, bnode_hash):
        if isinstance(o, URIRef):
            return (0, str(o))
        if isinstance(o, Literal):
            return (1, o.n3())
        return (2, bnode_hash.get(o, ""))

    def __decompose(self, g: Graph, timestamp: str, project_id: str, tbox_meta: dict = None,
                    dataset_iri: str = None) -> Decomposition:
        d = Decomposition(timestamp)
        root = d.node("PrimaryNode", ET_DATASET, "ds", validate_project_id(str(project_id)))
        if dataset_iri:
            root[META_DATASET_IRI] = dataset_iri
        root[META_PREFIXES] = json.dumps(sorted((p, str(ns)) for p, ns in g.namespaces()))
        root[META_TBOX_MODE] = self.tbox_mode
        if tbox_meta is not None:
            root[META_TBOX] = json.dumps(tbox_meta, sort_keys=True)

        bnode_hash = self.__bnode_hashes(g)
        nodes = {}

        def iri_node(iri):
            if iri not in nodes:
                nodes[iri] = d.node("PrimaryNode", ET_RESOURCE, f"r:{iri}", str(iri))
            return nodes[iri]

        for term in sorted({t for t in g.all_nodes() if isinstance(t, URIRef)}, key=str):
            iri_node(term)

        def bnode_node(b, key):
            if b not in nodes:
                nodes[b] = d.node("SecondaryNode", ET_BLANK, key)
                pending.append(b)
            return nodes[b]

        pending = []
        objects = set(g.objects())
        root_bnodes = sorted((b for b in g.subjects() if isinstance(b, BNode) and b not in objects),
                             key=lambda b: bnode_hash.get(b, ""))
        for i, b in enumerate(root_bnodes):
            d.rel(root, bnode_node(b, d.child_key(root, REL_SUBJECTS, i)), REL_SUBJECTS, i)

        def emit(subject):
            src = nodes[subject]
            for p in sorted(set(g.predicates(subject)), key=str):
                objs = sorted(g.objects(subject, p), key=lambda o: self.__sort_key(o, bnode_hash))
                for i, o in enumerate(objs):
                    if isinstance(o, Literal):
                        d.inline(src, str(p), i, ET_LITERAL, o.n3())
                    elif isinstance(o, URIRef):
                        d.rel(src, iri_node(o), str(p), i)
                    else:
                        d.rel(src, bnode_node(o, d.child_key(src, str(p), i)), str(p), i)

        for s in sorted({s for s in g.subjects() if isinstance(s, URIRef)}, key=str):
            emit(s)
        # Blank nodes are emitted once reached (breadth-first), so their key is the first path to them.
        done = set()
        while pending:
            b = pending.pop(0)
            if b not in done:
                done.add(b)
                emit(b)
        # Blank nodes only reachable through cycles of blank nodes (no IRI, not a root): anchor them too.
        rest = sorted((b for b in g.subjects() if isinstance(b, BNode) and b not in nodes), key=lambda b: bnode_hash.get(b, ""))
        for i, b in enumerate(rest, start=len(root_bnodes)):
            d.rel(root, bnode_node(b, d.child_key(root, REL_SUBJECTS, i)), REL_SUBJECTS, i)
        while pending:
            b = pending.pop(0)
            if b not in done:
                done.add(b)
                emit(b)
        return d

    @staticmethod
    def __assemble(nodes: dict, edges: list):
        roots = [n for n, v in nodes.items() if v["kind"] == "PrimaryNode" and v["props"].get("EntityType") == ET_DATASET]
        if len(roots) != 1:
            raise Exception(f"Expected exactly one {ET_DATASET} node, found {len(roots)}.")
        root = roots[0]
        meta = {k: v for k, v in nodes[root]["props"].items() if k.startswith("meta__")}
        g = Graph()
        for prefix, ns in json.loads(meta.get(META_PREFIXES, "[]")):
            g.bind(prefix, ns, override=True)
        terms = {}
        for nid, node in nodes.items():
            if node["kind"] == "PrimaryNode" and node["props"].get("EntityType") == ET_RESOURCE:
                terms[nid] = URIRef(node["props"]["GlobalId"])
            elif node["props"].get("EntityType") == ET_BLANK:
                terms[nid] = BNode()
            elif node["props"].get("EntityType") == ET_LITERAL:
                terms[nid] = from_n3(node["props"]["wrappedValue"])
        for src, tgt, rel_type, _ in edges:
            if src == root:
                continue
            g.add((terms[src], URIRef(rel_type), terms[tgt]))
        return g, {"project_id": nodes[root]["props"]["GlobalId"],
                   "dataset_iri": meta.get(META_DATASET_IRI),
                   "tbox": json.loads(meta[META_TBOX]) if META_TBOX in meta else None,
                   "tbox_mode": meta.get(META_TBOX_MODE)}

    ######################
    ### Main Functions ###
    ######################

    @staticmethod
    def default_graph_file(timestamp: str) -> str:
        return f"networkx_graph_{timestamp}.gpickle"

    def split(self, g: Graph):
        """(versioned graph, tbox fingerprint or None) according to tbox_mode."""
        if self.tbox_mode == "include":
            return g, None
        abox, tbox = partition(g)
        return abox, tbox_fingerprint(tbox)

    def rdflib_2_graph(self, g: Graph, timestamp: str, project_id: str, tbox_meta: dict = None,
                       batch_size: int = 20000, graph_file: str = None, dataset_iri: str = None) -> Decomposition:
        """Store an (already partitioned) rdflib graph as one graph version."""
        d = self.__decompose(g, timestamp, project_id, tbox_meta, dataset_iri)
        if self.graph_provider == "neo4j":
            send_to_neo4j(d, batch_size)
        else:
            send_to_nx(d, graph_file or self.default_graph_file(timestamp))
        return d

    def rdf_2_graph(self, rdf_path: str, timestamp: str, project_id: str = None,
                    batch_size: int = 20000, graph_file: str = None) -> Decomposition:
        print("Loading RDF model.")
        g = load_rdf(rdf_path)
        dataset_iri = dataset_iri_from_graph(g)
        pid = project_id or (project_slug(dataset_iri) if dataset_iri else None)
        if pid is None:
            raise ValueError(f"{rdf_path}: no unique owl:Ontology / void:Dataset / dcat:Dataset IRI. Provide a project_id.")
        versioned, tbox_meta = self.split(g)
        print(f"Versioning {len(versioned)} of {len(g)} triples (tbox_mode={self.tbox_mode}).")
        d = self.rdflib_2_graph(versioned, timestamp, pid, tbox_meta, batch_size, graph_file, dataset_iri)
        print("Finished RDF parsing.")
        return d

    def graph_2_rdflib(self, timestamp: str, graph_file: str = None):
        """(rdflib Graph, meta) of one stored version."""
        if self.graph_provider == "neo4j":
            nodes, edges = retrieve_from_neo4j(timestamp)
        else:
            nodes, edges = retrieve_from_nx(timestamp, graph_file or self.default_graph_file(timestamp))
        return self.__assemble(nodes, edges)

    def graph_2_rdf(self, rdf_path: str, timestamp: str, graph_file: str = None) -> Graph:
        g, _ = self.graph_2_rdflib(timestamp, graph_file)
        if rdf_path:
            g.serialize(destination=rdf_path, format=rdf_format(rdf_path))
            print("Finished RDF file generation. ")
        return g

    @staticmethod
    def get_project_id_from_rdf_path(rdf_path: str):
        try:
            iri = dataset_iri_from_graph(load_rdf(rdf_path))
            return project_slug(iri) if iri else None
        except Exception as e:
            print(f"Error retrieving project ID from RDF file {rdf_path}: {e}")
            return None

    @staticmethod
    def get_timestamp_from_project_id(project_id: str):
        """Neo4j only: all timestamps under which this dataset exists in the DB."""
        try:
            return [n.timestamp for n in PrimaryNode.nodes.filter(GlobalId=project_id, EntityType=ET_DATASET).all()]
        except Exception as e:
            print(f"Error retrieving timestamps for project ID {project_id}: {e}")
            return None
