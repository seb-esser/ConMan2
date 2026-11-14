"""
Generate the synthetic, CityGML-3.0-inspired GeoJSON version series in
``../citygml_campus/`` (v1 ... v5).

Every version differs from its predecessor by a documented, controlled set of
changes so that the diff/patch behaviour of ConMan2 can be checked precisely
(analogous to the ``GeomRepresentation_0*`` IFC regression fixtures).

CityGML 3.0 semantics are carried in the Feature ``properties`` (``featureType``
holds the CityGML class name, e.g. ``Building``, ``BuildingPart``, ``Road``).
Coordinates are WGS84 lon/lat (+ ellipsoidal height) as required by RFC 7946.

Run from anywhere:
    python make_citygml_campus_series.py
"""
import copy
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "citygml_campus")


def ring(*pts):
    pts = [list(p) for p in pts]
    return pts + [list(pts[0])]


def v1():
    return {
        "type": "FeatureCollection",
        # Foreign members (RFC 7946 §6.1). "id" is used by ConMan2 as project id.
        "id": "tum-campus-citygml3-demo",
        "name": "TUM campus - CityGML 3.0 inspired demo (synthetic)",
        "lod": 1,
        "bbox": [11.5660, 48.1480, 11.5700, 48.1500],
        "features": [
            {
                "type": "Feature",
                "id": "bldg-0001",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring([11.5670, 48.1485, 519.0], [11.5680, 48.1485, 519.0],
                                         [11.5680, 48.1490, 519.0], [11.5670, 48.1490, 519.0])],
                },
                "properties": {
                    "featureType": "Building",
                    "name": "Stammgelaende N1",
                    "function": "university",
                    "roofType": "flat",
                    "measuredHeight": 23.5,
                    "storeysAboveGround": 5,
                    "yearOfConstruction": 1965,
                    "isListedMonument": False,
                    "address": {"street": "Arcisstrasse", "houseNumber": "21",
                                "postalCode": "80333", "city": "Muenchen"},
                    "genericAttributes": [
                        {"name": "owner", "value": "Freistaat Bayern"},
                        {"name": "grossFloorArea", "value": 9800, "uom": "m2"},
                    ],
                    "tags": ["campus", "teaching"],
                    "comment": None,
                },
            },
            {
                "type": "Feature",
                "id": "bldg-0001-part-01",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [ring([11.5672, 48.1486, 542.5], [11.5676, 48.1486, 542.5],
                              [11.5676, 48.1488, 542.5], [11.5672, 48.1488, 542.5])],
                        [ring([11.5677, 48.1486, 542.5], [11.5679, 48.1486, 542.5],
                              [11.5679, 48.1488, 542.5], [11.5677, 48.1488, 542.5])],
                    ],
                },
                "properties": {"featureType": "BuildingPart", "parent": "bldg-0001",
                               "function": "lecture hall", "measuredHeight": 4.0},
            },
            {
                "type": "Feature",
                "id": "bldg-0002",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        ring([11.5684, 48.1484, 519.0], [11.5694, 48.1484, 519.0],
                             [11.5694, 48.1492, 519.0], [11.5684, 48.1492, 519.0]),
                        # courtyard (interior ring, clockwise)
                        ring([11.5687, 48.1487, 519.0], [11.5687, 48.1489, 519.0],
                             [11.5691, 48.1489, 519.0], [11.5691, 48.1487, 519.0]),
                    ],
                },
                "properties": {"featureType": "Building", "name": "Courtyard building",
                               "function": "office", "roofType": "gabled",
                               "measuredHeight": 17.2, "storeysAboveGround": 4},
            },
            {
                "type": "Feature",
                "id": "road-0001",
                "geometry": {"type": "LineString",
                             "coordinates": [[11.5662, 48.1482], [11.5675, 48.1482], [11.5698, 48.1482]]},
                "properties": {"featureType": "Road", "name": "Arcisstrasse", "class": "secondary",
                               "lanes": 2, "surfaceMaterial": "asphalt"},
            },
            {
                "type": "Feature",
                "id": "road-0002",
                "geometry": {"type": "MultiLineString",
                             "coordinates": [[[11.5682, 48.1482], [11.5682, 48.1498]],
                                             [[11.5662, 48.1496], [11.5698, 48.1496]]]},
                "properties": {"featureType": "Road", "class": "footway"},
            },
            {
                "type": "Feature",
                "id": "tree-0001",
                "geometry": {"type": "Point", "coordinates": [11.5665, 48.1488, 519.0]},
                "properties": {"featureType": "SolitaryVegetationObject", "species": "Tilia cordata",
                               "height": 14.0, "trunkDiameter": 0.45},
            },
            {
                "type": "Feature",
                "id": "tree-0002",
                "geometry": {"type": "Point", "coordinates": [11.5666, 48.1491, 519.0]},
                "properties": {"featureType": "SolitaryVegetationObject", "species": "Acer platanoides",
                               "height": 11.5, "trunkDiameter": 0.30},
            },
            {
                "type": "Feature",
                "id": "tree-0003",
                "geometry": {"type": "Point", "coordinates": [11.5667, 48.1494, 519.0]},
                "properties": {"featureType": "SolitaryVegetationObject", "species": "Quercus robur",
                               "height": 19.0, "trunkDiameter": 0.70},
            },
            {
                "type": "Feature",
                "id": "furn-0001",
                "geometry": {"type": "MultiPoint",
                             "coordinates": [[11.5671, 48.1493], [11.5673, 48.1493], [11.5675, 48.1493]]},
                "properties": {"featureType": "CityFurniture", "function": "bench", "count": 3},
            },
            {
                "type": "Feature",
                "id": 1001,  # numeric id (allowed by RFC 7946 §3.2)
                "geometry": {"type": "Point", "coordinates": [11.5678, 48.1483]},
                "properties": {"featureType": "CityFurniture", "function": "street lamp"},
            },
            {
                "type": "Feature",
                "id": "water-0001",
                "geometry": {"type": "Polygon",
                             "coordinates": [ring([11.5662, 48.1497], [11.5668, 48.1497],
                                                  [11.5668, 48.1499], [11.5662, 48.1499])]},
                "properties": {"featureType": "WaterBody", "class": "fountain"},
            },
            {
                "type": "Feature",
                "id": "landuse-0001",
                "geometry": {"type": "MultiPolygon",
                             "coordinates": [[ring([11.5660, 48.1480], [11.5700, 48.1480],
                                                   [11.5700, 48.1481], [11.5660, 48.1481])],
                                             [[[11.5660, 48.1499], [11.5700, 48.1499],
                                               [11.5700, 48.1500], [11.5660, 48.1500], [11.5660, 48.1499]]]]},
                "properties": {"featureType": "LandUse", "class": "green strip"},
            },
            {
                "type": "Feature",
                "id": "gen-0001",
                "geometry": {"type": "GeometryCollection",
                             "geometries": [
                                 {"type": "Point", "coordinates": [11.5696, 48.1494, 519.0]},
                                 {"type": "LineString",
                                  "coordinates": [[11.5695, 48.1493, 519.0], [11.5697, 48.1495, 521.0]]},
                             ]},
                "properties": {"featureType": "GenericOccupiedSpace", "name": "Sculpture"},
            },
            {
                # Feature without id: no persistent identity -> SecondaryNode in ConMan2.
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [11.5690, 48.1497]},
                "properties": {"featureType": "Annotation", "text": "Main entrance"},
            },
            {
                # Feature with null geometry and empty properties (both allowed by RFC 7946).
                "type": "Feature",
                "id": "meta-0001",
                "geometry": None,
                "properties": {},
            },
        ],
    }


