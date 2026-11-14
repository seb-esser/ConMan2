# Extending ConMan2 to RDF (ABox-only versioning) and to the other artefacts of an AEC project

Status: research and plan, 2026-11-14 · Branch `docs/rdf-and-aec-artifacts`
Builds on the generic diff/patch work on `feature/geojson-cli` (see
`docs/GeoJSON_CityGML_DiffPatch.md`). Nothing in this document is implemented yet.

## 0. The thesis behind the extension

The GeoJSON work showed that ConMan2's diff and patch are **format-independent** once a format is
mapped onto the meta model with three rules:

1. **Objects with persistent identity → PrimaryNode** (`GlobalId`), matched across versions by id.
2. **Objectified relations → ConnectionNode**, matched by id or by IoU of their ends.
3. **Everything else → Secondary/InlineNode**, identified by its unique path
   `(rel_type, list_index, EntityType)` from the nearest Primary/ConnectionNode.

Every additional artefact type therefore needs an *adapter* (format ⇄ graph) and possibly a few
*matching options*. It does not need a new versioning algorithm. Your assumption for RDF holds, with
two extensions that are also needed elsewhere: **unordered relations** (§1.5) and a **TBox/ABox
partition** (§1.3).

---

## 1. RDF datasets

### 1.1 Mapping RDF onto the meta model

| RDF | Node / edge | Identity | Analogue |
|---|---|---|---|
| dataset / named graph | PrimaryNode `RdfDataset` / `NamedGraph` (`GlobalId` = graph IRI) | IRI | `IfcProject`, `FeatureCollection` |
| IRI subject or object (individual) | PrimaryNode, `EntityType` = `rdf:type` (sorted list if several) or `rdfs:Resource` | the IRI is the `GlobalId`. This is a better identity than IFC GUIDs, because it is global by design | IfcRoot entities |
| membership of an individual in a named graph | ConnectionNode `GraphMembership` | `<graph>::<IRI>` | `FeatureMembership` |
| blank node | SecondaryNode | unique path from the nearest IRI node via the predicate | IFC secondary entities |
| literal | node property (single value) or InlineNode `Literal` (multi-valued); value encoded with datatype and language (`"23.5"^^xsd:decimal`, `"Wand"@de`) | path | IFC attribute values / `JsonValue` |
| triple `s p o` (o is an IRI) | `rel` edge with `rel_type` = predicate IRI (CURIE) | – | IFC attribute reference |
| `rdf:List` (`rdf:first`/`rdf:rest`) | flattened to edges with `list_index` | – | IFC `LIST` attributes |
| RDF-star triple term / reification | ConnectionNode `Statement` (`GlobalId` = hash of s, p, o) | content | objectified relation |

**Consequence for the patch.** In RDF most edges connect *two IRI nodes*, i.e. two PrimaryNodes,
and both are equivalent whenever both individuals survive. A changed object property (e.g.
`:wall1 bot:adjacentElement :wall2 → :wall3`) is then exactly a **context relation**. The
`context_relations` section introduced on `feature/patch-context-relations` (originally for IFC's
re-targeted `Representation`) is therefore the central patch mechanism for RDF. Literals go into
the semantic patch, and blank-node structures go into the topological patch.

The resulting patch is very close to the existing RDF change formats. It should be exportable as
**RDF Patch** (`A`/`D` quads; Jena RDF Delta) and as **SPARQL Update** (`DELETE DATA` / `INSERT
DATA`). That makes ConMan2 interoperable with triple stores and with Git-based RDF tools such as
Quit Store, without giving up its own path-based identity for blank nodes.

### 1.2 Blank nodes: three options

