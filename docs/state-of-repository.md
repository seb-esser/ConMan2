# ConMan2 – state of the repository (master @ 85b6e2f)

Assessed 2026-11-14. This describes `master`. The findings were fixed on separate branches,
listed in the last column.

## What exists

| Component | Files | State |
|---|---|---|
| IFC ⇄ graph (Neo4j) | `ifc_graph_interface/IfcGraphInterface.py` | works; bulk `UNWIND` import, export via ifcopenshell |
| IFC ⇄ graph (NetworkX) | same class, `graph_provider="networkx"` | parse/export works (merged from branch `networkx`); **no diff/patch** |
| Diff | `graph_diff/GraphDiff.py` (neomodel); `GraphDiffBatched.py` (APOC, not wired into the CLI) | works on simple cases, see findings |
| Patch | `graph_patch/GraphPatch.py`, format in `Patch_Structure_Documentation.md` | works on simple cases, both directions; see findings |
| Version timeline | `version_timeline/VersionTimeline.py` → `timeline_data/timeline.json` | branches, commits, BFS checkout over the commit DAG |
| CLI | `conman2.py` + `command_line_interface/*` | add / commit / get / checkout / branch / log / remove / reset / nuke; fetch / pull / push are stubs |
| Tests | `tests/` (14 tests, all mocked, no DB) | 13 passed, 1 xfailed (a documented bug) |
| Sample data | `00_sampleData/IFC_stepP21/` (13 IFC series) | 7 Initial/Update pairs, an 8-version series, case studies |
| Unmerged branches | `origin/textbasedDiff` (3 commits: `ifc_decomposer.py`, per-object `.pifc` chunks for text diffs) | relevant for git integration; `batch-processing` and `networkx` are fully merged |

## Findings (verified by running against an isolated Neo4j 5 and NetworkX)

| # | Finding | Impact | Fixed on |
|---|---|---|---|
| 1 | `requirements.txt` unpinned; neomodel ≥ 6 removed `NodeSet.has()` | `commit` crashes on a fresh install | `fix/pin-neomodel` |
| 2 | Equivalence guard in `create_equivalence_relations_primary` filters on the node's own timestamp, so it is always empty | n:m equivalences; e.g. GeomRepresentation_01 ends with 39 instead of 35 nodes | `fix/diff-equivalence-guard` |
| 3 | `.env` URIs always rewritten to `bolt+ssc://…:7687` | a local instance on another port cannot be used; every CLI call goes to localhost:7687 | `fix/neo4j-local-env-uri` |
| 4 | ConnectionNodes compared all-pairs; n:m possible; `self.unique_paths` undefined; possible division by zero | O(n²) DB round trips; `AttributeError` when IoU == 1 | `fix/diff-connection-matching` |
| 5 | `apply_patch` deletes and restamps **every node in the DB** | `checkout` of one project wipes other projects in the same DB | `fix/apply-patch-scope` |
| 6 | `RelationshipTo('Node')` resolved via stack inspection; under pytest it resolves to pytest's own `Node` | every `connect()` fails in tests that touch a DB (the existing tests mock everything) | `fix/neomodel-relationship-resolution` |
| 7 | Semantic patch assumes a closed schema (keys only in updt are lost, removed keys raise `IndexError`); duplicated `elif` makes the relation→value branch unreachable | open-schema models impossible; one IFC case silently not applied | `feature/generic-diff-patch` |
| 8 | `find_node_from_unique_path` returns the **parent** when a step does not resolve | `apply_patch` may delete or modify the wrong node | `feature/generic-diff-patch` |
| 9 | `DataHandler` paths: no escaping; every digit-only value becomes `int` | ids containing `,` `=` `\|` or numeric ids break | `feature/generic-diff-patch` |
| 10 | `IfcProject` hard-coded as diff root | no other model types possible | `feature/generic-diff-patch` |
| 11 | Relations between two equivalent nodes that change are in no patch | GeomRepresentation_01 patched **wrongly** on master in both directions | `feature/patch-context-relations` |
| 12 | `nuke` crashes if `patch_data/` does not exist | – | `feature/geojson-cli` |
| 13 | 8VersionsTest: regenerated IfcColumnType GlobalId + shared IfcRepresentationMap | wrong patches from v1→v2 on, `RecursionError` at v5→v6 on master; improved on the branches, v2…v7 still open (xfail) | open |

Further observations (not changed):

- CLI commands write `timeline_data/`, `patch_data/`, and NetworkX graph files into the *current
  directory*. `Branch.py` and `Checkout.py` create a `VersionTimeline` (which writes to disk) and a
  DB connection at **import time**, so every `conman2.py` call does this.
- Cypher in `commit`/`remove` is built with f-strings (timestamp interpolated). Parameters would be
  safer.
- `add` without `-t` uses an empty timestamp for IFC.
- `IfcGraphInterface.__retrieve_from_nx` only reads the first edge between two nodes (comment in
  the code). Repeated references to the same entity in a list are lost on the NetworkX path.
- Neo4j diff/patch is bound by per-node OGM round trips (≈ 20 s diff for ≈ 1.1k nodes).
  `GraphDiffBatched` exists but is not used.
- Default credentials `neo4j/password` are hard-coded in every command.

## Where the new work is

See `docs/GeoJSON_CityGML_DiffPatch.md` (on `feature/geojson-cli`) for the GeoJSON/CityGML
integration and the branch map, and `docs/git-integration.md` (on `docs/git-integration`) for the git
integration concept.