def find(fc, fid):
    return next(f for f in fc["features"] if f.get("id") == fid)


def v2(prev):
    """Semantic changes only (attribute values, added/removed keys)."""
    fc = copy.deepcopy(prev)
    b1 = find(fc, "bldg-0001")["properties"]
    b1["measuredHeight"] = 24.1                       # value change (float)
    b1["name"] = "Stammgelaende N1 (renovated)"       # value change (string)
    b1["address"]["houseNumber"] = "21a"              # nested object change
    b1["genericAttributes"][1]["value"] = 10150       # change inside array of objects
    b1["energyRating"] = "B"                          # key added
    del b1["comment"]                                 # key removed
    b1["tags"] = ["campus", "teaching", "research"]   # primitive array change
    find(fc, "tree-0002")["properties"]["height"] = 12.0
    find(fc, "road-0001")["properties"]["lanes"] = 3
    fc["name"] = "TUM campus - CityGML 3.0 inspired demo (synthetic, rev 2)"  # collection foreign member
    return fc


def v3(prev):
    """Geometry changes (vertex moves, vertex append, hole removal)."""
    fc = copy.deepcopy(prev)
    g = find(fc, "bldg-0002")["geometry"]
    g["coordinates"][0][1] = [11.5695, 48.1484, 519.0]  # move one vertex of the exterior ring
    g["coordinates"] = g["coordinates"][:1]              # courtyard filled in -> hole removed
    find(fc, "road-0001")["geometry"]["coordinates"].append([11.5700, 48.1483])  # road extended
    find(fc, "tree-0002")["geometry"]["coordinates"] = [11.5666, 48.1492, 519.0]  # tree moved
    return fc