| Option | Stability | Use |
|---|---|---|
| **ConMan2 unique path** (proposed default) | stable as long as the bnode is tree-shaped below an IRI (property values, OWL restrictions, lists, ifcOWL value wrappers) | ABox diff / patch |
| **RDFC-1.0 canonical labels** (W3C Recommendation, May 2024) | deterministic for the same graph. But a change in a bnode's neighbourhood can relabel other bnodes, so a diff may show more changes than actually exist (as the spec itself notes) | content hashes / fingerprints (e.g. of a TBox, §1.3) |
| **Skolemisation** (`/.well-known/genid/…` IRIs assigned on first commit) | bnodes become IRIs and therefore PrimaryNodes | optional, for data that ConMan2 owns |

Shared or cyclic bnode structures (a bnode reached from several subjects) behave like IFC's shared
representations. The equivalence guard (1:1) and `context_relations` make them safe, but matching
quality depends on the traversal order (see the open IFC issue in the GeoJSON document).

### 1.3 Versioning the ABox only: partitioning TBox and ABox

The TBox (schema: classes, properties, axioms, shapes) should not be diffed per project. Instead,
it should be **referenced like a pinned dependency**. Only the ABox (individuals and their
assertions) is versioned. This needs a partitioner in front of the parser, which classifies each
triple in this order:

1. **Source-based (most robust).** Triples from documents that a project *imports* belong to the
   TBox: the `owl:imports` closure, plus a configured list of vocabulary namespaces or files
   (ifcOWL, BOT, PROPS, PRODUCT, bsDD exports, project ontology). Project data files form the ABox.
2. **Statement-based (for mixed files).** A triple is TBox if
   - its subject is declared as `owl:Class`, `rdfs:Class`, `owl:ObjectProperty`,
     `owl:DatatypeProperty`, `owl:AnnotationProperty`, `rdf:Property`, `owl:Ontology`, or
     `sh:NodeShape`/`sh:PropertyShape`; or
   - its predicate is a schema predicate (`rdfs:subClassOf`, `rdfs:subPropertyOf`, `rdfs:domain`,
     `rdfs:range`, `owl:equivalentClass`, `owl:inverseOf`, `owl:imports`, `owl:versionIRI`, …); or
   - it is a bnode structure reachable only from such subjects (OWL restrictions, `owl:unionOf`
     lists).

   Everything else is ABox, **including `rdf:type` assertions of individuals**, which are instance
   data.
3. **Edge cases**, reported rather than silently decided:
   - *Punning* (OWL 2: the same IRI used as class and individual).
   - *Vocabulary individuals*, e.g. enumeration values in ifcOWL or `skos:Concept`s of bsDD. These
     belong to the vocabulary although they are technically ABox. They are partitioned by source
     (rule 1) as "reference data".
   - *Project-specific classes* in a data file. The default is TBox, with a warning.

The **TBox is recorded per commit as a lock entry**, not as a diff:

```json
"tbox": {
  "https://w3id.org/bot#": {"versionIRI": "https://w3id.org/bot/0.3.2", "rdfc10_sha256": "9f2c…"},
  "https://standards.buildingsmart.org/IFC/DEV/IFC4/ADD2_TC1/OWL#": {"rdfc10_sha256": "41ab…"}
}
```

The content hash is computed over the canonicalised TBox (RDFC-1.0) and is independent of
serialisation. A TBox change is then a visible *dependency bump* in the commit. It is not a giant
diff, and the TBox itself can be versioned in its own ConMan2 project if desired.

**Inferred triples are never versioned.** Reasoner output (e.g. materialised `rdf:type` via
`rdfs:subClassOf`) is derived data, comparable to the Neo4j cache. Only asserted ABox triples are
committed. Materialisation can be re-run against the pinned TBox.

### 1.4 What can be reused unchanged

- `GraphDiff` / `GraphDiffNx` with `root_entity_type="RdfDataset"`: PrimaryNodes matched by IRI, and
  bnode subtrees matched by path.
- The open-schema semantic patch (union of keys, `null` = absent). RDF has no closed schema.
- Strict unique-path resolution, escaped paths (IRIs contain `:`, `/`, `#`, `=`; `DataHandler` now
  percent-encodes the delimiters), and identifier-safe property keys (CURIEs such as `bot:hasSpace`
  are escaped like `addr:city`).
