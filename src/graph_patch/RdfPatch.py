"""
RDF Patch increments (increment_representation = "rdf-patch", RDF projects only).

The increment between two versions of an RDF dataset is written as an RDF Patch
(https://afs.github.io/rdf-patch/): header lines, then a transaction of deleted (D) and added (A) triples.

    H id   <urn:conman2:<project>:<ts_updt>> .
    H prev <urn:conman2:<project>:<ts_init>> .
    H conman2-meta-prev "<json>" .            dataset metadata of the init version (TBox lock, prefixes, ...)
    H conman2-meta      "<json>" .            dataset metadata of the updt version
    TX .
    D <s> <p> <o> .
    A <s> <p> <o> .
    TC .

Blank nodes: both versions are canonicalised (rdflib to_canonical_graph) before the triple-set difference,
so blank-node labels in the patch are reproducible. When applying, the current version is canonicalised
the same way, so a patch's D lines match the current graph. As noted in the W3C RDF canonicalisation
spec, a change in a blank node's neighbourhood can relabel other blank nodes, so the patch can contain
more triples than strictly changed. It is still exact.

The patch can be applied in both directions (reverse: A and D swap roles). Application is strict: a
triple to delete must exist, otherwise the patch does not belong to the current version and an error
is raised.
"""
import io
import json
import os
import re

from rdflib import BNode, Graph, URIRef
from rdflib.compare import graph_diff, to_canonical_graph
from rdflib.plugins.parsers.ntriples import W3CNTriplesParser

INCREMENT_RDF_PATCH = "rdf-patch"
_TERM = re.compile(r'<[^>]*>|_:[A-Za-z0-9_\-]+|"(?:[^"\\]|\\.)*"(?:@[A-Za-z][A-Za-z0-9-]*|\^\^<[^>]*>)?')


def rdf_patch_file(project_id: str, timestamp_init: str, timestamp_updt: str, patch_dir: str = "patch_data") -> str:
    return os.path.join(patch_dir, f"Patch_RDF_{project_id}_{timestamp_init}_{timestamp_updt}.rdfp")


def find_rdf_patch(project_id: str, timestamp_a: str, timestamp_b: str, patch_dir: str = "patch_data"):
    """(path, reverse) of the patch between a and b, whichever direction it was created in."""
    forward = rdf_patch_file(project_id, timestamp_a, timestamp_b, patch_dir)
    if os.path.exists(forward):
        return forward, False
    backward = rdf_patch_file(project_id, timestamp_b, timestamp_a, patch_dir)
    if os.path.exists(backward):
        return backward, True
    raise FileNotFoundError(f"No RDF patch between {timestamp_a} and {timestamp_b} for project {project_id} in {patch_dir}.")


def _nt_lines(triples) -> list:
    g = Graph()
    for t in triples:
        g.add(t)
    return sorted(line for line in g.serialize(format="nt", encoding="utf-8").decode("utf-8").splitlines() if line.strip())


def _literal_header(value: dict) -> str:
    return _nt_lines([(URIRef("urn:x"), URIRef("urn:x"), _json_literal(value))])[0].split(" ", 2)[2].rsplit(" .", 1)[0]


def _json_literal(value):
    from rdflib import Literal
    return Literal(json.dumps(value, sort_keys=True))


class _Sink:
    def __init__(self):
        self.triples = []

    def triple(self, s, p, o):
        self.triples.append((s, p, o))


def _parse_term(token: str):
    if token.startswith("<"):
        return URIRef(token[1:-1])
    if token.startswith("_:"):
        return BNode(token[2:])
    sink = _Sink()
    W3CNTriplesParser(sink).parse(io.StringIO(f"<urn:s> <urn:p> {token} .\n"))
    return sink.triples[0][2]


def _parse_triple(rest: str):
    tokens = _TERM.findall(rest)
    if len(tokens) != 3:
        raise ValueError(f"Cannot parse RDF Patch triple: {rest!r}")
    return tuple(_parse_term(t) for t in tokens)


def create_rdf_patch(graph_init: Graph, graph_updt: Graph, project_id: str, timestamp_init: str, timestamp_updt: str,
                     meta_init: dict = None, meta_updt: dict = None) -> str:
    _, deleted, added = graph_diff(graph_init, graph_updt)
    lines = [
        f"H id <urn:conman2:{project_id}:{timestamp_updt}> .",
        f"H prev <urn:conman2:{project_id}:{timestamp_init}> .",
        f"H conman2-meta-prev {_literal_header(meta_init or {})} .",
        f"H conman2-meta {_literal_header(meta_updt or {})} .",
        "TX .",
    ]
    lines += [f"D {line}" for line in _nt_lines(deleted)]
    lines += [f"A {line}" for line in _nt_lines(added)]
    lines.append("TC .")
    return "\n".join(lines) + "\n"


def write_rdf_patch(text: str, project_id: str, timestamp_init: str, timestamp_updt: str, patch_dir: str = "patch_data") -> str:
    os.makedirs(patch_dir, exist_ok=True)
    path = rdf_patch_file(project_id, timestamp_init, timestamp_updt, patch_dir)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def parse_rdf_patch(text: str) -> dict:
    patch = {"headers": {}, "deletes": [], "adds": []}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        op, _, rest = line.partition(" ")
        if op == "H":
            name, _, value = rest.partition(" ")
            term = _parse_term(_TERM.findall(value)[0])
            patch["headers"][name] = json.loads(str(term)) if name.startswith("conman2-meta") else str(term)
        elif op in ("TX", "TC"):
            continue
        elif op == "D":
            patch["deletes"].append(_parse_triple(rest))
        elif op == "A":
            patch["adds"].append(_parse_triple(rest))
        else:
            raise ValueError(f"Unsupported RDF Patch line: {raw!r}")
    return patch


def apply_rdf_patch(graph: Graph, patch: dict, reverse: bool = False) -> Graph:
    """Apply a parsed patch to (a canonicalised copy of) graph and return the result."""
    result = Graph()
    for t in to_canonical_graph(graph):   # read-only aggregate -> copy
        result.add(t)
    for prefix, ns in graph.namespaces():
        result.bind(prefix, ns, override=True)
    removals, additions = (patch["adds"], patch["deletes"]) if reverse else (patch["deletes"], patch["adds"])
    missing = [t for t in removals if t not in result]
    if missing:
        raise ValueError(f"RDF patch does not match the current version: {len(missing)} triple(s) to delete are missing, "
                         f"e.g. {missing[0]}")
    for t in removals:
        result.remove(t)
    for t in additions:
        result.add(t)
    return result


def target_meta(patch: dict, reverse: bool = False) -> dict:
    return patch["headers"].get("conman2-meta-prev" if reverse else "conman2-meta", {})
