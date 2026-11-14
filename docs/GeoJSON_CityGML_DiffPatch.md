# CityGML (as GeoJSON) in ConMan2: parsing, diff, patch, and proposed extensions

Status: 2026-11-14 · Branches: see [Branch map](#branch-map)

CityGML 3.0 is the target. GeoJSON (RFC 7946) is the encoding used for now: city objects are GeoJSON
`Feature`s, the CityGML class goes into `properties.featureType`, and attributes are feature
properties. This document covers how GeoJSON is mapped onto the ConMan2 graph meta model, how the
existing diff and patch apply to it, which core extensions were necessary, how everything was
verified, and what should come next.

## 1. Summary

| | |
|---|---|
| Parser | `src/geojson_graph_interface/GeoJsonGraphInterface.py`, providers `neo4j` and `networkx`. Lossless round trip for all 11 sample files on both providers. |
| Diff / patch Neo4j | Existing `GraphDiff` / `GraphPatch`, made generic (root entity type, open-schema attributes, escaped paths, context relations). |
| Diff / patch NetworkX | New `GraphDiffNx` / `GraphPatchNx`. Faithful port that writes the **same patch files**. Works for IFC too. |
| CLI | `add` / `commit` / `get` / `checkout` / `branch` accept `.geojson` / `.json`. |
| Verification | campus v1→…→v5 and real OSM 2020→2024→2026: every patch reproduces the target file exactly, forward **and** reverse, on both providers. Neo4j-created patches apply on NetworkX and vice versa. 127 tests (with Neo4j). |

## 2. Mapping onto the meta model

The full table is in [`src/geojson_graph_interface/README.md`](../src/geojson_graph_interface/README.md).
The key decisions:

1. **Identity decides the node class**, as in IFC: the `FeatureCollection` and every `Feature` with an
   `id` are **PrimaryNodes** (`GlobalId`). Everything below a feature is **SecondaryNode** / **InlineNode**
   and is identified by its unique path.
2. **Collection membership is objectified** as a **ConnectionNode** `FeatureMembership` (the IFC pattern
   of `IfcRelAggregates`). Its GlobalId is `<collection id>::<feature id>`, and the feature order is the
   attribute `member_index`. Without it, inserting one feature would pair every following feature with
   the wrong partner, because `GraphDiff` descends by `(rel_type, list_index, EntityType)`.
3. **Geometry is decomposed down to positions** (`Polygon → LinearRing → Position`), as IFC decomposes
   `IfcPolyline → IfcCartesianPoint`. A moved vertex is then one semantic change on one `Position`
   InlineNode, not a change of the whole coordinate array.
4. **Values are stored losslessly and in a neomodel-safe way.** Native primitives stay as they are;
   `null` and primitive arrays are stored as JSON text (`meta__json_keys`). Keys that are not
   identifiers or that collide with bookkeeping or neomodel attributes are reversibly escaped
   (`addr:city` → `esc__addr_3acity`). `p21_id` is derived from the structural position, so it is
   stable across versions.

## 3. Diff

`GraphDiff.run_diff(ts_init, ts_updt, root_entity_type="FeatureCollection")` (Neo4j) and
`GraphDiffNx(g_init, g_updt).run_diff(...)` (NetworkX) apply the same rules:

| Element | Matched by | Effect of a change |
|---|---|---|
| FeatureCollection | always (project anchor) | foreign members (`name`, `bbox`, …) → semantic |
| Feature with id | `GlobalId` | new id = feature added, missing id = feature removed (topological) |
| FeatureMembership | `GlobalId` (then IoU for the rest) | reorder → `member_index` (semantic) |
| Feature without id | position in `features` | moves with its index (no identity) |
| geometry, rings, positions, properties, nested objects | `(rel_type, list_index, EntityType)` below the feature | value change → semantic; type change (e.g. `Polygon` → `MultiPolygon`) or count change → topological |

Every node gets at most one equivalent (see the fixes in §5).

## 4. Patch

The patch format is unchanged: `patch_data/Patch_{Topo,Sema}_<project>_<ts_init>_<ts_updt>.json`, with
two additions described in
[`Patch_Structure_Documentation.md`](../src/graph_patch/Patch_Structure_Documentation.md). Example
`campus_v1 → campus_v2` (semantic only, generated, unedited):

```text
[primary_node=tum-campus-citygml3-demo]
     name {'v1': 'TUM campus - … (synthetic)', 'v2': 'TUM campus - … (synthetic, rev 2)'}
[primary_node=bldg-0001]|[EntityType=Properties,list_index=0,rel_type=properties]
     comment         {'v1': 'null', 'v2': None}          ← key removed (JSON null value → absent)
     energyRating    {'v1': None,   'v2': 'B'}           ← key added
     measuredHeight  {'v1': 23.5,   'v2': 24.1}
     tags            {'v1': '["campus", "teaching"]', 'v2': '["campus", "teaching", "research"]'}
     meta__json_keys {'v1': '["comment", "tags"]', 'v2': '["tags"]'}
     name            {'v1': 'Stammgelaende N1', 'v2': 'Stammgelaende N1 (renovated)'}
[primary_node=bldg-0001]|…|[EntityType=JsonObject,list_index=0,rel_type=address]
     houseNumber {'v1': '21', 'v2': '21a'}
[primary_node=bldg-0001]|…|[EntityType=JsonObject,list_index=1,rel_type=genericAttributes]
     value {'v1': 9800, 'v2': 10150}
[primary_node=road-0001]|[EntityType=Properties,…]   lanes  {'v1': 2, 'v2': 3}
[primary_node=tree-0002]|[EntityType=Properties,…]   height {'v1': 11.5, 'v2': 12.0}
```

Pushouts per step of the controlled series (`citygml_campus/CHANGELOG.json`):

| Step | init pushout | updt pushout | semantic nodes |
|---|---|---|---|
| v1→v2 semantic | – | – | 6 |
| v2→v3 geometry | courtyard ring + 5 positions | 1 appended road vertex | 2 (moved vertex, moved tree) |
| v3→v4 topology | tree-0003 (Feature, membership, Point, Position, Properties) | bldg-0003 (11 nodes) + 4th bench point | 5 (`member_index` shifts, `count`) |
| v4→v5 mixed | water-0001 `Polygon` subtree | `MultiPolygon` subtree, new part, new hole | 1 (id-less annotation text) |

### Patches work in both directions and across providers

`apply_patch` uses one patch file in either direction (`checkout` walks the timeline backwards as
well). The NetworkX port writes semantic patches that are **byte-identical** to the Neo4j ones and
topological patches that are equivalent. Only the internal node keys differ. In all four cases
(NX→NX, Neo→Neo, Neo-patch on NX, NX-patch on Neo4j) the result equals the target file.

## 5. Changes to the existing core (all backward compatible for IFC)

Each change is on its own branch with a regression test:

| Branch | Problem found | Effect on IFC |
|---|---|---|
| `fix/pin-neomodel` | `requirements.txt` unpinned; neomodel ≥ 6 removed `NodeSet.has()` → `commit` crashes on a fresh install | install works again |
| `fix/diff-equivalence-guard` | guard `equivalent_to.filter(timestamp=<own ts>)` always empty → n:m equivalences for shared sub-structures | GeomRepresentation_01: 39 → 35 nodes after patch (correct) |
| `fix/neo4j-local-env-uri` | every `.env` URI was rewritten to `bolt+ssc://…:7687`; a local DB on another port was unreachable | `.env` can point to any local instance |
| `fix/diff-connection-matching` | ConnectionNodes compared all-pairs (O(n²) DB round trips), n:m possible, `self.unique_paths` undefined (`AttributeError` = the old xfail test), division by zero | GlobalId lookup first, IoU for the rest, 1:1 |
| `fix/apply-patch-scope` | `apply_patch` deleted and restamped **all nodes in the DB** → a second project in the same DB was wiped on `checkout` | only the init version is touched |
| `fix/neomodel-relationship-resolution` | `RelationshipTo('Node')` was resolved in the first stack frame containing a `Node` → under pytest that was pytest's own `Node` class, so every `connect()` failed | relationships target the model class |
| `feature/generic-diff-patch` | `IfcProject` hard-coded as root; semantic patch assumed a closed schema (keys added in updt were lost; removed keys raised `IndexError`); the relation→value branch of `apply_patch` was unreachable (duplicated `elif`); `find_node_from_unique_path` silently returned the **parent** on a failed step; path strings broke on `,` `=` `|` in ids, and numeric ids became `int` | `root_entity_type` parameter; union of keys with `null` = absent; strict path resolution; escaped paths. Existing IFC paths unchanged. |
| `feature/patch-context-relations` | relations between two *equivalent* nodes that exist in only one version were in neither patch. GeomRepresentation_01 was patched **wrongly on master** (Cuboid2's re-targeted `Representation`) | new `context_relations` section; all Initial/Update IFC fixtures are now structurally exact in both directions on both providers |
| `feature/geojson-cli` (commit) | `nuke` crashed without `patch_data/` | – |

## 6. Verification

| Data | Neo4j (diff / create / apply) | NetworkX (diff / create) | Result |
|---|---|---|---|
| campus v1…v5 (≈130–160 nodes) | 1.3–1.7 s / 1.6 s / 0.3–0.8 s | < 0.01 s / 0.01 s | exact, fwd + rev, cross-provider |
| OSM 2020→2024 (1009→1155 nodes) | 19.9 s / 11.8 s / 9 s | 0.02 s / 0.10 s | exact, fwd + rev, cross-provider |
| OSM 2024→2026 (1155→1321 nodes) | 23.6 s / 13.1 s / 11–13 s | 0.03 s / 0.12 s | exact, fwd + rev, cross-provider |
| IFC Initial/Update fixtures (7) | – | – | structurally exact, fwd + rev, both providers |
| CLI session (`conman2.py`) | commits v1…v5, branch `alt`, commit on a patched DB state, checkouts ts5→ts2→ts3(alt)→ts6→ts5→ts1, plus an IFC project in the same DB | | exact `.geojson` output every time |

Run the tests:

```bash
pip install -r src/requirements.txt -r tests/requirements_dev.txt
pytest tests                       # no database needed (Neo4j tests are skipped)
# Neo4j tests: they WIPE the database given here - use a throwaway instance, e.g.
docker run -d --name conman2-neo4j-test -p 127.0.0.1:7688:7687 -e NEO4J_AUTH=neo4j/password neo4j:5
CONMAN2_TEST_NEO4J_URI=bolt://neo4j:password@localhost:7688 pytest tests
```

CLI against a non-default instance: put `NEO4J_URI=bolt://localhost:7688`, `NEO4J_USERNAME`, and
`NEO4J_PASSWORD` into a `.env` in your working directory, then:

```bash
python src/conman2.py add -p src/00_sampleData/GeoJSON/citygml_campus/campus_v1.geojson -t ts1
python src/conman2.py commit -p tum-campus-citygml3-demo -b main -m "initial"
python src/conman2.py add -p src/00_sampleData/GeoJSON/citygml_campus/campus_v2.geojson -t ts2
python src/conman2.py commit -p tum-campus-citygml3-demo -b main -m "semantic changes"
python src/conman2.py checkout -p tum-campus-citygml3-demo -b main -t ts1
python src/conman2.py get -p out.geojson -t ts1
```

## 7. Known limitations and open issues

- **Positional matching inside lists.** Positions, rings, and array elements are matched by
  `list_index`. Inserting a vertex shifts every following position. On the OSM data **78 % of all
  semantic entries** (295/377 and 444/559) are `Position.wrappedValue` changes, many of them cascades
  after a single insertion. The results are correct, but the patches are larger and harder to read
  than needed. This is the same behaviour as for IFC lists. See proposal P1.
- **Feature order.** A feature insertion shifts `member_index` of all following memberships (8–12 % of
  the OSM semantic entries). RFC 7946 gives feature order no meaning. See P2.
- **Exact coordinate comparison.** `11.5680000` vs `11.5680001` is a change. See P3.
- **Features without id** have no identity and move with their index. See P4.
- **Escaped key names** appear in patches (`esc__addr_3acity`). This is reversible, but less readable.
- **Property key order** of the input is not stored; output is canonical (sorted keys).
- **Neo4j performance** is bound by per-node OGM round trips (≈ 20 s diff for ≈ 1.1k nodes; NetworkX
  is roughly 1000× faster on the same algorithm). See P6.
- **IFC open issue (pre-existing):** `8VersionsTest` v2…v7. The authoring tool regenerates the
  `IfcColumnType` GlobalId in every version, and its `IfcRepresentationMap` is shared with the
  column's `IfcMappedItem`. The re-created type ends up with two `RepresentationMaps`. Marked `xfail`
  in `tests/test_ifc_diff_patch.py`. master is wrong from v1→v2 on and crashes with a
  `RecursionError` at v5→v6.

## 8. Proposed extensions (prioritised)

**P1 – Sequence alignment for ordered lists (highest value).** Before positional matching, align the
ordered children of a node (positions of a ring, array elements) with an LCS/Myers diff on
`(EntityType, wrappedValue)`. Matched pairs become equivalences, and unmatched elements become
pushouts. The patch then needs a way to *re-index* context relations (`list_index` changes on edges
between equivalent nodes). The new `context_relations` section already provides this: a re-indexed
edge appears as a removal plus an addition. Expected effect on OSM: hundreds of `wrappedValue`
entries collapse to a few inserted or removed vertices. Generic, so it also benefits IFC
(`IfcPolyLoop`, `IfcIndexedPolyCurve`).

**P2 – Order as an option.** `GeoJsonGraphInterface(feature_order="ignore")` would store no
`member_index` and write features sorted by id. Use it when order carries no meaning, which is the
case for most city models.

**P3 – Tolerance-aware geometry comparison.** Compare `Position` values with a metric tolerance
(e.g. 1 mm after projecting to a local CRS). Classify geometry changes as *moved*, *reshaped*, or
*retyped* on the geometry node, as a summary for users.

**P4 – Content-based matching for id-less features.** Analogous to the IoU rule for ConnectionNodes:
match the remaining id-less features by a fingerprint (geometry centroid / hash plus `featureType`).
An alternative is a GeoJSON pre-processor that assigns stable ids (UUIDv5 over the content) on first
commit.

**P5 – Real CityGML 3.0 semantics.**
- *CityObjectRelations as ConnectionNodes.* Turn id references such as `BuildingPart.parent` or CityGML
  3.0 `relatedTo` into ConnectionNodes (`CityObjectRelation` with `relationType`, matched by the IoU
  of their ends). A re-parented building part then becomes a real topological change instead of a
  string edit.
- *`featureType` as EntityType* (option). A class change `Building` → `BuildingPart` then becomes a
  topological change, as an IFC class change is.
- *LoD-specific geometries* (lod0…lod3 per city object, as in CityJSON) as separate geometry relations
  `geometry_lod2` etc.
- *CityJSON 2.0 as the next encoding.* Its shared `vertices` array maps naturally onto shared
  `Position` nodes (several rings referencing one vertex). That multi-parent structure is exactly what
  the new context relations and the equivalence guard make safe.
- *Export patches as CityGML 3.0 Versioning* (`Version` / `VersionTransition` with `Transaction`
  insert / delete / replace). The ConMan2 topological and semantic patch has the same structure: a
  pushout on the init side is a delete, a pushout on the updt side is an insert, an equivalent node
  with attribute changes is a replace. This is a direct link to the standard for the dissertation.

**P6 – Neo4j performance.** Switch `commit` to `GraphDiffBatched` (APOC, already in the repo) and
write a batched Cypher `apply_patch`. Alternatively run the diff on NetworkX and only persist into
Neo4j: the patch files are provider-independent, so any provider can apply them.

**P7 – Spatial querying.** Additionally store a Neo4j `point` (and a feature `bbox`) so that
version-aware spatial queries ("which buildings changed inside this polygon between ts2 and ts5")
become possible.

**P8 – Patch readability.** Unescape keys and render a human-readable change summary per feature
(`bldg-0001: measuredHeight 23.5 → 24.1, +energyRating, −comment, geometry: 1 vertex moved`). This is
useful for commit messages and for the git integration (see `docs/git-integration.md` on
`docs/git-integration`).

## Branch map

```
master
 ├─ fix/pin-neomodel ───────────────────┐
 ├─ fix/diff-equivalence-guard ─────────┤
 ├─ fix/neo4j-local-env-uri ────────────┤
 ├─ feature/geojson-sample-data ── feature/geojson-graph-interface (merges the 3 fixes)
 │                                              │
 ├─ fix/diff-connection-matching ───────┐       │
 ├─ fix/apply-patch-scope ──────────────┤       │
 ├─ feature/generic-diff-patch ─────────┤       │
 ├─ fix/neomodel-relationship-resolution┤       │
 │                                      └── feature/geojson-diff-patch (+ GraphDiffNx/GraphPatchNx)
 │                                                 ├─ feature/patch-context-relations
 │                                                 └─ feature/geojson-cli (merges context-relations) ← tip
 ├─ docs/git-integration
 └─ docs/state-of-repository
```