- `context_relations`, bidirectional patches, cross-provider patch files, the timeline, and the CLI.

### 1.5 What has to be built

| # | Component | Description |
|---|---|---|
| R1 | `RdfGraphInterface` | rdflib-based (Turtle, N-Triples / N-Quads, TriG, JSON-LD, RDF/XML). Mirrors `GeoJsonGraphInterface` (decompose → same intermediate collections → Neo4j / NetworkX). Output is canonical N-Quads or Turtle (sorted), which suits git option C. |
| R2 | TBox/ABox partitioner + lock file | §1.3, plus a report of ambiguous triples. Configuration per project (`conman2.toml`: vocabularies, data files). |
| R3 | **Unordered relations** in the diff | RDF predicates are *sets*: `list_index` is arbitrary for multi-valued `:p`. Matching has to use content instead of position: `(predicate, target IRI)` for IRIs, `(predicate, literal)` for literals, `(predicate, structural hash)` for bnodes. A per-`rel_type` option `ordered: false` in `create_equivalence_relations_primary`. The same machinery is needed for the GeoJSON proposal P1/P2 and for IFC `SET` attributes, e.g. `IfcRelAggregates.RelatedObjects`. |
| R4 | Literal encoding | lexical value + datatype IRI + language tag, compared by value space where safe (`"1.0"^^xsd:decimal` = `"1.00"^^xsd:decimal`, optional). |
| R5 | Patch export / import | RDF Patch and SPARQL Update, so the patches can be replayed directly on a triple store. |
| R6 | Named graphs | one `NamedGraph` PrimaryNode per graph plus membership ConnectionNodes. An individual in several graphs is several memberships, not several nodes. |
| R7 | Scale | ifcOWL conversions are very large. Recommend LBD (BOT / PROPS / PRODUCT) for the versioned ABox, and IFC → LBD conversion as a separate, reproducible step. Use the NetworkX provider (in memory) or batched Cypher for Neo4j. |

### 1.6 SHACL

SHACL shapes are TBox-like *requirements* artefacts. They are versioned as their own project
(below, "requirements"), and each ABox commit records the shape version and its validation report
(see §2.3).

---

## 2. A version management system for all artefacts of an AEC project

### 2.1 Adapter architecture

The CLI's `ModelFormats` helper (on `feature/geojson-cli`) is the seed of a registry. Proposed
interface:

```python
class ArtifactAdapter(Protocol):
    format_id: str                      # "ifc", "geojson", "rdf", "ids", "mvdxml", "bcf", …
    root_entity_type: str               # project anchor in the graph
    def detect(self, path) -> bool: ...
    def project_id(self, path) -> str: ...
    def to_graph(self, path, timestamp, provider): ...      # decompose with identity rules
    def from_graph(self, timestamp, provider, out_path): ...
    def canonical_text(self, path) -> str: ...               # git clean filter / textconv
    match_options: dict                 # ordered / unordered rel_types, IoU rules, tolerances
    links(self, timestamp) -> list[CrossLink]               # references into other artefacts (§2.3)
```

Most formats are covered by **three generic adapters plus configuration**, so not every format needs
its own code:

- **Generic XML adapter.** Elements → nodes; attributes and text → properties; child order →
  `list_index` (or unordered, per element). Configured by an *identity map* (XPath → id attribute),
  e.g. `//ConceptTemplate/@uuid`.
- **Generic JSON adapter.** This is the GeoJSON adapter generalised, with identity rules as JSONPath.
- **RDF adapter** (§1).

Binary artefacts (point clouds, meshes, images, PDFs, native authoring files) are **not**
graph-versioned. They go to Git LFS. ConMan2 records their content hash and metadata, and links
them via §2.3.

### 2.2 Artefact catalogue

