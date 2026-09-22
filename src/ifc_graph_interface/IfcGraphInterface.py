from neomodel import db
import ifcopenshell
import ifcopenshell.api.project

from networkX_core.networkx_connection import networkxConnection
from .neo4j_helper import Neo4J_Helper

import ast
import glob
from collections import defaultdict

from neo4j_core.neo4j_model import GenericNode, PrimaryNode, SecondaryNode, ConnectionNode, InlineNode


class IfcGraphInterface:

    # list of graph providers that are supported by the interface.
    # This can be used in the future to extend the interface to other graph databases or graph libraries.
    graph_providers = ("neo4j", "networkx")

    def __init__(self, graph_provider: str = "neo4j") -> None:
        """
        Initialize the IfcGraphInterface.

        Args:
            graph_provider (str, optional): The graph provider that sets the endpoint 
                where the graph representations are handled. Defaults to "neo4j".
        """
        if graph_provider not in self.graph_providers:
            raise ValueError(
                f"Graph provider '{graph_provider}' not supported. Available providers: {self.graph_providers}")
        self.graph_provider = graph_provider
        print("Selected provider: ", self.graph_provider)

    ########################
    ### Helper Functions ###
    ########################

    def __process_ifc_attributes(self, entity: ifcopenshell.entity_instance, timestamp: str, props_map: dict, relationships: list, related_nodes: set, inline_patterns: list):
        p21_id = f"#{entity.id()}"

        # Recursively handle IFC attributes to catch primitives to nested lists.
        def traverse(key, val, list_index=0):
            if isinstance(val, ifcopenshell.entity_instance):
                # Case where attribute is single relation to other entity.
                if val.id() == 0:
                    inline_patterns.append({
                        "props": {
                            "EntityType": val.is_a(),
                            "wrappedValue": val.wrappedValue,
                            "timestamp": timestamp
                        },
                        "relation": {
                            "rel_type": key,
                            "list_index": list_index,
                            "source_p21_id": p21_id
                        }
                    })
                else:
                    related_p21_id = f"#{val.id()}"
                    relationships.append({
                        "source_p21_id": p21_id,
                        "target_p21_id": related_p21_id,
                        "timestamp": timestamp,
                        "rel_type": key,
                        "list_index": list_index
                    })
                    related_nodes.add(related_p21_id)
            elif isinstance(val, (tuple, list)):
                # Case where attribute is a list.
                if any(isinstance(x, ifcopenshell.entity_instance) for x in val):
                    # Case where list of IFC entities.
                    for i, x in enumerate(val):
                        traverse(key, x, list_index=i)
                else:
                    # Case where list of primtitves.
                    props_map.setdefault(p21_id, {})[key] = str(val)
            elif val is None:
                # Case where attribute is not assigned.
                props_map.setdefault(p21_id, {})[key] = "$"
            else:
                # Case where value is primitive.
                props_map.setdefault(p21_id, {})[key] = val

        info = entity.get_info()
        for key, val in info.items():
            # Ignore any IDs or types as they are already saved in the node and must not be changed
            if key in ("GlobalId", "EntityType", "type", "p21_id", "id", "inline_id", "timestamp"):
                continue
            else:
                traverse(key, val)

    def __process_node_attribute(self, ifc_entity, key, val):
        """
        Process node attributes. These are the directly attached primtive node properties that are directly attached to a neo4j node.

        @param ifc_entity: An ifcopenshell model entity.
        @param key: The key of the node attribute.
        @param val: The attribute value. This can either be a primitive type, a string, or a stringified list of primitives.
        """
        # print(f"Processing {ifc_entity, key, val}")
        if val == "$":
            pass
        # Check if it is any primitive but a string. If so, leave it.
        elif not isinstance(val, str):
            # Store the processed attribute in the IFC entity.
            setattr(ifc_entity, key, val)
        # Check if it is a list of primitives that was parsed as a string. If so, leave it.
        # While neo4j allows lists, it does not allow for nested lists, so every list is stored as a string for consistency.
        elif not val.startswith("(") or not val.endswith(")"):
            # Store the processed attribute in the IFC entity.
            setattr(ifc_entity, key, val)
        # If it is a stringified list of primitives, evaluate it back into a Python list.
        else:
            val = tuple(ast.literal_eval(val))
            # Store the processed attribute in the IFC entity.
            setattr(ifc_entity, key, val)

    def __process_node_relation(self, model, ifc_entity, rel_type, related_nodes, id_mapping):
        """
        From the relations in neo4j, create entity attributes and inline attributes for every STEP IFC object.

        @param model: The parsed ifcopenshell IFC model.
        @param ifc_entity: The current IFC entity.
        @param rel_type: The name of the relation in neo4j which will become the attribute key in the STEP attribute.
        @param related_nodes: The list of nodes that are all connected via a relation with the rel_type name.
        @param id_mapping: A dictionary that maps the newly created STEP ids to the node ids.
        """
        # Create list for entities to then set as the attribute value.
        ents = []
        # Iterate over all nodes that are grouped under the rel_attribute in the dict. This means that initially, all these nodes were part of the same IFC attribute.
        for node, list_index in related_nodes:
            # Determine if this is an inline node
            is_inline = False            
           
            # Check if node is a neomodel instance (Neo4j)
            if isinstance(node, InlineNode):
                is_inline = True
            # Check if node is a dict from NetworkX with label attribute
            elif isinstance(node, dict) and node.get("label") == "InlineNode":
                is_inline = True
            
            if is_inline:
                if self.graph_provider == "neo4j":
                    ent = model.create_entity(node.EntityType)
                    # WrappedValue is the actual input data of inline entities like "(6,5,1)" in "IfcArcIndex(6,5,1)". Process this like any other non-entity attribute.
                    self.__process_node_attribute(ent, "wrappedValue", node.wrappedValue)

                elif self.graph_provider == "networkx":
                    # Create new entity for inline node
                    ent = model.create_entity(node.get("EntityType")) 
                    # WrappedValue is the actual input data of inline entities like "(6,5,1)" in "IfcArcIndex(6,5,1)". Process this like any other non-entity attribute.
                    self.__process_node_attribute(ent, "wrappedValue", node.get("wrappedValue"))
                ents.append((ent, list_index))
            else:
                # If entity is a real STEP entity, get the existing IFC entity and append that to the list.
                # Handle both neomodel node (has element_id) and NetworkX node dict (has p21_id)
                if hasattr(node, 'element_id'):
                    node_id = node.element_id
                elif isinstance(node, dict) and "p21_id" in node:
                    node_id = node["p21_id"]
                else:
                    node_id = node.get("p21_id")
                
                if node_id and node_id in id_mapping:
                    ent = model.by_id(id_mapping[node_id])
                    ents.append((ent, list_index))

        # Every attribute value is a list, for some attributes this datatype is correct. Others need single values.
        if len(ents) <= 1:
            # Required try block because if a list has only 1 entry, it might have to be passed as a list with one entry, or it may have to be passed as a single entry.
            try:
                setattr(ifc_entity, rel_type, ents[0][0])
            except:
                setattr(ifc_entity, rel_type, [ents[0][0]])
        # If multiple entities in the list, set the list as attribute value.
        else:
            # Sort the entity list by the list index before setting as attribute. This rebuilds the same order.
            ents_sorted = sorted(ents, key=lambda x: x[1])
            ents_final = [ent[0] for ent in ents_sorted]
            setattr(ifc_entity, rel_type, ents_final)

        return model 

    ###########################
    ### Provider Connectors ###
    ###########################

    def __send_to_neo4j(self, timestamp, batch_size, model, primary_nodes, connection_nodes, secondary_nodes):

        # Create Neo4J_Helper instance.
        neo4j_helper = Neo4J_Helper()      

        # Retrieve IFC entities that will be PrimaryNodes, same for ConnectionNodes.
        primary_entities = model.by_type("IfcObjectDefinition") + model.by_type("IfcPropertyDefinition")
        connection_entities = model.by_type("IfcRelationship")
        prim_conn_entities = primary_entities + connection_entities

        prim_conn_ids = {e.id() for e in prim_conn_entities}
        secondary_entities = [e for e in model if e.id() != 0 and e.id() not in prim_conn_ids]

        # Create a list of node dicts that can be used for batch creation with UNWIND.
        primary_nodes = [{
            "GlobalId": e.GlobalId,
            "EntityType": e.is_a(),
            "p21_id": f"#{e.id()}",
            "timestamp": timestamp
        } for e in primary_entities]

        connection_nodes = [{
            "GlobalId": e.GlobalId,
            "EntityType": e.is_a(),
            "p21_id": f"#{e.id()}",
            "timestamp": timestamp
        } for e in connection_entities]

        secondary_nodes = [{
            "EntityType": e.is_a(),
            "p21_id": f"#{e.id()}",
            "timestamp": timestamp
        } for e in secondary_entities]

        inline_patterns = []

        # Bulk creation queries.
        query_primary_nodes = """
        UNWIND $batch AS props
        CREATE (n:PrimaryNode:GenericNode:Node)
        SET n = props
        """

        query_connection_nodes = """
        UNWIND $batch AS props
        CREATE (n:ConnectionNode:GenericNode:Node)
        SET n = props
        """

        query_secondary_nodes = """
        UNWIND $batch AS props
        CREATE (n:SecondaryNode:GenericNode:Node)
        SET n = props
        """

        # Bulk creation.
        print(f"Creating {len(primary_nodes)} PrimaryNodes.")
        neo4j_helper.bulk_cypher_query(
            query_primary_nodes, primary_nodes, batch_size)

        print(f"Creating {len(connection_nodes)} ConnectionNodes.")
        neo4j_helper.bulk_cypher_query(
            query_connection_nodes, connection_nodes, batch_size)

        print(f"Creating {len(secondary_nodes)} SecondaryNodes")
        neo4j_helper.bulk_cypher_query(
            query_secondary_nodes, secondary_nodes, batch_size)

        # Process IFC attributes into collections for node attributes and relationships.
        print("Collecting attributes and relationships.")
        props_map = {}
        relationships = []
        related_nodes = set()
        inline_patterns = []

        for entity in model:
            self.__process_ifc_attributes(
                entity, timestamp, props_map, relationships, related_nodes, inline_patterns)

        # Bulk update primitive attributes on nodes.
        print(f"Updating attributes on {len(props_map)} nodes.")
        attributes_list = [{"p21_id": p21_id, "timestamp": timestamp,
                            "properties": properties} for p21_id, properties in props_map.items()]
        query_properties = """
        UNWIND $batch AS row
        MATCH (n:GenericNode {p21_id: row.p21_id, timestamp: row.timestamp})
        SET n += row.properties
        """
        neo4j_helper.bulk_cypher_query(
            query_properties, attributes_list, batch_size)

        # Bulk create relationships from IFC attributes.
        print(f"Creating {len(relationships)} relationships.")
        query_relationships = """
        UNWIND $batch AS r
        MATCH (a:GenericNode {p21_id: r.source_p21_id, timestamp: r.timestamp})
        MATCH (b:GenericNode {p21_id: r.target_p21_id, timestamp: r.timestamp})
        CREATE (a)-[:rel {rel_type: r.rel_type, list_index: r.list_index}]->(b)   
        """
        neo4j_helper.bulk_cypher_query(
            query_relationships, relationships, batch_size)

        # Bulk create InlinePatterns
        print(f"Creating {len(inline_patterns)} InlineNode patterns.")
        query_inline_patterns = """
        UNWIND $batch AS r
        MATCH (a:GenericNode {p21_id: r.relation.source_p21_id, timestamp: r.props.timestamp})
        CREATE (b:InlineNode:Node)
        SET b = r.props
        CREATE (a)-[:rel {rel_type: r.relation.rel_type, list_index: r.relation.list_index}]->(b)
        """
        neo4j_helper.bulk_cypher_query(
            query_inline_patterns, inline_patterns, batch_size)
        
        print("Perform node indexing based on timestamp and p21_id for faster lookup.")
        # Create indexes for faster lookup.
        db.cypher_query("CREATE INDEX generic_p21_ts IF NOT EXISTS FOR (n:GenericNode) ON (n.p21_id, n.timestamp)")
        db.cypher_query("CREATE INDEX generic_ts IF NOT EXISTS FOR (n:GenericNode) ON (n.timestamp)")
        # Wait until the indexes are online.
        db.cypher_query("CALL db.awaitIndexes()")
    

    def __send_to_nx(self, timestamp, batch_size, model, primary_nodes, connection_nodes, secondary_nodes):

        nx_interface = networkxConnection()
        # add node sceletons. Each node is identified by its p21_id and has a property dict with the other primitive attributes that are directly attached to the node

        print(f"Creating {len(primary_nodes)} PrimaryNodes.")
        primary_nodes_to_add = [
            (
                n["p21_id"],
                {**{k: v for k, v in n.items() if k != "p21_id"},
                 "timestamp": n["timestamp"], "label": "PrimaryNode"}
            )
            for n in primary_nodes
        ]
        nx_interface.graph.add_nodes_from(primary_nodes_to_add)

        print(f"Creating {len(connection_nodes)} ConnectionNodes.")
        connection_nodes_to_add = [
            (
                n["p21_id"],
                {**{k: v for k, v in n.items() if k != "p21_id"},
                 "timestamp": n["timestamp"], "label": "ConnectionNode"}
            )
            for n in connection_nodes
        ]
        nx_interface.graph.add_nodes_from(connection_nodes_to_add)

        print(f"Creating {len(secondary_nodes)} SecondaryNodes.")
        secondary_nodes_to_add = [
            (
                n["p21_id"],
                {**{k: v for k, v in n.items() if k != "p21_id"},
                 "timestamp": n["timestamp"], "label": "SecondaryNode"}
            )
            for n in secondary_nodes
        ]
        nx_interface.graph.add_nodes_from(secondary_nodes_to_add)

        print("Collecting attributes and relationships.")
        props_map = {}  # contains all additional node properties that go beyond this already parsed
        relationships = []  # contains all relationships between nodes that are derived from IFC attributes that reference other IFC entities. These are stored as edges in the graph with the rel_type as edge attribute. List attributes are stored as multiple edges with a list_index attribute to keep track of the order.
        related_nodes = set()  # contains all nodes that are related to other nodes via relationships. This is used to filter out the nodes that have no relations and can be stored as node attributes instead of separate nodes with relationships.
        inline_patterns = []  # contains all attributes that have to be stored as separate nodes because they are inline attributes with primitive values. These are stored as separate nodes with the attribute value and a relation to the entity node. The relation has the same name as the attribute in IFC and a list_index attribute in case the attribute is a list of inline attributes. The inline attribute nodes have a property "wrappedValue" that contains the actual primitive value of the inline attribute and an EntityType property that contains the IFC type of the inline attribute, e.g. IfcArcIndex.

        # perform extraction
        for entity in model:
            self.__process_ifc_attributes(
                entity, timestamp, props_map, relationships, related_nodes, inline_patterns)

        # after the traversal above we have a props_map that maps p21_ids to a
        # dict of primitive properties; push those back onto the nodes that were
        # just added. the graph uses the p21_id as the key and stores the
        # timestamp as a node attribute, so use both to make sure we update the
        # correct instance.
        print(
            f"Updating attributes on {len(props_map)} nodes in networkx graph.")
        for p21_id, properties in props_map.items():
            node_data = nx_interface.graph.nodes[p21_id]
            node_data.update(properties)

        # after the primitive properties have been pushed back onto the
        # nodes, create the edges that were collected while traversing the
        # model. every entry in *relationships* already contains the source
        # and target p21_ids, the rel‑type and the list index. we simply
        # attach those as edge attributes.
        print(f"Adding {len(relationships)} relationships to networkx graph.")
        for r in relationships:
            src = r["source_p21_id"]
            tgt = r["target_p21_id"]
            nx_interface.graph.add_edge(
                src,
                tgt,
                rel_type=r["rel_type"],
                list_index=r["list_index"]
            )

        print(f"Creating {len(inline_patterns)} inline attribute nodes.")
        for pat in inline_patterns:
            props = pat["props"]
            rel = pat["relation"]
            inline_id = f"{rel['source_p21_id']}_inline_{rel['rel_type']}_{rel['list_index']}"
            if not nx_interface.graph.has_node(inline_id):
                node_attrs = {
                    **props,
                    "p21_id": inline_id,
                    "label": "InlineNode",
                }
                nx_interface.graph.add_node(inline_id, **node_attrs)
                nx_interface.graph.add_edge(
                    rel["source_p21_id"],
                    inline_id,
                    rel_type=rel["rel_type"],
                    list_index=rel["list_index"],
                    timestamp=props.get("timestamp"),
                )

        nx_interface.save_graph(f"networkx_graph_{timestamp}.gpickle")

    def __retrieve_from_neo4j(self, timestamp: str, model: ifcopenshell.file): 
        """
        Populate an IFC model from a Neo4j graph snapshot.
        This private helper reads all `GenericNode` instances at a given
        `timestamp` from the database and reconstructs the corresponding
        IFC entities in the supplied `model`. The operation proceeds in
        two phases:
        1. **Entity creation** – iterate over every node matching the
           timestamp, create an IFC entity of the node's `EntityType`,
           copy primitive properties and maintain a mapping from the
           original Neo4j `element_id` to the new IFC entity id.
        2. **Relationship wiring** – traverse all outgoing relationships
           (`relation_to`) of the same node set, group related nodes by
           relationship type and list index, and use the mapping to set
           the appropriate attributes on the IFC entities. Inline lists
           of references are handled and attributes which are not present
           on the IFC class are ignored.
        Special cases such as attributes that should be skipped
        (e.g. `"TrueNorth"`) are filtered in the first phase.
        Parameters
        ----------
        ifc_path : str
            Path or identifier of the IFC source (not used directly in
            this method but part of the abstraction).
        timestamp : Any
            Timestamp value used to filter `GenericNode` instances in Neo4j.
        model : ifcopenshell.file
            An open IFC model into which entities and relationships will be
            created.
        Returns
        -------
        ifcopenshell.file
            The same `model` instance with new entities and relationships
            inserted according to the graph data.
        Notes
        -----
        The caller is responsible for committing or exporting the model
        after this method returns. This method assumes that all nodes and
        relationships necessary to reconstruct the model at `timestamp`
        exist and that `GenericNode` and `relation_to` APIs behave as
        expected.
        """

        print("Creating IFC entities from nodes. ")
        # Dictionary to map newly created IFC entities to their source node ids.
        id_mapping = {}

        # Per method call, only one IFC file is created from the nodes. Therefore, filter all nodes with the timestamp of that IFC file.
        # First iteraton: Create IFC entities (STEP entities with p21 id) from all nodes that are not Inline Nodes
        print("Creating IFC entities from nodes. ")
        # Materialize the queryset once so we don't re-hit the database on subsequent iterations.
        all_nodes = list(GenericNode.nodes.filter(timestamp=timestamp))
        for node in all_nodes:
            ifc_entity = model.create_entity(node.EntityType)
            # Add node id and id of new IFC entity to mapping for later use
            id_mapping[node.element_id] = ifc_entity.id()

            # Iterate over all node attributes. These are only primitive attributes and can therefore be appended to the new IFC entity independently of what other entities already exist in the model.
            for key, val in node.__properties__.items():
                # Check if the ifc entity has an attribute with the name of the node attribute. Make sure e.g. node id or p21_id is ignored.
                if key in ["TrueNorth"]:  # Add other edge cases to list.
                    continue
                if hasattr(ifc_entity, key):
                    # Call function that handles primitives or stringified (nested) list of primitives.
                    self.__process_node_attribute(ifc_entity, key, val)

        # Load all relationships for the given timestamp in a single query
        query = """
        MATCH (a:GenericNode {timestamp: $timestamp})-[r:rel]->(b:Node)
        RETURN a, b, r.rel_type AS rel_type, r.list_index AS list_index
        """
        results, _ = db.cypher_query(query, {"timestamp": timestamp}, resolve_objects=True)

        # Build an in-memory mapping from source node -> list of (related_node, list_index, rel_type)
        relationships_by_source = defaultdict(list)
        for source_node, target_node, rel_type, list_index in results:
            relationships_by_source[source_node.element_id].append((target_node, list_index, rel_type))

        print(f"Found {len(results)} relationships. ")

        print("Creating relationships between entities. ")
        # Second iteration: Go over all node relations (either to existing Step entities in the model or to inline attributes that will be created).
        for node in all_nodes:
            # Find ifc entity for current neo4j graph using the dictionary.
            ifc_entity = model.by_id(id_mapping[node.element_id])
            # Create a dictionary to collect all related entities. This is important, because one entity attribute may be a list of entity references. So first group all nodes by their rel_type.
            relations_dict = {}

            # Iterate over all related nodes, using the pre-fetched relationships
            for related_node, list_index, rel_type in relationships_by_source.get(node.element_id, []):
                # Check if IFC entity has an attribute with the name of the rel_type
                if hasattr(ifc_entity, rel_type):
                    # Rel type already exists in dict? Append node to its value that is a list.
                    if rel_type in relations_dict:
                        relations_dict[rel_type].append([related_node, list_index])
                    # Rel type appears for the first time? Create new entry for that attribute in the dict.
                    else:
                        relations_dict[rel_type] = [[related_node, list_index]]

            # Iterate over the dictionary and process the lists of related nodes
            for rel_type, related_nodes in relations_dict.items():
                model = self.__process_node_relation(model, ifc_entity, rel_type, related_nodes, id_mapping)

        # finished iterating all nodes, return assembled model
        return model

    def __retrieve_from_nx(self, timestamp: str, model: ifcopenshell.file):
        nx_interface = networkxConnection()
        nx_interface.load_graph(f"networkx_graph_{timestamp}.gpickle")
        
        # Dictionary to map newly created IFC entities to their source node ids.
        id_mapping = {}
        
        # Phase 1: Create IFC entities from nodes
        print("Creating IFC entities from nodes.")
        for node_id, node_data in nx_interface.graph.nodes(data=True):
            if node_data.get("timestamp") != timestamp:
                continue
            
            entity_type = node_data.get("EntityType")
            if not entity_type:
                continue
            
            ifc_entity = model.create_entity(entity_type)
            id_mapping[node_id] = ifc_entity.id()
            
            # Process node attributes
            for key, val in node_data.items():
                if key in ["TrueNorth", "timestamp", "label", "EntityType", "p21_id"]:
                    continue
                if hasattr(ifc_entity, key):
                    self.__process_node_attribute(ifc_entity, key, val)
        
        # Phase 2: Process relationships between entities
        print("Creating relationships between entities.")
        for node_id, node_data in nx_interface.graph.nodes(data=True):
            if node_data.get("timestamp") != timestamp:
                continue
            # exclude inlineNodes as they have been already reconstructed
            elif node_data.get("label") == "InlineNode":
                continue
            
            ifc_entity = model.by_id(id_mapping[node_id])
            relations_dict = {}
            
            # Collect all outgoing edges for this node
            for target_node_id in nx_interface.graph.successors(node_id):
                target_data = nx_interface.graph.nodes[target_node_id]
                edge_data = nx_interface.graph.get_edge_data(node_id, target_node_id)
                target_data["p21_id"] = target_node_id  # Ensure target node has p21_id for later processing
                
                # here, extracting only the first edge is problematic if there are multiple edges between the same nodes with different rel_types. In that case, we would need to iterate over all edges and group them by rel_type and list_index, similar to how we do in Neo4j. For now, we assume there is only one edge between any two nodes.
                rel_type = edge_data[0].get("rel_type")
                list_index = edge_data[0].get("list_index", 0)
                
                if hasattr(ifc_entity, rel_type):
                    if rel_type not in relations_dict:
                        relations_dict[rel_type] = []
                    relations_dict[rel_type].append([target_data, list_index])
            
            # Process each relationship type
            for rel_type, related_nodes in relations_dict.items():
                model = self.__process_node_relation(model, ifc_entity, rel_type, related_nodes, id_mapping)

        # define return 
        return model    

    ######################
    ### Main Functions ###
    ######################

    def ifc_2_graph(self, ifc_path: str, timestamp: str, batch_size: int = 20000):

        # Load IFC model.
        print("Loading IFC model.")
        model = ifcopenshell.open(ifc_path)

        # Retrieve IFC entities that will be PrimaryNodes, same for ConnectionNodes.
        primary_entities = model.by_type(
            "IfcObjectDefinition") + model.by_type("IfcPropertyDefinition")
        connection_entities = model.by_type("IfcRelationship")
        prim_conn_entities = primary_entities + connection_entities

        prim_conn_ids = {e.id() for e in prim_conn_entities}
        secondary_entities = [
            e for e in model if e.id() != 0 and e.id() not in prim_conn_ids]

        # Create a list of node dicts that can be used for batch creation with UNWIND.
        primary_nodes = [{
            "GlobalId": e.GlobalId,
            "EntityType": e.is_a(),
            "p21_id": f"#{e.id()}",
            "timestamp": timestamp
        } for e in primary_entities]

        connection_nodes = [{
            "GlobalId": e.GlobalId,
            "EntityType": e.is_a(),
            "p21_id": f"#{e.id()}",
            "timestamp": timestamp
        } for e in connection_entities]

        secondary_nodes = [{
            "EntityType": e.is_a(),
            "p21_id": f"#{e.id()}",
            "timestamp": timestamp
        } for e in secondary_entities]

        # decide on provider and send data to that provider.

        if self.graph_provider == "neo4j":
            self.__send_to_neo4j(timestamp, batch_size, model,
                                 primary_nodes, connection_nodes, secondary_nodes)
        elif self.graph_provider == "networkx":
            self.__send_to_nx(timestamp, batch_size, model,
                              primary_nodes, connection_nodes, secondary_nodes)

        print("Finished IFC parsing.")

    def graph_2_ifc(self, ifc_path: str, timestamp: str):
        """
        Generate an IFC file from a graph.

        @param ifc_path: Target path of the generated IFC file.
        @param timestamp: ID to keep track of what nodes in the graph belong to the same origin IFC file.
        """
        # ToDo: set IFC version and MVD
        model = ifcopenshell.api.project.create_file("IFC4")
        # add a marker in the IFC header so that the file can be traced back to this application.  
        model.header.file_name.originating_system = "ConMan2"
        # ToDo: fetch the operator's name from the system and add it to the model header. 
        
        if self.graph_provider == "neo4j":
            model = self.__retrieve_from_neo4j(timestamp, model)
        elif self.graph_provider == "networkx":
            model = self.__retrieve_from_nx(timestamp, model)
                
        # Save the IFC model to file.
        print("Write model to file. ")
        model.write(ifc_path)
        print("Finished IFC file generation. ")


    @staticmethod
    def get_project_id_from_timestamp(timestamp: str):
        try:
            project = PrimaryNode.nodes.get(
                EntityType="IfcProject", timestamp=timestamp)
            return project.GlobalId
        except Exception as e:
            print(
                f"Error retrieving project ID for timestamp {timestamp}: {e}")
            return None

    @staticmethod
    def get_project_id_from_ifc_path(ifc_path: str):
        try:
            model = ifcopenshell.open(ifc_path)
            project = model.by_type("IfcProject")[0]
            return project.GlobalId
        except Exception as e:
            print(f"Error retrieving project ID from IFC file {ifc_path}: {e}")
            return None

    @staticmethod
    def get_timestamp_from_project_id(project_id: str, graph_provider: str = "neo4j"):
        if graph_provider == "neo4j":
            try:
                project = PrimaryNode.nodes.filter(
                    GlobalId=project_id, EntityType="IfcProject").all()
                return [p.timestamp for p in project]
            except Exception as e:
                print(
                    f"Error retrieving latest timestamp for project ID {project_id}: {e}")
                return None
        elif graph_provider == "networkx":
            try:
                timestamps = []
                for filepath in glob.glob("networkx_graph_*.gpickle"):
                    nx_interface = networkxConnection()
                    nx_interface.load_graph(filepath)
                    for _, node_data in nx_interface.graph.nodes(data=True):
                        if node_data.get("EntityType") == "IfcProject" and node_data.get("GlobalId") == project_id:
                            timestamps.append(node_data.get("timestamp"))
                            break
                return timestamps
            except Exception as e:
                print(
                    f"Error retrieving latest timestamp for project ID {project_id}: {e}")
                return None