def v4(prev):
    """Topological changes on feature level (add, remove, reorder)."""
    fc = copy.deepcopy(prev)
    fc["features"] = [f for f in fc["features"] if f.get("id") != "tree-0003"]  # tree cut down
    new_building = {
        "type": "Feature",
        "id": "bldg-0003",
        "geometry": {"type": "Polygon",
                     "coordinates": [ring([11.5664, 48.1484, 519.0], [11.5668, 48.1484, 519.0],
                                          [11.5668, 48.1487, 519.0], [11.5664, 48.1487, 519.0])]},
        "properties": {"featureType": "Building", "name": "Pavilion", "function": "cafe",
                       "roofType": "flat", "measuredHeight": 4.5, "storeysAboveGround": 1},
    }
    idx = next(i for i, f in enumerate(fc["features"]) if f.get("id") == "bldg-0002") + 1
    fc["features"].insert(idx, new_building)
    furn = find(fc, "furn-0001")
    furn["geometry"]["coordinates"].append([11.5677, 48.1493])  # fourth bench
    furn["properties"]["count"] = 4
    return fc


def v5(prev):
    """Mixed changes: new part, new hole, geometry type change, anonymous feature edit."""
    fc = copy.deepcopy(prev)
    fc["features"].append({
        "type": "Feature",
        "id": "bldg-0001-part-02",
        "geometry": {"type": "Polygon",
                     "coordinates": [ring([11.5671, 48.1489, 542.5], [11.5674, 48.1489, 542.5],
                                          [11.5674, 48.1490, 542.5], [11.5671, 48.1490, 542.5])]},
        "properties": {"featureType": "BuildingPart", "parent": "bldg-0001",
                       "function": "roof terrace", "measuredHeight": 3.0},
    })
    find(fc, "bldg-0001")["geometry"]["coordinates"].append(
        ring([11.5674, 48.1487, 519.0], [11.5674, 48.1488, 519.0],
             [11.5676, 48.1488, 519.0], [11.5676, 48.1487, 519.0]))  # light well = new hole
    w = find(fc, "water-0001")
    w["geometry"] = {"type": "MultiPolygon",
                     "coordinates": [w["geometry"]["coordinates"],
                                     [ring([11.5669, 48.1497], [11.5670, 48.1497],
                                           [11.5670, 48.1498], [11.5669, 48.1498])]]}  # Polygon -> MultiPolygon
    anon = next(f for f in fc["features"] if "id" not in f)
    anon["properties"]["text"] = "Main entrance (barrier-free)"
    return fc


CHANGELOG = {
    "v1": "Initial state: 15 features covering all 7 RFC 7946 geometry types, a Polygon with hole, "
          "3D and 2D positions, nested objects, arrays of objects, primitive arrays, null values, "
          "a numeric id, a feature without id, and a feature with null geometry.",
    "v2": "Semantic only: bldg-0001 measuredHeight/name/address.houseNumber/genericAttributes[1].value/tags "
          "changed, key energyRating added, key comment removed; tree-0002 height; road-0001 lanes; "
          "collection name.",
    "v3": "Geometry: bldg-0002 exterior vertex 1 moved and courtyard hole removed; road-0001 extended by one "
          "vertex; tree-0002 moved.",
    "v4": "Feature topology: tree-0003 removed; bldg-0003 inserted after bldg-0002 (shifts the order of "
          "all following features); furn-0001 gets a fourth point and count=4.",
    "v5": "Mixed: bldg-0001-part-02 appended; bldg-0001 gets a hole; water-0001 changes Polygon -> "
          "MultiPolygon; text of the id-less annotation feature changed.",
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    versions = {}
    versions["v1"] = v1()
    versions["v2"] = v2(versions["v1"])
    versions["v3"] = v3(versions["v2"])
    versions["v4"] = v4(versions["v3"])
    versions["v5"] = v5(versions["v4"])
    for name, fc in versions.items():
        with open(os.path.join(OUT, f"campus_{name}.geojson"), "w", encoding="utf-8") as f:
            json.dump(fc, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT, "CHANGELOG.json"), "w", encoding="utf-8") as f:
        json.dump(CHANGELOG, f, indent=2)
    print("written to", os.path.abspath(OUT))
