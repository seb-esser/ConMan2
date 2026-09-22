from data_handler.DataHandler import DataHandler
from networkX_core.networkx_connection import networkxConnection
import json
import os

# Query for all nodes without equivalence
# match (n:Node) where not (n)-[:equivalent_to]-(:Node) return n

class GraphDiff:

    def __init__(self, graph_provider: str = "neo4j"):
        self.graph_provider = graph_provider
        self.unique_paths = {}
        self.equivalences = {}
        self._nx_graph_cache = {}

        if self.graph_provider == "neo4j":
            from neo4j_core.neo4j_model import Node, GenericNode, PrimaryNode, ConnectionNode, SecondaryNode, InlineNode, RelProperties
            from neomodel import Traversal
            self.Node = Node
            self.PrimaryNode = PrimaryNode
            self.ConnectionNode = ConnectionNode

        elif self.graph_provider == "networkx":
            pass

    ########################
    ### Adapter Layer    ###
    ########################

    def _get_nx_graph(self, timestamp: str):
        """
        Lazily load and cache the NetworkX graph for a given timestamp so repeated
        lookups (e.g. during recursive equivalence matching) don't re-read the file.
        """
        if timestamp not in self._nx_graph_cache:
            nx_interface = networkxConnection()
            nx_interface.load_graph(f"networkx_graph_{timestamp}.gpickle")
            self._nx_graph_cache[timestamp] = nx_interface.graph
        return self._nx_graph_cache[timestamp]

    def _record_equivalence(self, ts_a: str, node_id_a, ts_b: str, node_id_b):
        """
        Record a symmetric equivalence between two nodes identified by (timestamp, node_id).
        Both directions are stored so lookups work regardless of which side initiates them.
        """
        self.equivalences[(ts_a, node_id_a)] = (ts_b, node_id_b)
        self.equivalences[(ts_b, node_id_b)] = (ts_a, node_id_a)

    def _save_equivalences(self, timestamp_init: str, timestamp_updt: str):
        """
        Persist the computed equivalence map so a separate GraphPatch instance can consume it.
        Unlike Neo4j (where equivalent_to edges are written straight into the shared database),
        NetworkX has no shared store between GraphDiff and GraphPatch instances, so the mapping
        is handed off via a JSON file instead.
        """
        os.makedirs("equivalence_data", exist_ok=True)
        pairs = [
            {"init": {"timestamp": ts_a, "node_id": id_a}, "updt": {"timestamp": ts_b, "node_id": id_b}}
            for (ts_a, id_a), (ts_b, id_b) in self.equivalences.items()
            if ts_a == timestamp_init
        ]
        path = f"equivalence_data/Equivalences_{timestamp_init}_{timestamp_updt}.json"
        with open(path, "w") as f:
            json.dump(pairs, f, indent=4)

    def _get_project_node(self, timestamp: str):
        if self.graph_provider == "neo4j":
            return self.Node.nodes.get(EntityType="IfcProject", timestamp=timestamp)
        elif self.graph_provider == "networkx":
            graph = self._get_nx_graph(timestamp)
            for node_id, node_data in graph.nodes(data=True):
                if node_data.get("EntityType") == "IfcProject" and node_data.get("timestamp") == timestamp:
                    return (node_id, node_data)
            return None

    def _get_primary_nodes(self, timestamp: str):
        if self.graph_provider == "neo4j":
            return list(self.PrimaryNode.nodes.filter(timestamp=timestamp))
        elif self.graph_provider == "networkx":
            graph = self._get_nx_graph(timestamp)
            return [
                (node_id, node_data)
                for node_id, node_data in graph.nodes(data=True)
                if node_data.get("label") == "PrimaryNode" and node_data.get("timestamp") == timestamp
            ]

    def _get_connection_nodes(self, timestamp: str):
        if self.graph_provider == "neo4j":
            return list(self.ConnectionNode.nodes.filter(timestamp=timestamp))
        elif self.graph_provider == "networkx":
            graph = self._get_nx_graph(timestamp)
            return [
                (node_id, node_data)
                for node_id, node_data in graph.nodes(data=True)
                if node_data.get("label") == "ConnectionNode" and node_data.get("timestamp") == timestamp
            ]
        
    ########################
    ### Helper Functions ###
    ########################

    def create_equivalence_relations_primary(self, equiv_node_init, equiv_node_updt):
        """
        Traverse the two parsed models starting from PrimaryNodes and find equivalent nodes. Create equilavent_to relations between them.
        """
        if self.graph_provider == "neo4j":
            # Iterate over all related nodes.
            for child_init in equiv_node_init.relation_to.all():
                rel_init = equiv_node_init.relation_to.relationship(child_init)
                # Iterate over all corresponding node's related nodes.
                for child_updt in equiv_node_updt.relation_to.all():
                    rel_updt = equiv_node_updt.relation_to.relationship(child_updt)
                    # Check if the child nodes are equivalent.
                    if (
                        rel_init.rel_type == rel_updt.rel_type
                        and rel_init.list_index == rel_updt.list_index
                        and child_init.EntityType == child_updt.EntityType
                        and not child_init.equivalent_to.filter(timestamp=child_init.timestamp)
                        and not child_updt.equivalent_to.filter(timestamp=child_updt.timestamp)
                    ):
                        # Create equivalent_to edge and recursively run the funciton.
                        child_init.equivalent_to.connect(child_updt)
                        self.create_equivalence_relations_primary(child_init, child_updt)

        elif self.graph_provider == "networkx":
            node_id_init, node_data_init = equiv_node_init
            node_id_updt, node_data_updt = equiv_node_updt
            ts_init, ts_updt = node_data_init["timestamp"], node_data_updt["timestamp"]
            graph_init, graph_updt = self._get_nx_graph(ts_init), self._get_nx_graph(ts_updt)

            for child_id_init in graph_init.successors(node_id_init):
                edge_init = list(graph_init.get_edge_data(node_id_init, child_id_init).values())[0]
                for child_id_updt in graph_updt.successors(node_id_updt):
                    edge_updt = list(graph_updt.get_edge_data(node_id_updt, child_id_updt).values())[0]
                    child_data_init = graph_init.nodes[child_id_init]
                    child_data_updt = graph_updt.nodes[child_id_updt]
                    # Check if the child nodes are equivalent.
                    if (
                        edge_init.get("rel_type") == edge_updt.get("rel_type")
                        and edge_init.get("list_index") == edge_updt.get("list_index")
                        and child_data_init.get("EntityType") == child_data_updt.get("EntityType")
                        and (ts_init, child_id_init) not in self.equivalences
                        and (ts_updt, child_id_updt) not in self.equivalences
                    ):
                        # Record equivalence and recursively run the function.
                        self._record_equivalence(ts_init, child_id_init, ts_updt, child_id_updt)
                        self.create_equivalence_relations_primary(
                            (child_id_init, child_data_init), (child_id_updt, child_data_updt)
                        )


    def create_equivalence_relations_connection(self, connection_node_init, connection_node_updt):
        """
        Traverse the two parsed models starting from ConnectionNodes and find equivalent nodes. Create equilavent_to relations between them.
        """
        if self.graph_provider == "neo4j":
            # Check if a globalid exists on the nodes and if they are the same.
            global_id_init = getattr(connection_node_init, "GlobalId", None)
            global_id_updt = getattr(connection_node_updt, "GlobalId", None)

            if global_id_init and global_id_updt and global_id_init == global_id_updt:
                connection_node_init.equivalent_to.connect(connection_node_updt)
                return

            # Since ConnectionNodes dont necessarily have a persistent globalid, another check is used to identify equivalence.
            # This check uses Intersection over Union of the ConnectionNode and its children.
            common_children_count = 0
            for child_init in connection_node_init.relation_to.all():
                for child_updt in connection_node_updt.relation_to.all():
                    # If children are equivalent, count them as a point FOR equivalence of the ConnectionNodes.
                    if child_init.equivalent_to.relationship(child_updt) is not None:
                        common_children_count += 1
            # Get the respective children that are not equivalent between the init and updt Connection nodes.
            unique_children_count_init = len(connection_node_init.relation_to.all()) - common_children_count
            unique_children_count_updt = len(connection_node_updt.relation_to.all()) - common_children_count
            # Compute the intersection over union. ConnectionNodes are equivalent of all children are equivalent.
            iou = common_children_count / (unique_children_count_init + common_children_count + unique_children_count_updt)
            if iou == 1.0:
                connection_node_init.equivalent_to.connect(connection_node_updt)
                if global_id_init:
                    self.unique_paths[connection_node_init.element_id] = {"connection_node": global_id_init}
                if global_id_updt:
                    self.unique_paths[connection_node_updt.element_id] = {"connection_node": global_id_updt}

        elif self.graph_provider == "networkx":
            node_id_init, node_data_init = connection_node_init
            node_id_updt, node_data_updt = connection_node_updt
            ts_init, ts_updt = node_data_init["timestamp"], node_data_updt["timestamp"]
            # Check if a globalid exists on the nodes and if they are the same.
            global_id_init, global_id_updt = node_data_init.get("GlobalId"), node_data_updt.get("GlobalId")

            if global_id_init and global_id_updt and global_id_init == global_id_updt:
                self._record_equivalence(ts_init, node_id_init, ts_updt, node_id_updt)
                return

            # Since ConnectionNodes dont necessarily have a persistent globalid, another check is used to identify equivalence.
            # This check uses Intersection over Union of the ConnectionNode and its children.
            graph_init, graph_updt = self._get_nx_graph(ts_init), self._get_nx_graph(ts_updt)
            children_init = list(graph_init.successors(node_id_init))
            children_updt = list(graph_updt.successors(node_id_updt))

            common_children_count = 0
            for child_id_init in children_init:
                for child_id_updt in children_updt:
                    # If children are equivalent, count them as a point FOR equivalence of the ConnectionNodes.
                    if self.equivalences.get((ts_init, child_id_init)) == (ts_updt, child_id_updt):
                        common_children_count += 1
            # Get the respective children that are not equivalent between the init and updt Connection nodes.
            unique_children_count_init = len(children_init) - common_children_count
            unique_children_count_updt = len(children_updt) - common_children_count
            denom = unique_children_count_init + common_children_count + unique_children_count_updt
            if denom == 0:
                # Both nodes have no children to compare and no matching GlobalId; treat as inconclusive
                # rather than dividing by zero (the neo4j branch above does not guard against this case).
                return
            # Compute the intersection over union. ConnectionNodes are equivalent of all children are equivalent.
            iou = common_children_count / denom
            if iou == 1.0:
                self._record_equivalence(ts_init, node_id_init, ts_updt, node_id_updt)
                if global_id_init:
                    self.unique_paths[(ts_init, node_id_init)] = {"connection_node": global_id_init}
                if global_id_updt:
                    self.unique_paths[(ts_updt, node_id_updt)] = {"connection_node": global_id_updt}


    ######################
    ### Main Functions ###
    ######################

    def run_diff(self, timestamp_init:str, timestamp_updt:str):
        """
        Recursively compares nodes on graph for equivalence and generates equivalent_to relations between them.
        """
        if self.graph_provider == "neo4j":
            project_init = self._get_project_node(timestamp_init)
            project_updt = self._get_project_node(timestamp_updt)
            #Looks directed but is undirectedly treated.
            project_init.equivalent_to.connect(project_updt)

            # For PrimaryNodes, find partners using the globalid, then run the recursive function.
            for primary_node_init in self._get_primary_nodes(timestamp=timestamp_init):
                try:
                    primary_node_updt = self.PrimaryNode.nodes.get(GlobalId=primary_node_init.GlobalId, timestamp=timestamp_updt)
                except:
                    continue
                primary_node_init.equivalent_to.connect(primary_node_updt)
                self.create_equivalence_relations_primary(primary_node_init, primary_node_updt)
            # For ConnectionNodes, find all in both models, then run the Intersection over Union function.
            for connection_node_init in self._get_connection_nodes(timestamp=timestamp_init):
                for connection_node_updt in self._get_connection_nodes(timestamp=timestamp_updt):
                    self.create_equivalence_relations_connection(connection_node_init, connection_node_updt)
            return

        elif self.graph_provider == "networkx":
            project_init = self._get_project_node(timestamp_init)
            project_updt = self._get_project_node(timestamp_updt)
            #Looks directed but is undirectedly treated.
            self._record_equivalence(timestamp_init, project_init[0], timestamp_updt, project_updt[0])

            # For PrimaryNodes, find partners using the globalid. NetworkX has no database index, so
            # build a one-time lookup dict for the updt side instead of scanning it per init node.
            primary_nodes_updt = self._get_primary_nodes(timestamp=timestamp_updt)
            global_id_index_updt = {
                node_data.get("GlobalId"): (node_id, node_data)
                for node_id, node_data in primary_nodes_updt
                if node_data.get("GlobalId")
            }
            for primary_node_init in self._get_primary_nodes(timestamp=timestamp_init):
                node_id_init, node_data_init = primary_node_init
                primary_node_updt = global_id_index_updt.get(node_data_init.get("GlobalId"))
                if primary_node_updt is None:
                    continue
                self._record_equivalence(timestamp_init, node_id_init, timestamp_updt, primary_node_updt[0])
                self.create_equivalence_relations_primary(primary_node_init, primary_node_updt)
            # For ConnectionNodes, find all in both models, then run the Intersection over Union function.
            for connection_node_init in self._get_connection_nodes(timestamp=timestamp_init):
                for connection_node_updt in self._get_connection_nodes(timestamp=timestamp_updt):
                    self.create_equivalence_relations_connection(connection_node_init, connection_node_updt)

            # Hand off the computed equivalences to GraphPatch, which runs as a separate instance
            # and (unlike Neo4j) has no shared database to read them back from.
            self._save_equivalences(timestamp_init, timestamp_updt)