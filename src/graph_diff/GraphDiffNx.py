"""
GraphDiffNx: the NetworkX counterpart of GraphDiff.

It implements the same matching rules on two NetworkX graphs (one per timestamp, as written by
IfcGraphInterface / GeoJsonGraphInterface with graph_provider="networkx"):

  * the two project anchors (root_entity_type) are always equivalent,
  * PrimaryNodes are matched by GlobalId, then children are matched recursively on
    (rel_type, list_index, EntityType); every node gets at most one equivalent,
  * ConnectionNodes are matched by GlobalId first, then by Intersection over Union (== 1.0) of their
    already matched children.

Instead of equivalent_to edges in the database, the result is an equivalence mapping
{init_node_id: updt_node_id}. It can be saved to / loaded from JSON so that diff and patch can run
as separate steps, like the Neo4j workflow where the equivalent_to edges persist in the DB.
"""
import json
import os

from networkX_core.networkx_connection import networkxConnection


class GraphDiffNx:

    def __init__(self, graph_init, graph_updt):
        self.graph_init = graph_init
        self.graph_updt = graph_updt
        self.init_to_updt = {}
        self.updt_to_init = {}
        # Unique paths of ConnectionNodes matched via Intersection over Union (same as GraphDiff).
        self.unique_paths = {}

    @classmethod
    def from_files(cls, graph_file_init: str, graph_file_updt: str):
        nx_init, nx_updt = networkxConnection(), networkxConnection()
        nx_init.load_graph(graph_file_init)
        nx_updt.load_graph(graph_file_updt)
        return cls(nx_init.graph, nx_updt.graph)

    ########################
    ### Helper Functions ###
    ########################

    def __connect(self, node_init, node_updt):
        self.init_to_updt[node_init] = node_updt
        self.updt_to_init[node_updt] = node_init

    @staticmethod
    def __nodes(graph, timestamp, label=None, entity_type=None):
        return [n for n, d in graph.nodes(data=True)
                if d.get("timestamp") == timestamp
                and (label is None or d.get("label") == label)
                and (entity_type is None or d.get("EntityType") == entity_type)]

    def create_equivalence_relations_primary(self, equiv_node_init, equiv_node_updt):
        """
        Traverse the two parsed models starting from PrimaryNodes and find equivalent nodes.
        """
        for _, child_init, rel_init in self.graph_init.out_edges(equiv_node_init, data=True):
            # Children with identity (Primary/ConnectionNodes) are matched by GlobalId / IoU only (see GraphDiff).
            if self.graph_init.nodes[child_init].get("label") in ("PrimaryNode", "ConnectionNode"):
                continue
            for _, child_updt, rel_updt in self.graph_updt.out_edges(equiv_node_updt, data=True):
                if (
                    rel_init.get("rel_type") == rel_updt.get("rel_type")
                    and rel_init.get("list_index") == rel_updt.get("list_index")
                    and self.graph_init.nodes[child_init].get("EntityType") == self.graph_updt.nodes[child_updt].get("EntityType")
                    and child_init not in self.init_to_updt
                    and child_updt not in self.updt_to_init
                ):
                    self.__connect(child_init, child_updt)
                    self.create_equivalence_relations_primary(child_init, child_updt)

    def create_equivalence_relations_connection(self, connection_node_init, connection_node_updt) -> bool:
        """
        Match two ConnectionNodes by GlobalId or by Intersection over Union of their children.

        @return: True if the nodes were matched.
        """
        gid_init = self.graph_init.nodes[connection_node_init].get("GlobalId")
        gid_updt = self.graph_updt.nodes[connection_node_updt].get("GlobalId")
        if gid_init is not None and gid_init == gid_updt:
            self.__connect(connection_node_init, connection_node_updt)
            return True
        children_init = set(self.graph_init.successors(connection_node_init))
        children_updt = set(self.graph_updt.successors(connection_node_updt))
        common_children_count = sum(1 for c in children_init if self.init_to_updt.get(c) in children_updt)
        union = len(children_init) + len(children_updt) - common_children_count
        if union == 0:
            return False
        if common_children_count / union == 1.0:
            self.__connect(connection_node_init, connection_node_updt)
            self.unique_paths[connection_node_init] = {"connection_node": gid_init}
            self.unique_paths[connection_node_updt] = {"connection_node": gid_updt}
            return True
        return False

    ######################
    ### Main Functions ###
    ######################

    def run_diff(self, timestamp_init: str, timestamp_updt: str, root_entity_type: str = "IfcProject") -> dict:
        """
        Compute the equivalence mapping between the two graph versions.

        @return: {init_node_id: updt_node_id}
        """
        roots_init = self.__nodes(self.graph_init, timestamp_init, entity_type=root_entity_type)
        roots_updt = self.__nodes(self.graph_updt, timestamp_updt, entity_type=root_entity_type)
        if len(roots_init) != 1 or len(roots_updt) != 1:
            raise Exception(f"Expected exactly one {root_entity_type} per version, found {len(roots_init)} / {len(roots_updt)}.")
        self.__connect(roots_init[0], roots_updt[0])

        # PrimaryNodes: find partners using the GlobalId, then run the recursive function.
        updt_primary = {}
        for n in self.__nodes(self.graph_updt, timestamp_updt, label="PrimaryNode"):
            updt_primary.setdefault(self.graph_updt.nodes[n].get("GlobalId"), []).append(n)
        for primary_node_init in self.__nodes(self.graph_init, timestamp_init, label="PrimaryNode"):
            partners = updt_primary.get(self.graph_init.nodes[primary_node_init].get("GlobalId"), [])
            if len(partners) != 1:
                continue  # GraphDiff skips missing or ambiguous partners as well
            primary_node_updt = partners[0]
            known = self.init_to_updt.get(primary_node_init)
            if known is not None and known != primary_node_updt:
                continue
            if self.updt_to_init.get(primary_node_updt, primary_node_init) != primary_node_init:
                continue
            self.__connect(primary_node_init, primary_node_updt)
            self.create_equivalence_relations_primary(primary_node_init, primary_node_updt)

        # ConnectionNodes: GlobalId first, then IoU among the unmatched ones.
        connection_nodes_init = self.__nodes(self.graph_init, timestamp_init, label="ConnectionNode")
        connection_nodes_updt = self.__nodes(self.graph_updt, timestamp_updt, label="ConnectionNode")
        updt_by_global_id = {self.graph_updt.nodes[n].get("GlobalId"): n for n in connection_nodes_updt}
        updt_by_global_id.pop(None, None)
        for connection_node_init in connection_nodes_init:
            partner = updt_by_global_id.get(self.graph_init.nodes[connection_node_init].get("GlobalId"))
            if partner is not None and partner not in self.updt_to_init:
                self.__connect(connection_node_init, partner)
        for connection_node_init in connection_nodes_init:
            if connection_node_init in self.init_to_updt:
                continue
            for connection_node_updt in connection_nodes_updt:
                if connection_node_updt in self.updt_to_init:
                    continue
                if self.create_equivalence_relations_connection(connection_node_init, connection_node_updt):
                    break
        return dict(self.init_to_updt)

    @staticmethod
    def equivalence_file(timestamp_init: str, timestamp_updt: str) -> str:
        return f"networkx_equivalence_{timestamp_init}_{timestamp_updt}.json"

    def save_equivalences(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.init_to_updt, f, indent=2)

    @staticmethod
    def load_equivalences(path: str) -> dict:
        with open(path) as f:
            return json.load(f)