| Artefact | Encoding | Persistent identity → PrimaryNode | Relations → Connection / context | Notes |
|---|---|---|---|---|
| **IFC** 2x3 / 4 / 4.3 | STEP, ifcXML, ifcJSON | `GlobalId` | `IfcRel*` | done; open issue with regenerated type GUIDs |
| **CityGML 3.0** | GeoJSON (done), CityJSON 2.0, GML | feature id / `gml:id` | CityObjectRelation, `parent` | CityJSON's `vertices` array = shared positions |
| **IDS 1.0** (buildingSMART, June 2024) | XML (XSD) | `specification` by `identifier`/`name` (the identifier is optional → configure a fallback) | — | facets (entity, attribute, property, classification, material, partOf) as Secondary below applicability / requirements. Facet order has no meaning → unordered (R3) |
| **mvdXML 1.1** (1.2 is not a formal standard yet) | XML | `uuid` of ModelView, ConceptRoot, Concept, ConceptTemplate, ExchangeRequirement | template references by uuid → ConnectionNode / context relation; sub-templates | TemplateRules / AttributeRules as Secondary; rule strings stay semantic values (later possibly parsed into a grammar tree) |
| **BCF 3.0** | ZIP (markup.bcf, .bcfv viewpoints, PNG snapshots) or BCF API JSON | Topic Guid, Comment Guid, Viewpoint Guid | component references → **IFC GlobalIds** (cross-artefact) | snapshots → LFS; comment threads are append-mostly |
| **bsDD** | JSON / RDF (API) | dictionary / class / property URIs | class–property relations | vocabulary → treated as TBox / reference data (§1.3); pinned per project |
| **ICDD** (ISO 21597-1/-2) | ZIP + `Index.rdf` + linksets (RDF, Linkset / ExtendedLinkset ontology) | container and document IRIs | links (RDF) → **cross-artefact links** | the container is a natural "superproject" (§2.4); every contained document is versioned by its own adapter, linksets by the RDF adapter |
| **SHACL shapes** | RDF | shape IRIs | `sh:property` … | requirements artefact |
| **COBie** | spreadsheet / CSV | `Name` per sheet (+ sheet) | foreign-key columns | ifcopenshell can derive it from IFC → often a *derived* artefact |
| **GAEB DA XML** (bills of quantities, DE) | XML | OZ (ordinal number) + item ids | quantities ↔ BIM elements | very relevant for German projects; generic XML adapter |
| **schedules** (MS Project XML, IFC 4D) | XML / IFC | task UIDs | task dependencies, task ↔ element | |
| **LandXML / gbXML** | XML | element ids | | generic XML adapter |
| **point clouds, meshes, drawings (PDF), native files** | binary | content hash | links | Git LFS + metadata; no graph diff |

### 2.3 Cross-artefact consistency

The real benefit of one system for all artefacts is that it can **check the links between them on
every commit**:

- BCF topics, ICDD links, quantity takeoffs, and schedule tasks reference IFC GlobalIds. If an IFC
  patch deletes a PrimaryNode, the topological patch shows it directly, and every artefact still
  referencing it gets a *dangling link* warning (or a blocking check).
- IDS / SHACL / mvdXML are requirements. Each model commit can store `validated-against: <IDS
  version>` plus a result summary, comparable to CI status checks. A new IDS version re-validates the
  pinned model versions.
- The links are themselves data (ICDD linksets) and are versioned with the RDF adapter.

### 2.4 Project-level versions ("superproject")

Individual artefacts have their own timelines. A project milestone (e.g. a design freeze or an ISO
19650 information exchange) pins one version of every artefact, analogous to git submodules or an
ICDD container:

```json
{"milestone": "LP3-freeze-2027-03",
 "artifacts": {"arc.ifc": "ts…", "str.ifc": "ts…", "requirements.ids": "ts…", "issues.bcf": "ts…",
               "site.geojson": "ts…", "links.ttl": "ts…"},
 "checks": {"ids": "passed 412/415", "links": "2 dangling"}}
```

