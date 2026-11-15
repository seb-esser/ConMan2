"""
Generate the synthetic Linked-Building-Data office series in ../lbd_office/ (office_v1 ... office_v4).

The ABox uses the Building Topology Ontology (BOT, https://w3id.org/bot#) plus a small project vocabulary
(ex:). Every file also contains an inline TBox block (class/property declarations, an OWL restriction,
the ontology header) so that the TBox/ABox partitioning is exercised. Changes per version are listed in
CHANGELOG.json.

    python make_lbd_office_series.py
"""
import json
import os

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import OWL, RDF, RDFS, XSD

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lbd_office")
BOT = Namespace("https://w3id.org/bot#")
EX = Namespace("https://example.org/tum/office#")
INST = Namespace("https://example.org/tum/office-building/")
DATASET = URIRef("https://example.org/tum/office-building")


def dec(v):
    return Literal(v, datatype=XSD.decimal)


def new_graph():
    g = Graph()
    for p, ns in (("bot", BOT), ("ex", EX), ("inst", INST), ("owl", OWL), ("rdfs", RDFS), ("xsd", XSD)):
        g.bind(p, ns)
    return g


def tbox(g, version, meeting_room=False):
    g.add((DATASET, RDF.type, OWL.Ontology))
    g.add((DATASET, OWL.imports, URIRef("https://w3id.org/bot")))
    g.add((DATASET, OWL.versionInfo, Literal(str(version))))
    g.add((EX.Office, RDF.type, OWL.Class))
    g.add((EX.Office, RDFS.subClassOf, BOT.Space))
    g.add((EX.Office, RDFS.label, Literal("Office", lang="en")))
    g.add((EX.FireDoor, RDF.type, OWL.Class))
    restriction = BNode()
    g.add((EX.FireDoor, RDFS.subClassOf, restriction))
    g.add((restriction, RDF.type, OWL.Restriction))
    g.add((restriction, OWL.onProperty, EX.hasProperty))
    g.add((restriction, OWL.someValuesFrom, EX.FireRatingProperty))
    g.add((EX.area, RDF.type, OWL.DatatypeProperty))
    g.add((EX.area, RDFS.domain, BOT.Space))
    g.add((EX.area, RDFS.range, XSD.decimal))
    g.add((EX.hasProperty, RDF.type, OWL.ObjectProperty))
    if meeting_room:
        g.add((EX.MeetingRoom, RDF.type, OWL.Class))
        g.add((EX.MeetingRoom, RDFS.subClassOf, BOT.Space))


def prop(g, element, name, value, unit=None):
    b = BNode()
    g.add((element, EX.hasProperty, b))
    g.add((b, EX.name, Literal(name)))
    g.add((b, EX.value, value))
    if unit:
        g.add((b, EX.unit, Literal(unit)))
    return b


def v1():
    g = new_graph()
    tbox(g, 1)
    g.add((INST.site, RDF.type, BOT.Site))
    g.add((INST.site, RDFS.label, Literal("TUM Stammgelände", lang="de")))
    g.add((INST.site, BOT.hasBuilding, INST.building))
    g.add((INST.building, RDF.type, BOT.Building))
    g.add((INST.building, RDFS.label, Literal("N1")))
    for storey, elevation, spaces in (("storey0", "0.0", ("space001", "space002")), ("storey1", "3.5", ("space101",))):
        g.add((INST.building, BOT.hasStorey, INST[storey]))
        g.add((INST[storey], RDF.type, BOT.Storey))
        g.add((INST[storey], EX.elevation, dec(elevation)))
        for s in spaces:
            g.add((INST[storey], BOT.hasSpace, INST[s]))
    g.add((INST.space001, RDF.type, BOT.Space))
    g.add((INST.space001, RDF.type, EX.Office))
    g.add((INST.space001, RDFS.label, Literal("Büro 0.01", lang="de")))
    g.add((INST.space001, RDFS.label, Literal("Office 0.01", lang="en")))
    g.add((INST.space001, EX.area, dec("24.5")))
    g.add((INST.space001, BOT.adjacentElement, INST.wall1))
    g.add((INST.space001, BOT.adjacentElement, INST.wall2))
    g.add((INST.space001, BOT.containsElement, INST.desk1))
    g.add((INST.space002, RDF.type, BOT.Space))
    g.add((INST.space002, RDFS.label, Literal("Flur 0.02", lang="de")))
    g.add((INST.space002, EX.area, dec("12.0")))
    g.add((INST.space002, BOT.adjacentElement, INST.wall2))
    g.add((INST.space002, BOT.adjacentElement, INST.door1))
    g.add((INST.space101, RDF.type, BOT.Space))
    g.add((INST.space101, RDFS.label, Literal("Büro 1.01", lang="de")))
    g.add((INST.space101, EX.area, dec("30.25")))
    g.add((INST.space101, BOT.adjacentElement, INST.wall3))
    for e, label in (("wall1", "AW 1"), ("wall2", "IW 2"), ("wall3", "AW 3"), ("door1", "T 1"), ("desk1", "Desk 1")):
        g.add((INST[e], RDF.type, BOT.Element))
        g.add((INST[e], RDFS.label, Literal(label)))
    g.add((INST.door1, RDF.type, EX.FireDoor))
    prop(g, INST.wall1, "thickness", dec("0.365"), unit="m")
    prop(g, INST.wall2, "fireRating", Literal("F90"))
    prop(g, INST.door1, "fireRating", Literal("T30"))
    boundary = BNode()
    Collection(g, boundary, [Literal("0 0"), Literal("5 0"), Literal("5 6"), Literal("0 6")])
    g.add((INST.wall3, EX.boundary, boundary))
    note = BNode()  # root blank node (never an object)
    g.add((note, RDF.type, EX.Note))
    g.add((note, RDFS.comment, Literal("Survey 2026-05")))
    g.add((note, EX.about, INST.building))
    return g


