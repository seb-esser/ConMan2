from neo4j_core.neo4j_model import Node, GenericNode, PrimaryNode, ConnectionNode, SecondaryNode, InlineNode, RelProperties
import json
import os
from neomodel import db
from data_handler.DataHandler import DataHandler

class GraphPatch:

    # node_ids_to_unique_paths_mapping = {}
    # init_side_node_ids_to_unique_paths_mapping = {} #includes pushout nodes in path, used to identify non-danlging pushout nodes to delete

    # topological_patch_pattern = {}
    # semantic_patch_pattern = {}
    # nodes_to_delete = []

    ########################
    ### Helper Functions ###
    ########################

    def create_unique_path_mappings(self, node, timestamp, unique_path=None):
        """
        Starting from a Primary or ConnectionNode, create unique paths for every reachable node in the graph. These are used to identify nodes without GlobalIds across different versions of a model.
        """
        # Check if node already has an entry in the dictionaaries that map a node to a unique path and vice-versa.
        if node.element_id not in self.node_ids_to_unique_paths_mapping[timestamp]:
            # If the node is a PrimaryNode or a ConnectionNode, reset the path because this is the base for a unique path.
            if type(node) == PrimaryNode:
                unique_path = [{"primary_node": node.GlobalId}]
            if type(node) == ConnectionNode:
                unique_path = [{"connection_node": node.GlobalId}]
            # Create entries in the dicts for the node and its unique path.
            self.node_ids_to_unique_paths_mapping[timestamp][node.element_id] = DataHandler.path_to_string(unique_path)
            # Create a unique path to a child element and then recursively run the function until a leaf node is reached.
            for child in node.relation_to.all():
                if child.equivalent_to.all():
                    rel = node.relation_to.relationship(child)
                    new_path = unique_path + [{"rel_type": rel.rel_type, "list_index": rel.list_index, "EntityType": child.EntityType}]
                    self.create_unique_path_mappings(child, timestamp, new_path)

    def create_init_side_unique_path_mappings(self, node, timestamp, unique_path=None):
        if node.element_id not in self.init_side_node_ids_to_unique_paths_mapping[timestamp]:
            # If the node is a PrimaryNode or a ConnectionNode, reset the path because this is the base for a unique path.
            if type(node) == PrimaryNode:
                unique_path = [{"primary_node": node.GlobalId}]
            if type(node) == ConnectionNode:
                unique_path = [{"connection_node": node.GlobalId}]
            # Create entries in the dicts for the node and its unique path.
            self.init_side_node_ids_to_unique_paths_mapping[timestamp][node.element_id] = DataHandler.path_to_string(unique_path)
            # Create a unique path to a child element and then recursively run the function until a leaf node is reached.
            for child in node.relation_to.all():
                rel = node.relation_to.relationship(child)
                new_path = unique_path + [{"rel_type": rel.rel_type, "list_index": rel.list_index, "EntityType": child.EntityType}]
                self.create_init_side_unique_path_mappings(child, timestamp, new_path)

    def find_node_from_unique_path(self, unique_path: str, timestamp):
        """
        Function translates a unique path str to a unique path to find a node by its unique path in the graph db.
        """
        path = DataHandler.string_to_path(unique_path)
        # Path can either start with a PrimaryNode or with a ConnectionNode. Retrieve that start node by its GlobalId to start the search.
        if "primary_node" in path[0]:
            start_node = PrimaryNode.nodes.get(timestamp=timestamp, GlobalId=path[0]["primary_node"])
        elif "connection_node" in path[0]:
            start_node = ConnectionNode.nodes.get(timestamp=timestamp, GlobalId=path[0]["connection_node"])
        latest_node = start_node
        # Traverse the graph using the unique path as a template to find the node in question.
        for i in range(1, len(path)):
            # A unique step in the unique path is defined by the relation type, the list index of the relation, and the entity type of the target node.
            for contestant in latest_node.relation_to.match(rel_type=path[i]["rel_type"], list_index=path[i]["list_index"]):
                if contestant.EntityType == path[i]["EntityType"]:
                    latest_node = contestant
            i += 1
        return latest_node
    
    
    def create_semantic_patch_pattern(self, equivalent_nodes_init, timestamp_init, timestamp_updt):
        """
        Among the nodes that are deemed equivalent during the Diff, compare the attributes and note and differences.
        """
        for node_init in equivalent_nodes_init:
            # Find the corresponding equivalent node in the db.
            node_updt = node_init.equivalent_to.all()[0]
            unique_path = self.node_ids_to_unique_paths_mapping[timestamp_init][node_init.element_id]

            for property_key, property_value in node_init.__properties__.items():
                # Exclude checking for the attributes timestamp and node id, as these are supposed to be different..
                if property_key not in ["timestamp", "element_id_property"]:
                    # Compare the attribute values.
                    property_value_updt = node_updt.__properties__.get(property_key)
                    if property_value != property_value_updt:
                        if unique_path not in self.semantic_patch_pattern:
                            self.semantic_patch_pattern[unique_path] = {}
                        if property_value is None:
                            adjacent =  node_init.relation_to.match(rel_type=property_key)[0]
                            if adjacent.equivalent_to.all():
                                self.semantic_patch_pattern[unique_path][property_key] = {}
                                self.semantic_patch_pattern[unique_path][property_key][timestamp_init] = {
                                    "path": self.node_ids_to_unique_paths_mapping[timestamp_init][adjacent.element_id],
                                    "rel_type": property_key,
                                    "list_index": node_init.relation_to.relationship(adjacent).list_index
                                }
                                self.semantic_patch_pattern[unique_path][property_key][timestamp_updt] = property_value_updt
                            else:
                                continue
                        elif property_value_updt is None:
                            adjacent =  node_updt.relation_to.match(rel_type=property_key)[0]
                            if adjacent.equivalent_to.all():
                                self.semantic_patch_pattern[unique_path][property_key] = {}
                                self.semantic_patch_pattern[unique_path][property_key][timestamp_updt] = {
                                    "path": self.node_ids_to_unique_paths_mapping[timestamp_updt][adjacent.element_id],
                                    "rel_type": property_key,
                                    "list_index": node_updt.relation_to.relationship(adjacent).list_index
                                }
                                self.semantic_patch_pattern[unique_path][property_key][timestamp_init] = property_value
                            else:
                                continue
                        else:
                            self.semantic_patch_pattern[unique_path][property_key] = {}
                            self.semantic_patch_pattern[unique_path][property_key][timestamp_init] = property_value
                            self.semantic_patch_pattern[unique_path][property_key][timestamp_updt] = property_value_updt


    def create_topological_patch_pattern(self, pushout_nodes, timestamp):
        """
        Among the nodes that are not deemed equivalent during the diff, document their structure and information fo future reference.
        """
        for pushout_node in pushout_nodes:
            # Add the pushout node with all its properties into the topological patch pattern and create additional attributes for the structural information.
            # relation_to are relationships to other pushout nodes. context_to and context_from are relationships to equivalent nodes that will be used to identify the pushout nodes.
            self.topological_patch_pattern[timestamp][pushout_node.element_id] = {"properties": {**dict(pushout_node.__properties__)}, "node_type": type(pushout_node).__name__, "path": "", "relation_to": {}, "context_to": {}, "context_from": {}}
            # If a pushout node is reachable (has a unique path), the unique path is stored.
            if pushout_node.element_id in self.init_side_node_ids_to_unique_paths_mapping[timestamp]:
                self.topological_patch_pattern[timestamp][pushout_node.element_id]["path"] = self.init_side_node_ids_to_unique_paths_mapping[timestamp][pushout_node.element_id]
            # Look at adjacent nodes from outgoing edges and store them with the pushout node. Mark down if it is another pushout node or a context node.
            for adjacent in pushout_node.relation_to.all():
                if adjacent.timestamp != pushout_node.timestamp:
                    continue
                relation_to = pushout_node.relation_to.relationship(adjacent)
                # If related node has an equivalence, it is a context node.
                if adjacent.equivalent_to.all():
                    self.topological_patch_pattern[timestamp][pushout_node.element_id]["context_to"][adjacent.element_id] = {"path": self.node_ids_to_unique_paths_mapping[timestamp][adjacent.element_id], "properties": relation_to.__properties__}
                else:
                    self.topological_patch_pattern[timestamp][pushout_node.element_id]["relation_to"][adjacent.element_id] = {"properties": relation_to.__properties__}
            # Look at adjacent nodes from incoming egdes. Only store them if they are context nodes. Other relations that are incoming are handled by the respective adjacent node in the relation_to attribute.
            for adjacent in pushout_node.relation_from.all():
                if adjacent.timestamp != pushout_node.timestamp:
                    continue
                relation_from = pushout_node.relation_from.relationship(adjacent)
                # If related node has an equivalence, it is a context node.
                if adjacent.equivalent_to.all():
                    self.topological_patch_pattern[timestamp][pushout_node.element_id]["context_from"][adjacent.element_id] = {"path": self.node_ids_to_unique_paths_mapping[timestamp][adjacent.element_id], "properties": relation_from.__properties__}


    def load_patch_from_file(self, path_topo, path_sema):
        """
        To apply a patch to a model, the previously created json-based patch files have to be loaded.
        """
        with open(path_sema, "r") as f:
            self.semantic_patch_pattern = json.load(f)
        with open(path_topo, "r") as f:
            self.topological_patch_pattern = json.load(f)



    ######################
    ### Main Functions ###
    ######################

    def create_patch(self, project_id: str, timestamp_init:str, timestamp_updt:str):
        """
        Use the two models that have been diffed and create a semanic and a topological patch.
        """

        self.node_ids_to_unique_paths_mapping = {timestamp_init: {}, timestamp_updt: {}}
        self.init_side_node_ids_to_unique_paths_mapping = {timestamp_init: {}, timestamp_updt: {}}
        self.topological_patch_pattern = {timestamp_init: {}, timestamp_updt: {}}
        self.semantic_patch_pattern = {}
        self.nodes_to_delete = []

        # Get all Primary and Connection Nodes.
        prim_and_con_init = list(PrimaryNode.nodes.filter(timestamp=timestamp_init)) + list(ConnectionNode.nodes.filter(timestamp=timestamp_init))
        prim_and_con_updt = list(PrimaryNode.nodes.filter(timestamp=timestamp_updt)) + list(ConnectionNode.nodes.filter(timestamp=timestamp_updt))

        # Create unique paths starting from all Primary and all Connection nodes.
        for node in prim_and_con_init:
            # One mapping is just for the init (existing) side to find nodes to delete. These unique paths can traverse over init pushout nodes that are not present in the updt model.
            self.create_init_side_unique_path_mappings(node, timestamp_init)
            if node.equivalent_to.all():
                # This mapping is the universal one for both models to identify context nodes.
                self.create_unique_path_mappings(node, timestamp_init)
        for node in prim_and_con_updt:
            self.create_init_side_unique_path_mappings(node, timestamp_updt)
            if node.equivalent_to.all():
                self.create_unique_path_mappings(node, timestamp_updt)

        # Collect all pushout nodes and equivalent nodes using the equivalent_to relations from the diff.
        pushout_nodes_init = Node.nodes.filter(timestamp=timestamp_init).has(equivalent_to=False).all()
        pushout_nodes_updt = Node.nodes.filter(timestamp=timestamp_updt).has(equivalent_to=False).all()
        equivalent_nodes_init = Node.nodes.filter(timestamp=timestamp_init).has(equivalent_to=True).all()

        self.create_semantic_patch_pattern(equivalent_nodes_init, timestamp_init, timestamp_updt)
        self.create_topological_patch_pattern(pushout_nodes_init, timestamp_init)
        self.create_topological_patch_pattern(pushout_nodes_updt, timestamp_updt)

        # Write out the patches.
        os.makedirs("patch_data", exist_ok=True)
        with open(f"patch_data/Patch_Topo_{project_id}_{timestamp_init}_{timestamp_updt}.json", "w") as f:
            json.dump(self.topological_patch_pattern, f, indent=4)
        with open(f"patch_data/Patch_Sema_{project_id}_{timestamp_init}_{timestamp_updt}.json", "w") as f:
            json.dump(self.semantic_patch_pattern, f, indent=4)

    
    def apply_patch(self, project_id: str, timestamp_init: str, timestamp_updt: str):

        self.node_ids_to_unique_paths_mapping = {timestamp_init: {}, timestamp_updt: {}}
        self.init_side_node_ids_to_unique_paths_mapping = {timestamp_init: {}, timestamp_updt: {}}
        self.topological_patch_pattern = {timestamp_init: {}, timestamp_updt: {}}
        self.semantic_patch_pattern = {}
        self.nodes_to_delete = []

        try:
            path_topo = f"./patch_data/Patch_Topo_{project_id}_{timestamp_init}_{timestamp_updt}.json"
            path_sema = f"./patch_data/Patch_Sema_{project_id}_{timestamp_init}_{timestamp_updt}.json"
            self.load_patch_from_file(path_topo, path_sema)
        except:
            path_topo = f"./patch_data/Patch_Topo_{project_id}_{timestamp_updt}_{timestamp_init}.json"
            path_sema = f"./patch_data/Patch_Sema_{project_id}_{timestamp_updt}_{timestamp_init}.json"
            self.load_patch_from_file(path_topo, path_sema)

        # Deletion of init
        # Get all Primary and Connection nodes and create unique paths for all reachable nodes. These are, again, the identifiers.
        prim_and_con_init = list(PrimaryNode.nodes.filter(timestamp=timestamp_init)) + list(ConnectionNode.nodes.filter(timestamp=timestamp_init))
        for node in prim_and_con_init:
            self.create_init_side_unique_path_mappings(node, timestamp_init)
        # Removal of init pushout pattern.
        # Mark any unreachable nodes for deletion. These nodes can not be updated and so must be fully replaced.
        # Only nodes of the init version are considered; other projects/versions in the DB stay untouched.
        for node in Node.nodes.filter(timestamp=timestamp_init):
            if node.element_id not in self.init_side_node_ids_to_unique_paths_mapping[timestamp_init]:
                if node not in self.nodes_to_delete:
                    self.nodes_to_delete.append(node)

        # Iterate over the topological patches init side and mark any nodes with a unique path up for deletion.
        for key, pushout_node_ref in self.topological_patch_pattern[timestamp_init].items():
            if pushout_node_ref["path"]:
                pushout_node = self.find_node_from_unique_path(pushout_node_ref["path"], timestamp_init)
                if pushout_node not in self.nodes_to_delete:
                    self.nodes_to_delete.append(pushout_node)
        
        # Iterate over all nodes marked up for deletion (init pushout nodes). Detach them and remove them from the db.
        for node in self.nodes_to_delete:
            for adjacent in node.relation_from.all():
                rel_type = adjacent.relation_to.relationship(node).rel_type
                setattr(adjacent, rel_type, "$")
            node.relation_to.disconnect_all()
            node.relation_from.disconnect_all()
            node.delete()

        #Insertion of updt.
        # First iteration to create the nodes as they are listed in the patch.
        # Dicts to map patch_pattern node ids to actual DB nodes
        pushout_node_refs_updt = self.topological_patch_pattern[timestamp_updt]
        pushout_node_id_to_added_node_mapping = {}
        added_node_id_to_pushout_id_mapping = {}
        for key, pushout_node_ref in pushout_node_refs_updt.items():
            node_class = globals()[pushout_node_ref["node_type"]]
            node_obj = node_class(**pushout_node_ref["properties"])
            delattr(node_obj, "element_id_property")
            node_obj.save()
            pushout_node_id_to_added_node_mapping[pushout_node_ref["properties"]["element_id_property"]] = node_obj
            added_node_id_to_pushout_id_mapping[node_obj.element_id] = pushout_node_id_to_added_node_mapping[pushout_node_ref["properties"]["element_id_property"]]
        # Second iteration to connect the new updt nodes with one another and with the context
        for key_pushout, pushout_node_ref in pushout_node_refs_updt.items():
            pushout_node = pushout_node_id_to_added_node_mapping[key_pushout]
            if pushout_node_ref["relation_to"]:
                for key_relation, relation in pushout_node_ref["relation_to"].items():
                    related_node = pushout_node_id_to_added_node_mapping[key_relation]
                    pushout_node.relation_to.connect(related_node, {"rel_type": relation["properties"]["rel_type"], "list_index": relation["properties"]["list_index"]})
                    if hasattr(pushout_node, relation["properties"]["rel_type"]):
                        setattr(pushout_node, relation["properties"]["rel_type"], None)
                        pushout_node.save()
            if pushout_node_ref["context_to"]:
                for key_context_to, context_to in pushout_node_ref["context_to"].items():
                    context_node = self.find_node_from_unique_path(context_to["path"], timestamp_init)
                    pushout_node.relation_to.connect(context_node, {"rel_type": context_to["properties"]["rel_type"], "list_index": context_to["properties"]["list_index"]})
                    if hasattr(pushout_node, context_to["properties"]["rel_type"]):
                        setattr(pushout_node, context_to["properties"]["rel_type"], None)
                        pushout_node.save()
            if pushout_node_ref["context_from"]:
                for key_context_from, context_from in pushout_node_ref["context_from"].items():
                    context_node = self.find_node_from_unique_path(context_from["path"], timestamp_init)
                    context_node.relation_to.connect(pushout_node, {"rel_type": context_from["properties"]["rel_type"], "list_index": context_from["properties"]["list_index"]})
                    if hasattr(context_node, context_from["properties"]["rel_type"]):
                        setattr(context_node, context_from["properties"]["rel_type"], None)
                        context_node.save()

                    
        # Update the existing nodes based on the semantic patch, i.e., the attribute updates.
        for unique_path in self.semantic_patch_pattern.keys():
            node = self.find_node_from_unique_path(unique_path=unique_path, timestamp=timestamp_init)
            for property_key in self.semantic_patch_pattern[unique_path].keys():
                property_value_init = self.semantic_patch_pattern[unique_path][property_key][timestamp_init]
                property_value_updt = self.semantic_patch_pattern[unique_path][property_key][timestamp_updt]
                if isinstance(property_value_updt, dict):
                    if "path" in property_value_updt.keys():
                        adjacent = self.find_node_from_unique_path(property_value_updt["path"], timestamp_init)
                        node.relation_to.connect(adjacent, {"rel_type": property_value_updt["rel_type"], "list_index": property_value_updt["list_index"]})
                        setattr(node, property_key, None)
                elif isinstance(property_value_updt, dict):
                    if "path" in property_value_init.keys():
                        adjacent = self.find_node_from_unique_path(property_value_init["path"], timestamp_init)
                        node.relation_to.disconnect(adjacent)
                        setattr(node, property_key, "$")
                else:
                    setattr(node, property_key, self.semantic_patch_pattern[unique_path][property_key][timestamp_updt])
                node.save()

        # Make all timestamps updt to have the whole model be that version.
        # Newly inserted nodes already carry timestamp_updt; restamp the remaining init nodes in one query
        # (instead of one OGM save per node) and leave other projects/versions in the DB untouched.
        db.cypher_query("MATCH (n:Node {timestamp: $ts_init}) SET n.timestamp = $ts_updt",
                        {"ts_init": timestamp_init, "ts_updt": timestamp_updt})