ICDD can serve as the **exchange format** of such a milestone. The container is the snapshot, and
ConMan2 holds the history behind it. Combined with the git integration (`docs/git-integration.md`),
a milestone is simply a tagged git commit whose ConMan2 lock file pins all artefact versions.

### 2.5 Roadmap

| Phase | Content | Depends on |
|---|---|---|
| 1 | Adapter registry + interface (refactor `ModelFormats`, IFC and GeoJSON as the first adapters); per-project config | — |
| 2 | **Unordered relations (R3)** and sequence alignment (GeoJSON P1) in `GraphDiff` / `GraphDiffNx` | 1 |
| 3 | RDF adapter (R1, R4, R6) + TBox/ABox partitioner and lock file (R2); RDF Patch / SPARQL Update export (R5) | 2 |
| 4 | Generic XML adapter → IDS 1.0, mvdXML 1.1, GAEB, LandXML; generic JSON adapter → BCF API JSON | 1, 2 |
| 5 | BCF ZIP and ICDD containers (composite artefacts: adapter per part + LFS for binaries) | 3, 4 |
| 6 | Cross-artefact link checks, requirement validation records, milestones | 3–5 |
| 7 | Git integration (diff/merge drivers per adapter, canonical text per adapter) | 1 + `docs/git-integration.md` |

Test data per phase follows the pattern of `00_sampleData/GeoJSON`: a controlled vN series with a
CHANGELOG per artefact type, plus real data where licences permit (e.g. buildingSMART IDS / mvdXML
examples, the 3DBAG CityJSON tiles, LBD conversions of the existing IFC fixtures).

---

## Sources

- RDF versioning: [Arndt et al., *Decentralized Collaborative Knowledge Management using Git* (Quit Store)](https://arxiv.org/pdf/1805.03721); [Taelman et al., OSTRICH / bidirectional delta chains](https://content.iospress.com:443/articles/semantic-web/sw210449); [Towards Fully-fledged Archiving for RDF Datasets](https://semantic-web-journal.net/node/2538); [Evaluating Systems and Benchmarks for Archiving Evolving Linked Datasets](https://www.semantic-web-journal.net/node/1605)
- [W3C RDF Dataset Canonicalization (RDFC-1.0), Recommendation 21 May 2024](https://w3.org/TR/2024/REC-rdf-canon-20240521/)
- Linked Building Data / TBox–ABox: [LDAC 2018 paper](https://ceur-ws.org/Vol-2159/04paper.pdf), [CEUR Vol-2213](https://ceur-ws.org/Vol-2213/paper4.pdf), [CEUR Vol-3081](https://ceur-ws.org/Vol-3081/11paper.pdf), [building ontology comparison (2026)](https://arxiv.org/html/2603.14374v1)
- IDS: [Wikipedia: Information Delivery Specification](https://en.wikipedia.org/wiki/Information_Delivery_Specification), [buildingSMART IDS documentation (metadata)](https://github.com/buildingSMART/IDS/blob/master/Documentation/ids-metadata.md), [openbimrs/ids](https://github.com/openbimrs/ids), [Nordic BIM: What is IDS](https://www.nordicbim.com/en/insights/what-is-the-buildingsmart-ids-standard)
- mvdXML: [buildingSMART mvdXML repository](https://uithub.com/buildingSMART/mvdXML), [mvdXML overview](https://hujb2000.gitbooks.io/ifcspecification/content/en/specifications/mvdXML_overview.html), [MVDLite (arXiv 1909.06997)](https://arxiv.org/pdf/1909.06997), [python-mvdxml](https://www.github.com/opensourceBIM/python-mvdxml)
- ICDD: [AS ISO 21597.1:2021](https://store.standards.org.au/product/as-iso-21597-1-2021), [CEUR Vol-3633 paper 3 (ICDD and Linked Data)](https://ceur-ws.org/Vol-3633/paper3.pdf), [ICDD ontology documentation](https://rub-informatik-im-bauwesen.github.io/aas/submodels/icdd/)