def copy(g):
    h = new_graph()
    for t in g:
        h.add(t)
    return h


def find_prop(g, element, name):
    return next(b for b in g.objects(element, EX.hasProperty) if (b, EX.name, Literal(name)) in g)


def v2(prev):
    """Semantic ABox changes + a TBox-only change."""
    g = copy(prev)
    g.set((INST.space001, EX.area, dec("25.1")))
    g.remove((INST.space001, RDFS.label, Literal("Office 0.01", lang="en")))
    g.add((INST.space001, RDFS.label, Literal("Office 0.01 (renovated)", lang="en")))
    g.add((INST.space001, EX.occupancy, Literal(2)))
    g.set((find_prop(g, INST.wall2, "fireRating"), EX.value, Literal("F120")))
    g.remove((find_prop(g, INST.wall1, "thickness"), EX.unit, None))
    note = next(g.subjects(RDF.type, EX.Note))
    g.set((note, RDFS.comment, Literal("Survey 2026-06")))
    # TBox: new class and new version info -> must not show up as ABox change, only as a new fingerprint
    g.set((DATASET, OWL.versionInfo, Literal("2")))
    g.add((EX.MeetingRoom, RDF.type, OWL.Class))
    g.add((EX.MeetingRoom, RDFS.subClassOf, BOT.Space))
    return g


def v3(prev):
    """Topology: new space and wall, removed door, desk moved to another space."""
    g = copy(prev)
    door_props = list(g.objects(INST.door1, EX.hasProperty))
    for b in door_props:
        g.remove((b, None, None))
    g.remove((INST.door1, None, None))
    g.remove((None, None, INST.door1))
    g.add((INST.storey1, BOT.hasSpace, INST.space102))
    g.add((INST.space102, RDF.type, BOT.Space))
    g.add((INST.space102, RDFS.label, Literal("Büro 1.02", lang="de")))
    g.add((INST.space102, EX.area, dec("18.0")))
    g.add((INST.space102, BOT.adjacentElement, INST.wall3))
    g.add((INST.space102, BOT.adjacentElement, INST.wall4))
    g.add((INST.wall4, RDF.type, BOT.Element))
    g.add((INST.wall4, RDFS.label, Literal("IW 4")))
    prop(g, INST.wall4, "fireRating", Literal("F30"))
    g.remove((INST.space001, BOT.containsElement, INST.desk1))
    g.add((INST.space101, BOT.containsElement, INST.desk1))
    return g


def v4(prev):
    """List insertion, added type, IRI rename, extra language."""
    g = copy(prev)
    old = next(g.objects(INST.wall3, EX.boundary))
    items = list(Collection(g, old))
    Collection(g, old).clear()
    g.remove((INST.wall3, EX.boundary, old))
    new = BNode()
    Collection(g, new, items[:2] + [Literal("5 3")] + items[2:])
    g.add((INST.wall3, EX.boundary, new))
    g.add((INST.space002, RDF.type, EX.Office))
    for p, o in list(g.predicate_objects(INST.desk1)):
        g.remove((INST.desk1, p, o))
        g.add((INST["desk-001"], p, o))
    for s, p in list(g.subject_predicates(INST.desk1)):
        g.remove((s, p, INST.desk1))
        g.add((s, p, INST["desk-001"]))
    g.add((INST.space101, RDFS.label, Literal("Bureau 1.01", lang="fr")))
    return g


CHANGELOG = {
    "v1": "Initial LBD office: site, building, 2 storeys, 3 spaces, 5 elements; literals with datatypes and "
          "languages, PROPS-style blank-node properties, an rdf:List, a root blank node; inline TBox "
          "(ontology header, 2 classes, OWL restriction, 2 properties).",
    "v2": "ABox semantic: space001 area 24.5->25.1, English label changed, ex:occupancy added; wall2 fire rating "
          "F90->F120 (inside a blank node); unit of wall1 thickness removed; note comment changed. "
          "TBox only: owl:versionInfo 2, class ex:MeetingRoom added.",
    "v3": "ABox topology: door1 removed with its property; space102 and wall4 added; desk1 moved from "
          "space001 to space101 (re-targeted relation).",
    "v4": "wall3 boundary list gets a point inserted; space002 additionally typed ex:Office; desk1 renamed to "
          "desk-001 (IRI change = delete + add); French label for space101.",
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    versions = {"v1": v1()}
    versions["v2"] = v2(versions["v1"])
    versions["v3"] = v3(versions["v2"])
    versions["v4"] = v4(versions["v3"])
    for name, g in versions.items():
        g.serialize(destination=os.path.join(OUT, f"office_{name}.ttl"), format="turtle")
    with open(os.path.join(OUT, "CHANGELOG.json"), "w", encoding="utf-8") as f:
        json.dump(CHANGELOG, f, indent=2, ensure_ascii=False)
    print("written to", os.path.abspath(OUT))
