"""
Convert an Overpass API JSON response (queried with ``out geom``) into an
RFC 7946 GeoJSON FeatureCollection.

Only what is needed for the ConMan2 sample data is supported:
  * closed ways            -> Feature with Polygon geometry
  * open ways              -> Feature with LineString geometry
  * multipolygon relations -> Feature with MultiPolygon geometry (outer/inner
                              member ways are stitched into closed rings)

The OSM element identity ("way/<id>", "relation/<id>") is kept as the
Feature ``id``. This is the persistent identifier ConMan2 uses to match
features across versions (analogous to the IFC GlobalId).

Usage:
    python osm_overpass_to_geojson.py <overpass.json> <out.geojson> [--id ID] [--name NAME] [--snapshot DATE]

Reproducing the sample snapshots (TUM main campus, Munich):
    [out:json][timeout:60][date:"<DATE>T00:00:00Z"];
    (way["building"](48.1478,11.5655,48.1508,11.5705);
     relation["building"](48.1478,11.5655,48.1508,11.5705););
    out geom;
"""
import argparse
import json


def _pos(pt):
    # GeoJSON uses [lon, lat]; round to 7 decimals (OSM precision).
    return [round(pt["lon"], 7), round(pt["lat"], 7)]


def _ring_area2(ring):
    """Twice the signed area (shoelace). > 0 means counter-clockwise."""
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1))


def _orient(ring, ccw):
    """RFC 7946 right-hand rule: exterior rings CCW, interior rings CW."""
    if (_ring_area2(ring) > 0) != ccw:
        ring = list(reversed(ring))
    return ring


def _stitch(segments):
    """Greedily join way segments that share end points into closed rings."""
    segments = [list(s) for s in segments if s]
    rings = []
    while segments:
        ring = segments.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, seg in enumerate(segments):
                if seg[0] == ring[-1]:
                    ring += seg[1:]
                elif seg[-1] == ring[-1]:
                    ring += list(reversed(seg))[1:]
                elif seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                elif seg[0] == ring[0]:
                    ring = list(reversed(seg))[:-1] + ring
                else:
                    continue
                segments.pop(i)
                changed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _point_in_ring(pt, ring):
    x, y = pt
    inside = False
    for i in range(len(ring) - 1):
        (x1, y1), (x2, y2) = ring[i], ring[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def convert_element(el):
    tags = dict(el.get("tags", {}))
    fid = f"{el['type']}/{el['id']}"
    if el["type"] == "way":
        coords = [_pos(p) for p in el.get("geometry", [])]
        if len(coords) >= 4 and coords[0] == coords[-1]:
            geometry = {"type": "Polygon", "coordinates": [_orient(coords, ccw=True)]}
        else:
            geometry = {"type": "LineString", "coordinates": coords}
    elif el["type"] == "relation":
        outer = [[_pos(p) for p in m.get("geometry", [])] for m in el.get("members", []) if m.get("role") == "outer"]
        inner = [[_pos(p) for p in m.get("geometry", [])] for m in el.get("members", []) if m.get("role") == "inner"]
        outer_rings = [_orient(r, ccw=True) for r in _stitch(outer)]
        inner_rings = [_orient(r, ccw=False) for r in _stitch(inner)]
        polygons = [[r] for r in outer_rings]
        for hole in inner_rings:
            for poly in polygons:
                if _point_in_ring(hole[0], poly[0]):
                    poly.append(hole)
                    break
        geometry = {"type": "MultiPolygon", "coordinates": polygons}
        tags.pop("type", None)
    else:
        return None
    return {"type": "Feature", "id": fid, "geometry": geometry, "properties": tags}


def convert(overpass, name=None, snapshot=None, fc_id=None):
    features = [f for f in (convert_element(e) for e in overpass["elements"]) if f]
    features.sort(key=lambda f: f["id"])
    fc = {"type": "FeatureCollection"}
    # Foreign members (RFC 7946 section 6.1) carrying collection-level metadata.
    # "id" is the persistent collection identity ConMan2 uses as project id.
    if fc_id:
        fc["id"] = fc_id
    if name:
        fc["name"] = name
    if snapshot:
        fc["snapshot"] = snapshot
    fc["attribution"] = "© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)"
    fc["features"] = features
    return fc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--name", default=None)
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--id", default=None, help="Persistent collection id (ConMan2 project id).")
    a = ap.parse_args()
    with open(a.src, encoding="utf-8") as f:
        data = json.load(f)
    with open(a.dst, "w", encoding="utf-8") as f:
        json.dump(convert(data, a.name, a.snapshot, a.id), f, indent=2, ensure_ascii=False)
