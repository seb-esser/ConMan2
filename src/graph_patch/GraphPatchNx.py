"""
GraphPatchNx: the NetworkX counterpart of GraphPatch.

Method by method it mirrors GraphPatch (unique path mappings, semantic patch, topological patch,
apply_patch) and reads/writes the **same JSON patch files** in patch_data/. A patch created with the
Neo4j provider can be applied to a NetworkX graph and vice versa:

  * topological patch entries are keyed by node id (Neo4j: element id, NetworkX: node key), and
    "properties" always carries "element_id_property" (= that key), which GraphPatch.apply_patch uses
    to wire up pushout nodes,
  * node properties are compared in the same "view" as neomodel's __properties__ minus the volatile
    keys: for Generic nodes the NetworkX node key is exposed as p21_id, the NetworkX-only attributes
    "label" (node class) and the p21_id of InlineNodes are hidden.
"""
import json
import os

from data_handler.DataHandler import DataHandler
from graph_patch.context_relations import context_relation_delta, KEY as CONTEXT_RELATIONS
from networkX_core.networkx_connection import networkxConnection

IGNORED_SEMANTIC_KEYS = ("timestamp", "element_id_property")


class GraphPatchNx:

    ########################
    ### Helper Functions ###
    ########################

    @staticmethod
    def node_view(graph, node) -> dict:
        """Node properties as GraphPatch sees them (neomodel __properties__ without element_id_property)."""
        data = graph.nodes[node]
        props = {k: v for k, v in data.items() if k not in ("label", "p21_id")}
        if data.get("label") != "InlineNode":
            props["p21_id"] = data.get("p21_id", node)
        return props

    @staticmethod
    def __children(graph, node):
        """Distinct successors with the first connecting edge (like relation_to.all() + relationship())."""
        seen = {}
        for _, child, data in graph.out_edges(node, data=True):
            seen.setdefault(child, data)
        return seen.items()

    @staticmethod
    def __parents(graph, node):
        seen = {}
        for parent, _, data in graph.in_edges(node, data=True):
            seen.setdefault(parent, data)
        return seen.items()

    @staticmethod
    def __start_path(graph, node):
        label = graph.nodes[node].get("label")
        if label == "PrimaryNode":
            return [{"primary_node": graph.nodes[node].get("GlobalId")}]
        if label == "ConnectionNode":
            return [{"connection_node": graph.nodes[node].get("GlobalId")}]
        return None

    def __is_equivalent(self, timestamp, node) -> bool:
        return node in self.equivalence[timestamp]

    def create_unique_path_mappings(self, graph, node, timestamp, unique_path=None):
        if node in self.node_ids_to_unique_paths_mapping[timestamp]:
            return
        unique_path = self.__start_path(graph, node) or unique_path
        self.node_ids_to_unique_paths_mapping[timestamp][node] = DataHandler.path_to_string(unique_path)
        for child, rel in self.__children(graph, node):
            if self.__is_equivalent(timestamp, child):
                new_path = unique_path + [{"rel_type": rel.get("rel_type"), "list_index": rel.get("list_index"),
                                           "EntityType": graph.nodes[child].get("EntityType")}]
                self.create_unique_path_mappings(graph, child, timestamp, new_path)

    def create_init_side_unique_path_mappings(self, graph, node, timestamp, unique_path=None):
        if node in self.init_side_node_ids_to_unique_paths_mapping[timestamp]:
            return
        unique_path = self.__start_path(graph, node) or unique_path
        self.init_side_node_ids_to_unique_paths_mapping[timestamp][node] = DataHandler.path_to_string(unique_path)
        for child, rel in self.__children(graph, node):
            new_path = unique_path + [{"rel_type": rel.get("rel_type"), "list_index": rel.get("list_index"),
                                       "EntityType": graph.nodes[child].get("EntityType")}]
            self.create_init_side_unique_path_mappings(graph, child, timestamp, new_path)

    @staticmethod
    def find_node_from_unique_path(graph, unique_path: str, timestamp):
        path = DataHandler.string_to_path(unique_path)
        if "primary_node" in path[0]:
            label, global_id = "PrimaryNode", path[0]["primary_node"]
        elif "connection_node" in path[0]:
            label, global_id = "ConnectionNode", path[0]["connection_node"]
        else:
            raise LookupError(f"Unique path {unique_path!r} does not start at a Primary or ConnectionNode.")
        starts = [n for n, d in graph.nodes(data=True)
                  if d.get("timestamp") == timestamp and d.get("label") == label and d.get("GlobalId") == global_id]
        if len(starts) != 1:
            raise LookupError(f"Start node of unique path {unique_path!r} found {len(starts)} times in timestamp {timestamp}.")
        latest_node = starts[0]
        for i in range(1, len(path)):
            next_node = None
            for _, contestant, rel in graph.out_edges(latest_node, data=True):
                if (rel.get("rel_type") == path[i]["rel_type"] and rel.get("list_index") == path[i]["list_index"]
                        and graph.nodes[contestant].get("EntityType") == path[i]["EntityType"]):
                    next_node = contestant
            if next_node is None:
                raise LookupError(f"Unique path {unique_path!r} cannot be resolved at step {i} ({path[i]}) in timestamp {timestamp}.")
            latest_node = next_node
        return latest_node

    def __relation_change(self, graph, node, property_key, timestamp_relation, timestamp_value, value):
        adjacents = [(child, rel) for _, child, rel in graph.out_edges(node, data=True) if rel.get("rel_type") == property_key]
        if not adjacents:
            return None
        adjacent, rel = adjacents[0]
        if not self.__is_equivalent(timestamp_relation, adjacent):
            return None
        return {
            timestamp_relation: {
                "path": self.node_ids_to_unique_paths_mapping[timestamp_relation][adjacent],
                "rel_type": property_key,
                "list_index": rel.get("list_index")
            },
            timestamp_value: value
        }

    def create_semantic_patch_pattern(self, timestamp_init, timestamp_updt):
        g_init, g_updt = self.graphs[timestamp_init], self.graphs[timestamp_updt]
        for node_init, node_updt in self.equivalence[timestamp_init].items():
            unique_path = self.node_ids_to_unique_paths_mapping[timestamp_init][node_init]
            properties_init = self.node_view(g_init, node_init)
            properties_updt = self.node_view(g_updt, node_updt)
            property_keys = list(properties_init) + [k for k in properties_updt if k not in properties_init]
            for property_key in property_keys:
                if property_key in IGNORED_SEMANTIC_KEYS:
                    continue
                property_value = properties_init.get(property_key)
                property_value_updt = properties_updt.get(property_key)
                if property_value == property_value_updt:
                    continue
                change = None
                if property_value is None:
                    change = self.__relation_change(g_init, node_init, property_key, timestamp_init, timestamp_updt, property_value_updt)
                elif property_value_updt is None:
                    change = self.__relation_change(g_updt, node_updt, property_key, timestamp_updt, timestamp_init, property_value)
                if change is None:
                    change = {timestamp_init: property_value, timestamp_updt: property_value_updt}
                self.semantic_patch_pattern.setdefault(unique_path, {})[property_key] = change

    def create_topological_patch_pattern(self, pushout_nodes, timestamp):
        graph = self.graphs[timestamp]
        for pushout_node in pushout_nodes:
            key = str(pushout_node)
            entry = {"properties": {**self.node_view(graph, pushout_node), "element_id_property": key},
                     "node_type": graph.nodes[pushout_node].get("label"),
                     "path": "", "relation_to": {}, "context_to": {}, "context_from": {}}
            if pushout_node in self.init_side_node_ids_to_unique_paths_mapping[timestamp]:
                entry["path"] = self.init_side_node_ids_to_unique_paths_mapping[timestamp][pushout_node]
            for adjacent, rel in self.__children(graph, pushout_node):
                rel_props = {"rel_type": rel.get("rel_type"), "list_index": rel.get("list_index")}
                if self.__is_equivalent(timestamp, adjacent):
                    entry["context_to"][str(adjacent)] = {"path": self.node_ids_to_unique_paths_mapping[timestamp][adjacent], "properties": rel_props}
                else:
                    entry["relation_to"][str(adjacent)] = {"properties": rel_props}
            for adjacent, rel in self.__parents(graph, pushout_node):
                if self.__is_equivalent(timestamp, adjacent):
                    entry["context_from"][str(adjacent)] = {"path": self.node_ids_to_unique_paths_mapping[timestamp][adjacent],
                                                           "properties": {"rel_type": rel.get("rel_type"), "list_index": rel.get("list_index")}}
            self.topological_patch_pattern[timestamp][key] = entry

    def create_context_relation_pattern(self, timestamp_init, timestamp_updt):
        """Relations between equivalent nodes that exist in only one version (see graph_patch/context_relations.py)."""
        edges = {}
        for ts in (timestamp_init, timestamp_updt):
            graph, partner = self.graphs[ts], self.equivalence[ts]
            edges[ts] = [(a, b, d.get("rel_type"), d.get("list_index")) for a, b, d in graph.edges(data=True)
                         if a in partner and b in partner]
        return context_relation_delta(edges, self.equivalence, self.node_ids_to_unique_paths_mapping, timestamp_init, timestamp_updt)

    def load_patch_from_file(self, path_topo, path_sema):
        with open(path_sema, "r") as f:
            self.semantic_patch_pattern = json.load(f)
        with open(path_topo, "r") as f:
            self.topological_patch_pattern = json.load(f)

    def __reset(self, timestamp_init, timestamp_updt):
        self.node_ids_to_unique_paths_mapping = {timestamp_init: {}, timestamp_updt: {}}
        self.init_side_node_ids_to_unique_paths_mapping = {timestamp_init: {}, timestamp_updt: {}}
        self.topological_patch_pattern = {timestamp_init: {}, timestamp_updt: {}}
        self.semantic_patch_pattern = {}
        self.nodes_to_delete = []

    @staticmethod
    def __prim_and_con(graph, timestamp):
        return [n for n, d in graph.nodes(data=True)
                if d.get("timestamp") == timestamp and d.get("label") in ("PrimaryNode", "ConnectionNode")]

    ######################
    ### Main Functions ###
    ######################

    def create_patch(self, project_id: str, timestamp_init: str, timestamp_updt: str,
                     graph_init, graph_updt, equivalence: dict, patch_dir: str = "patch_data"):
        """
        Create the semantic and the topological patch from two graphs and their equivalence mapping
        (GraphDiffNx.run_diff). Writes the same files as GraphPatch.create_patch.
        """
        self.__reset(timestamp_init, timestamp_updt)
        self.graphs = {timestamp_init: graph_init, timestamp_updt: graph_updt}
        self.equivalence = {timestamp_init: dict(equivalence), timestamp_updt: {v: k for k, v in equivalence.items()}}

        for ts in (timestamp_init, timestamp_updt):
            graph = self.graphs[ts]
            for node in self.__prim_and_con(graph, ts):
                self.create_init_side_unique_path_mappings(graph, node, ts)
                if self.__is_equivalent(ts, node):
                    self.create_unique_path_mappings(graph, node, ts)

        pushout_nodes = {ts: [n for n, d in self.graphs[ts].nodes(data=True)
                              if d.get("timestamp") == ts and not self.__is_equivalent(ts, n)]
                         for ts in (timestamp_init, timestamp_updt)}

        self.create_semantic_patch_pattern(timestamp_init, timestamp_updt)
        self.create_topological_patch_pattern(pushout_nodes[timestamp_init], timestamp_init)
        self.create_topological_patch_pattern(pushout_nodes[timestamp_updt], timestamp_updt)
        self.topological_patch_pattern[CONTEXT_RELATIONS] = self.create_context_relation_pattern(timestamp_init, timestamp_updt)

        os.makedirs(patch_dir, exist_ok=True)
        with open(f"{patch_dir}/Patch_Topo_{project_id}_{timestamp_init}_{timestamp_updt}.json", "w") as f:
            json.dump(self.topological_patch_pattern, f, indent=4)
        with open(f"{patch_dir}/Patch_Sema_{project_id}_{timestamp_init}_{timestamp_updt}.json", "w") as f:
            json.dump(self.semantic_patch_pattern, f, indent=4)

    def apply_patch(self, project_id: str, timestamp_init: str, timestamp_updt: str,
                    graph_file_init: str = None, graph_file_updt: str = None, patch_dir: str = "patch_data"):
        """
        Apply a patch to the NetworkX graph of timestamp_init and write the graph of timestamp_updt.
        Works in both directions (the patch files are looked up as <init>_<updt> and <updt>_<init>).
        """
        self.__reset(timestamp_init, timestamp_updt)
        graph_file_init = graph_file_init or f"networkx_graph_{timestamp_init}.gpickle"
        graph_file_updt = graph_file_updt or f"networkx_graph_{timestamp_updt}.gpickle"
        try:
            self.load_patch_from_file(f"{patch_dir}/Patch_Topo_{project_id}_{timestamp_init}_{timestamp_updt}.json",
                                      f"{patch_dir}/Patch_Sema_{project_id}_{timestamp_init}_{timestamp_updt}.json")
        except FileNotFoundError:
            self.load_patch_from_file(f"{patch_dir}/Patch_Topo_{project_id}_{timestamp_updt}_{timestamp_init}.json",
                                      f"{patch_dir}/Patch_Sema_{project_id}_{timestamp_updt}_{timestamp_init}.json")

        nx_interface = networkxConnection()
        nx_interface.load_graph(graph_file_init)
        graph = nx_interface.graph

        # Resolve the endpoints of context relation changes before the graph is modified; applied at the end.
        context_relations = self.topological_patch_pattern.get(CONTEXT_RELATIONS, {})
        resolve = lambda e: (self.find_node_from_unique_path(graph, e["source"][timestamp_init], timestamp_init),
                             self.find_node_from_unique_path(graph, e["target"][timestamp_init], timestamp_init),
                             e["rel_type"], e["list_index"])
        context_relations_remove = [resolve(e) for e in context_relations.get(timestamp_init, [])]
        context_relations_add = [resolve(e) for e in context_relations.get(timestamp_updt, [])]

        # Deletion of init: unreachable nodes and init pushout nodes.
        for node in self.__prim_and_con(graph, timestamp_init):
            self.create_init_side_unique_path_mappings(graph, node, timestamp_init)
        for node, data in list(graph.nodes(data=True)):
            if data.get("timestamp") == timestamp_init and node not in self.init_side_node_ids_to_unique_paths_mapping[timestamp_init]:
                self.nodes_to_delete.append(node)
        for pushout_node_ref in self.topological_patch_pattern[timestamp_init].values():
            if pushout_node_ref["path"]:
                node = self.find_node_from_unique_path(graph, pushout_node_ref["path"], timestamp_init)
                if node not in self.nodes_to_delete:
                    self.nodes_to_delete.append(node)
        graph.remove_nodes_from(self.nodes_to_delete)

        # Insertion of updt: create pushout nodes, then wire them to each other and to the context.
        pushout_node_refs_updt = self.topological_patch_pattern[timestamp_updt]
        added = {}
        for key, ref in pushout_node_refs_updt.items():
            props = {k: v for k, v in ref["properties"].items() if k != "element_id_property"}
            label = ref["node_type"]
            node_id = props.get("p21_id") if label != "InlineNode" else None
            if node_id is None or graph.has_node(node_id):
                base = node_id or f"inline:{key}"
                node_id, n = base, 0
                while graph.has_node(node_id):
                    n += 1
                    node_id = f"{base}~{n}"
            if label == "InlineNode":
                props["p21_id"] = node_id
            else:
                props.pop("p21_id", None)
            graph.add_node(node_id, **props, label=label)
            added[ref["properties"].get("element_id_property", key)] = node_id

        for key, ref in pushout_node_refs_updt.items():
            pushout_node = added[ref["properties"].get("element_id_property", key)]
            for key_relation, relation in ref["relation_to"].items():
                rel = relation["properties"]
                graph.add_edge(pushout_node, added[key_relation], rel_type=rel["rel_type"], list_index=rel["list_index"])
                graph.nodes[pushout_node].pop(rel["rel_type"], None)
            for context_to in ref["context_to"].values():
                rel = context_to["properties"]
                context_node = self.find_node_from_unique_path(graph, context_to["path"], timestamp_init)
                graph.add_edge(pushout_node, context_node, rel_type=rel["rel_type"], list_index=rel["list_index"])
                graph.nodes[pushout_node].pop(rel["rel_type"], None)
            for context_from in ref["context_from"].values():
                rel = context_from["properties"]
                context_node = self.find_node_from_unique_path(graph, context_from["path"], timestamp_init)
                graph.add_edge(context_node, pushout_node, rel_type=rel["rel_type"], list_index=rel["list_index"])
                graph.nodes[context_node].pop(rel["rel_type"], None)

        # Update the existing nodes based on the semantic patch.
        for unique_path, changes in self.semantic_patch_pattern.items():
            node = self.find_node_from_unique_path(graph, unique_path, timestamp_init)
            for property_key, change in changes.items():
                value_init, value_updt = change.get(timestamp_init), change.get(timestamp_updt)
                if isinstance(value_updt, dict) and "path" in value_updt:
                    adjacent = self.find_node_from_unique_path(graph, value_updt["path"], timestamp_init)
                    graph.add_edge(node, adjacent, rel_type=value_updt["rel_type"], list_index=value_updt["list_index"])
                    graph.nodes[node].pop(property_key, None)
                elif isinstance(value_init, dict) and "path" in value_init:
                    adjacent = self.find_node_from_unique_path(graph, value_init["path"], timestamp_init)
                    for k in [k for _, v, k, d in graph.out_edges(node, keys=True, data=True)
                              if v == adjacent and d.get("rel_type") == property_key]:
                        graph.remove_edge(node, adjacent, key=k)
                    graph.nodes[node][property_key] = "$" if value_updt is None else value_updt
                elif property_key == "p21_id":
                    continue  # node key / bulk-load id, not a model attribute in the NetworkX provider
                elif value_updt is None:
                    graph.nodes[node].pop(property_key, None)
                else:
                    graph.nodes[node][property_key] = value_updt

        # Apply context relation changes (idempotent, like GraphPatch).
        def matching_edges(a, b, rel_type, list_index):
            return [k for _, v, k, d in graph.out_edges(a, keys=True, data=True)
                    if v == b and d.get("rel_type") == rel_type and d.get("list_index") == list_index]
        for a, b, rel_type, list_index in context_relations_remove:
            for k in matching_edges(a, b, rel_type, list_index):
                graph.remove_edge(a, b, key=k)
        for a, b, rel_type, list_index in context_relations_add:
            if not matching_edges(a, b, rel_type, list_index):
                graph.add_edge(a, b, rel_type=rel_type, list_index=list_index)
            graph.nodes[a].pop(rel_type, None)

        # Restamp the remaining init nodes so the whole graph is the updt version.
        for node, data in graph.nodes(data=True):
            if data.get("timestamp") == timestamp_init:
                data["timestamp"] = timestamp_updt
        nx_interface.save_graph(graph_file_updt)
        return graph
