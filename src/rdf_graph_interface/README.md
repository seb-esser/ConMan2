# RdfGraphInterface: RDF ⇄ ConMan2 graph

Reads Turtle, N-Triples, N3, RDF/XML (`.rdf`, `.owl`) and JSON-LD (`.jsonld`) with rdflib, and
stores the graph in the ConMan2 meta model on Neo4j or NetworkX (shared writer: `graph_io/lpg_io.py`).

| RDF | Node | Identity |
|---|---|---|
| dataset (project) | PrimaryNode `RdfDataset` | project id = filename-safe slug of the `owl:Ontology` / `void:Dataset` / `dcat:Dataset` IRI (or given explicitly). The IRI is kept in `meta__dataset_iri`. |
| IRI | PrimaryNode `Resource` | `GlobalId` = IRI |
| blank node | SecondaryNode `BlankNode` | unique path from the first IRI that reaches it. Root blank nodes hang off the dataset via `subjects`. |
| literal | InlineNode `Literal` | `wrappedValue` = N-Triples form (datatype and language preserved) |
| triple | `rel` edge | `rel_type` = predicate IRI. `list_index` = rank among the objects of (s, p), by a deterministic sort key. |

**TBox/ABox** (`tbox_abox.py`, rules in `docs/rdf-and-aec-artifacts.md` §1.3). With
`tbox_mode="exclude"`, only the ABox is stored. The TBox is replaced by a fingerprint on the dataset
node (`meta__tbox`: SHA-256 over the canonicalised, sorted N-Triples, plus triple count and
`owl:imports`), so a TBox change appears as one semantic change of the dataset node. The
canonicalisation is rdflib's `to_canonical_graph`, not W3C RDFC-1.0, because rdflib does not
implement RDFC-1.0. Switching to RDFC-1.0 would only change the hash value.

The existing diff/patch apply unchanged (`root_entity_type="RdfDataset"`). Changed object
properties between surviving resources show up as `context_relations`. Changed literals show up in
the semantic patch. Blank-node structures show up in the topological patch.

**Known limitation.** Multi-valued predicates are sets, but they are matched by rank (see R3 in
the design document). Adding a value can therefore shift the ranks of others. The patch stays
correct, it is just larger than necessary.
