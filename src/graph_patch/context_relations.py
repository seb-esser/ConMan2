"""
Context relation delta: relations whose source and target are both *equivalent* (context) nodes but
that exist in only one of the two versions.

The topological patch only covers relations that touch pushout nodes, and the semantic patch only
covers attribute values. A relation that is re-targeted between existing nodes - e.g. an IFC element
whose Representation switches to an IfcProductDefinitionShape that is shared with another element
(GeomRepresentation_01) - was therefore lost: the forward patch left the attribute unset, the reverse
patch kept both relations.

The delta is stored in the topological patch file under the key "context_relations":

    "context_relations": {
        "<ts_init>": [ {"source": {"<ts_init>": path, "<ts_updt>": path},
                        "target": {"<ts_init>": path, "<ts_updt>": path},
                        "rel_type": ..., "list_index": ...}, ... ],   # relations only in ts_init
        "<ts_updt>": [ ... ]                                           # relations only in ts_updt
    }

Both endpoint paths are stored, so the delta can be applied in either direction: relations listed
under the source version of apply_patch are removed, those listed under the target version are added;
endpoints are always resolved with the path of the source version.
"""
import json

KEY = "context_relations"


def context_relation_delta(edges: dict, partner: dict, paths: dict, timestamp_init: str, timestamp_updt: str) -> dict:
    """
    @param edges:   {ts: [(source_id, target_id, rel_type, list_index)]} relations between equivalent nodes
    @param partner: {ts: {node_id: equivalent node id in the other version}}
    @param paths:   {ts: {node_id: unique path string}} (node_ids_to_unique_paths_mapping)
    """
    other = {timestamp_init: timestamp_updt, timestamp_updt: timestamp_init}
    existing = {ts: {(a, rt, li, b) for a, b, rt, li in edges[ts]} for ts in (timestamp_init, timestamp_updt)}
    delta = {timestamp_init: [], timestamp_updt: []}
    for ts in (timestamp_init, timestamp_updt):
        o = other[ts]
        for a, b, rel_type, list_index in edges[ts]:
            if (partner[ts][a], rel_type, list_index, partner[ts][b]) in existing[o]:
                continue
            try:
                entry = {
                    "source": {ts: paths[ts][a], o: paths[o][partner[ts][a]]},
                    "target": {ts: paths[ts][b], o: paths[o][partner[ts][b]]},
                    "rel_type": rel_type,
                    "list_index": list_index,
                }
            except KeyError:
                print(f"Warning: no unique path for context relation {rel_type}[{list_index}] in {ts}; skipped.")
                continue
            delta[ts].append(entry)
        delta[ts].sort(key=lambda e: json.dumps(e, sort_keys=True))
    return delta
