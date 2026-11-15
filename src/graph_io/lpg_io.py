"""
Provider-independent I/O of the ConMan2 labeled property graph meta model, shared by the
GeoJSON and RDF interfaces (and usable by further format adapters):

  * Decomposition: collects nodes, edges and inline patterns in the same shape IfcGraphInterface builds,
  * send_to_neo4j / send_to_nx: bulk-write a decomposition (same Cypher / NetworkX layout as IFC),
  * retrieve_from_neo4j / retrieve_from_nx: read one version as
        nodes = {node_id: {"kind": <PrimaryNode|ConnectionNode|SecondaryNode|InlineNode>, "props": {...}}}
        edges = [(source_id, target_id, rel_type, list_index)]
"""
from neomodel import db

from networkX_core.networkx_connection import networkxConnection
from ifc_graph_interface.neo4j_helper import Neo4J_Helper


class Decomposition:
    """Collects nodes, edges and inline patterns in the same shape as IfcGraphInterface does."""

    def __init__(self, timestamp: str):
        self.timestamp = timestamp
        self.primary_nodes = []
        self.connection_nodes = []
        self.secondary_nodes = []
        self.relationships = []
        self.inline_patterns = []

    def node(self, kind: str, entity_type: str, key: str, global_id: str = None) -> dict:
        # "p21_id" is only the file-local bulk-load key (as in IFC). It is derived from the node's
        # structural position (e.g. "f:bldg-0001/geometry/0/coordinates/1") instead of a running
        # counter, so unchanged nodes keep it across versions and it creates no semantic-patch noise.
        props = {"EntityType": entity_type, "p21_id": key, "timestamp": self.timestamp}
        if global_id is not None:
            props["GlobalId"] = global_id
        {"PrimaryNode": self.primary_nodes,
         "ConnectionNode": self.connection_nodes,
         "SecondaryNode": self.secondary_nodes}[kind].append(props)
        return props

    @staticmethod
    def child_key(parent: dict, rel_type: str, list_index: int) -> str:
        return f"{parent['p21_id']}/{rel_type}/{list_index}"

    def rel(self, source: dict, target: dict, rel_type: str, list_index: int = 0):
        self.relationships.append({"source_p21_id": source["p21_id"], "target_p21_id": target["p21_id"],
                                   "timestamp": self.timestamp, "rel_type": rel_type, "list_index": list_index})

    def inline(self, source: dict, rel_type: str, list_index: int, entity_type: str, wrapped_value: str):
        self.inline_patterns.append({
            "props": {"EntityType": entity_type, "wrappedValue": wrapped_value, "timestamp": self.timestamp},
            "relation": {"rel_type": rel_type, "list_index": list_index, "source_p21_id": source["p21_id"]},
        })


def send_to_neo4j(d: Decomposition, batch_size: int = 20000):
    neo4j_helper = Neo4J_Helper()
    # Same bulk queries as IfcGraphInterface.__send_to_neo4j (primitive attributes are already part
    # of the node maps, therefore no separate attribute update pass is needed).
    for label, rows in (("PrimaryNode", d.primary_nodes), ("ConnectionNode", d.connection_nodes),
                        ("SecondaryNode", d.secondary_nodes)):
        print(f"Creating {len(rows)} {label}s.")
        neo4j_helper.bulk_cypher_query(f"""
        UNWIND $batch AS props
        CREATE (n:{label}:GenericNode:Node)
        SET n = props
        """, rows, batch_size)

    print(f"Creating {len(d.relationships)} relationships.")
    neo4j_helper.bulk_cypher_query("""
    UNWIND $batch AS r
    MATCH (a:GenericNode {p21_id: r.source_p21_id, timestamp: r.timestamp})
    MATCH (b:GenericNode {p21_id: r.target_p21_id, timestamp: r.timestamp})
    CREATE (a)-[:rel {rel_type: r.rel_type, list_index: r.list_index}]->(b)
    """, d.relationships, batch_size)

    print(f"Creating {len(d.inline_patterns)} InlineNode patterns.")
    neo4j_helper.bulk_cypher_query("""
    UNWIND $batch AS r
    MATCH (a:GenericNode {p21_id: r.relation.source_p21_id, timestamp: r.props.timestamp})
    CREATE (b:InlineNode:Node)
    SET b = r.props
    CREATE (a)-[:rel {rel_type: r.relation.rel_type, list_index: r.relation.list_index}]->(b)
    """, d.inline_patterns, batch_size)

    db.cypher_query("CREATE INDEX generic_p21_ts IF NOT EXISTS FOR (n:GenericNode) ON (n.p21_id, n.timestamp)")
    db.cypher_query("CREATE INDEX generic_ts IF NOT EXISTS FOR (n:GenericNode) ON (n.timestamp)")
    db.cypher_query("CALL db.awaitIndexes()")

def send_to_nx(d: Decomposition, graph_file: str):
    nx_interface = networkxConnection()
    # Same layout as IfcGraphInterface.__send_to_nx: node key = p21_id, "label" = node class.
    for label, rows in (("PrimaryNode", d.primary_nodes), ("ConnectionNode", d.connection_nodes),
                        ("SecondaryNode", d.secondary_nodes)):
        print(f"Creating {len(rows)} {label}s.")
        nx_interface.graph.add_nodes_from(
            (n["p21_id"], {**{k: v for k, v in n.items() if k != "p21_id"}, "label": label}) for n in rows)

    print(f"Adding {len(d.relationships)} relationships to networkx graph.")
    for r in d.relationships:
        nx_interface.graph.add_edge(r["source_p21_id"], r["target_p21_id"],
                                    rel_type=r["rel_type"], list_index=r["list_index"])

    print(f"Creating {len(d.inline_patterns)} inline attribute nodes.")
    for pat in d.inline_patterns:
        props, rel = pat["props"], pat["relation"]
        inline_id = f"{rel['source_p21_id']}_inline_{rel['rel_type']}_{rel['list_index']}"
        nx_interface.graph.add_node(inline_id, **props, p21_id=inline_id, label="InlineNode")
        nx_interface.graph.add_edge(rel["source_p21_id"], inline_id, rel_type=rel["rel_type"],
                                    list_index=rel["list_index"], timestamp=props["timestamp"])
    nx_interface.save_graph(graph_file)

def retrieve_from_neo4j(timestamp: str):
    rows, _ = db.cypher_query(
        "MATCH (n:Node {timestamp: $ts}) RETURN elementId(n), labels(n), properties(n)", {"ts": timestamp})
    nodes = {}
    for nid, labels, props in rows:
        kind = next((k for k in ("InlineNode", "ConnectionNode", "PrimaryNode", "SecondaryNode") if k in labels), None)
        nodes[nid] = {"kind": kind, "props": props}
    edges, _ = db.cypher_query("""
        MATCH (a:Node {timestamp: $ts})-[r:rel]->(b:Node {timestamp: $ts})
        RETURN elementId(a), elementId(b), r.rel_type, r.list_index""", {"ts": timestamp})
    return nodes, [tuple(e) for e in edges]

def retrieve_from_nx(timestamp: str, graph_file: str):
    nx_interface = networkxConnection()
    nx_interface.load_graph(graph_file)
    g = nx_interface.graph
    nodes = {n: {"kind": data.get("label"), "props": {k: v for k, v in data.items() if k != "label"}}
             for n, data in g.nodes(data=True) if data.get("timestamp") == timestamp}
    edges = [(u, v, data.get("rel_type"), data.get("list_index", 0))
             for u, v, data in g.edges(data=True) if u in nodes and v in nodes]
    return nodes, edges
