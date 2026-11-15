"""
TBox / ABox partitioning of an RDF graph (see docs/rdf-and-aec-artifacts.md, section 1.3).

Statement-based rules, applied in this order:
  1. TBox subjects: everything typed as a class, property, ontology header, OWL restriction or SHACL
     shape (TBOX_TYPES). All triples of these subjects are TBox, including their labels and comments.
  2. TBox predicates: schema predicates (rdfs:subClassOf, rdfs:domain, owl:imports, ...) make a triple
     TBox regardless of its subject.
  3. Blank nodes that are reachable from TBox triples (OWL restrictions, owl:unionOf lists, SHACL
     property shapes) belong to the TBox with all their triples.
Everything else is ABox, in particular rdf:type assertions of individuals.

The TBox is not versioned. It is pinned by a fingerprint: a SHA-256 over the canonicalised TBox
(rdflib's canonical blank-node labelling, then sorted N-Triples), which does not depend on the
serialisation or on blank-node labels in the source file.
"""
import hashlib

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.compare import to_canonical_graph
from rdflib.namespace import OWL, RDF, RDFS

SH = "http://www.w3.org/ns/shacl#"

TBOX_TYPES = {
    OWL.Class, RDFS.Class, RDF.Property, OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty,
    OWL.OntologyProperty, OWL.TransitiveProperty, OWL.SymmetricProperty, OWL.AsymmetricProperty,
    OWL.ReflexiveProperty, OWL.IrreflexiveProperty, OWL.FunctionalProperty, OWL.InverseFunctionalProperty,
    OWL.Ontology, OWL.Restriction, OWL.AllDisjointClasses, OWL.AllDisjointProperties, RDFS.Datatype,
    URIRef(SH + "NodeShape"), URIRef(SH + "PropertyShape"),
}

TBOX_PREDICATES = {
    RDFS.subClassOf, RDFS.subPropertyOf, RDFS.domain, RDFS.range,
    OWL.equivalentClass, OWL.equivalentProperty, OWL.inverseOf, OWL.disjointWith, OWL.propertyDisjointWith,
    OWL.complementOf, OWL.unionOf, OWL.intersectionOf, OWL.oneOf, OWL.disjointUnionOf,
    OWL.onProperty, OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue, OWL.cardinality,
    OWL.minCardinality, OWL.maxCardinality, OWL.qualifiedCardinality, OWL.onClass, OWL.propertyChainAxiom,
    OWL.imports, OWL.versionIRI, OWL.versionInfo, OWL.priorVersion, OWL.backwardCompatibleWith,
    OWL.incompatibleWith, OWL.deprecated,
}


def partition(graph: Graph):
    """Split a graph into (abox, tbox). Both are new rdflib Graphs; namespace bindings are copied."""
    tbox_subjects = {s for s, o in graph.subject_objects(RDF.type) if o in TBOX_TYPES}
    tbox_triples = {t for t in graph if t[0] in tbox_subjects or t[1] in TBOX_PREDICATES}

    # Blank-node closure of the TBox.
    frontier = [o for _, _, o in tbox_triples if isinstance(o, BNode)]
    seen = set()
    while frontier:
        node = frontier.pop()
        if node in seen:
            continue
        seen.add(node)
        for t in graph.triples((node, None, None)):
            tbox_triples.add(t)
            if isinstance(t[2], BNode):
                frontier.append(t[2])

    abox, tbox = Graph(), Graph()
    for prefix, ns in graph.namespaces():
        abox.bind(prefix, ns, override=True)
        tbox.bind(prefix, ns, override=True)
    for t in graph:
        (tbox if t in tbox_triples else abox).add(t)
    return abox, tbox


def canonical_ntriples(graph: Graph) -> str:
    canonical = to_canonical_graph(graph)
    lines = sorted(f"{s.n3()} {p.n3()} {o.n3()} ." for s, p, o in canonical)
    return "\n".join(lines) + ("\n" if lines else "")


def tbox_fingerprint(tbox: Graph) -> dict:
    """Lock entry of a TBox: hash, size and imported ontologies."""
    return {
        "sha256": hashlib.sha256(canonical_ntriples(tbox).encode("utf-8")).hexdigest(),
        "triples": len(tbox),
        "imports": sorted(str(o) for o in tbox.objects(None, OWL.imports)),
        "canonicalisation": "rdflib to_canonical_graph + sorted N-Triples",
    }


def is_literal(term) -> bool:
    return isinstance(term, Literal)
