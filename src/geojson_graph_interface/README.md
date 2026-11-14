# GeoJsonGraphInterface: GeoJSON (CityGML-as-GeoJSON) ⇄ ConMan2 graph

`GeoJsonGraphInterface` is the GeoJSON counterpart of `IfcGraphInterface`. It writes into
**the same graph meta model** (`PrimaryNode`, `ConnectionNode`, `SecondaryNode`, `InlineNode`,
generic `rel` edges with `rel_type` + `list_index`, `timestamp` per version). As a result,
`GraphDiff`/`GraphPatch` and their NetworkX counterparts treat a GeoJSON graph like an IFC graph.

```python
from geojson_graph_interface.GeoJsonGraphInterface import GeoJsonGraphInterface

gi = GeoJsonGraphInterface(graph_provider="neo4j")      # or "networkx"
gi.geojson_2_graph("campus_v1.geojson", timestamp="ts1")  # project id = FeatureCollection "id"
gi.graph_2_geojson("out.geojson", timestamp="ts1")
```

## Design principle

In IFC, *identity* decides the node class: entities with a `GlobalId` are Primary/Connection nodes
and are matched across versions by that id. Everything else is reached from them and identified by
its **unique path** of `(rel_type, list_index, EntityType)` steps. The GeoJSON mapping applies the
same rule:

| GeoJSON element | Node class | `EntityType` | identity | IFC analogue |
|---|---|---|---|---|
| `FeatureCollection` | PrimaryNode | `FeatureCollection` | `GlobalId` = collection `"id"` (or explicit `project_id`) | `IfcProject` |
| `Feature` **with** `"id"` | PrimaryNode | `Feature` | `GlobalId` = `str(id)` | `IfcProduct` / `IfcObjectDefinition` |
| membership collection ↔ feature | ConnectionNode | `FeatureMembership` | `GlobalId` = `<collection id>::<feature id>`, property `member_index` | `IfcRelAggregates` / `IfcRelContainedInSpatialStructure` |
| `Feature` **without** `"id"` | SecondaryNode | `Feature` | path `FeatureCollection -[features, i]->` | secondary entity |
| geometry object | SecondaryNode | `Point`, `Polygon`, … | path `Feature -[geometry,0]->` | `IfcShapeRepresentation`, `IfcPolyline` |
| ring of a Polygon | SecondaryNode | `LinearRing` | `-[coordinates, i]->` | `IfcPolyLoop` |
| line of a MultiLineString | SecondaryNode | `LineStringCoordinates` | `-[coordinates, i]->` | — |
| polygon of a MultiPolygon | SecondaryNode | `PolygonCoordinates` | `-[coordinates, i]->` | — |
| position `[x, y(, z)]` | InlineNode | `Position`, `wrappedValue` = JSON text | `-[coordinates, i]->` | inline `IfcArcIndex((1,2,3))` / `IfcCartesianPoint` |
| `properties` object | SecondaryNode | `Properties` | `Feature -[properties,0]->` | `IfcPropertySet` internals |
| nested JSON object | SecondaryNode | `JsonObject` | `-[<key>, 0]->` (or `-[<key>, i]->` inside arrays) | nested entity attribute |
| nested array inside array | SecondaryNode | `JsonArray` | `-[<key>, i]->`, elements via `items` | nested lists |
| primitive inside a structured array | InlineNode | `JsonValue` | `-[<key>, i]->` | — |

Edge `rel_type`s are the GeoJSON member names (`geometry`, `properties`, `coordinates`,
`geometries`, `features`, or a property key), just as IFC uses attribute names.

### Why a ConnectionNode for membership

A direct `FeatureCollection -[features, i]-> Feature` edge would turn the feature order into the
identity: `GraphDiff` descends from PrimaryNodes into children by `(rel_type, list_index, EntityType)`,
so inserting one feature would pair every following feature with its neighbour. Objectifying the
membership the IFC way (`IfcRelAggregates`) avoids this:

- features keep their `GlobalId` identity regardless of position,
- the `FeatureMembership` node is matched by its deterministic `GlobalId`,
- a reorder shows up as a *semantic* change of `member_index`, and an added or removed feature is a
  *topological* change of exactly one membership node.

Features without an id have no identity. They hang directly off the collection and are matched by
position, the same trade-off IFC secondary entities have.

### Primitive values

- `str`, `int`, `float`, `bool` are stored as native node properties.
- `null` and arrays of primitives are stored as JSON text. Their keys are listed in the node property
  `meta__json_keys`. This is lossless: IFC's `str(tuple)` + `ast.literal_eval` heuristic would mistake a
  string like `"(not a tuple)"` for a list.
- Keys whose child nodes form an array are listed in `meta__array_keys`.
- Non-string ids are flagged with `meta__id_type = "number"`. A collection without its own id (when
  `project_id` was passed explicitly) gets `meta__id_type = "none"`.
- Keys are escaped (prefix `esc__`, then every UTF-8 byte outside `[A-Za-z0-9]` written as `_hh`;
  reversible) when they
  - collide with node bookkeeping (`timestamp`, `EntityType`, `GlobalId`, `p21_id`, `label`, …) or with
    attributes of the neomodel classes (`id`, `save`, `nodes`, …), which `GraphPatch` writes via
    `setattr`, or
  - are not plain identifiers. neomodel writes `SET n.<key> = $<key>` unquoted, so OSM keys like
    `addr:city` raise a `CypherSyntaxError` in `apply_patch`. Example: `addr:city` → `esc__addr_3acity`.
  - start with `_`, because neomodel silently drops such attributes when `apply_patch` recreates a
    node. For the same reason the meta keys use the prefix `meta__` and not `_`.
- `p21_id` is only the file-local bulk-load key, as in IFC. It is derived from the node's structural
  position (`fc`, `f:<id>`, `m:<id>`, `f:bldg-0001/geometry/0/coordinates/1`, …) rather than a running
  counter. Unchanged nodes therefore keep their `p21_id` across versions, and inserting a feature does
  not cause `p21_id` noise in the semantic patch.

### Output canonicalisation

`graph_2_geojson` emits GeoJSON members in RFC order (`type`, `id`, `bbox`, `geometry`/`coordinates`,
`properties`) followed by foreign members, and sorts property keys alphabetically. Original key
order is not stored. The output is semantically identical to the input (all sample files
round-trip with `==` on the parsed JSON) and deterministic, which keeps text diffs clean when
the files are also tracked in git.

## Scope and limitations

- Only `FeatureCollection` documents can be versioned. A bare `Feature`/geometry has no project anchor.
- The legacy `crs` member (GeoJSON 2008) and any other foreign members are kept as plain JSON. They
  are not interpreted.
- Feature ids must be unique within a collection (the parser raises otherwise).
- Relations between city objects (e.g. `properties.parent = "bldg-0001"`) stay plain property values.
  Turning them into ConnectionNodes is a proposed extension (see
  [`docs/GeoJSON_CityGML_DiffPatch.md`](../../docs/GeoJSON_CityGML_DiffPatch.md), P5).
