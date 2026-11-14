from neo4j_core.neo4j_model import Node, GenericNode, PrimaryNode, ConnectionNode, SecondaryNode, InlineNode, RelProperties
from data_handler.DataHandler import DataHandler

from neomodel import Traversal #???
import json

# Query for all nodes without equivalence
# match (n:Node) where not (n)-[:equivalent_to]-(:Node) return n

class GraphDiff:

    ########################
    ### Helper Functions ###
    ########################

    def create_equivalence_relations_primary(self, equiv_node_init, equiv_node_updt):
        """
        Traverse the two parsed models starting from PrimaryNodes and find equivalent nodes. Create equilavent_to relations between them.
        """
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
                    and not child_init.equivalent_to.filter(timestamp=child_updt.timestamp)
                    and not child_updt.equivalent_to.filter(timestamp=child_init.timestamp)
                ):
                    # Create equivalent_to edge and recursively run the funciton.
                    child_init.equivalent_to.connect(child_updt)
                    self.create_equivalence_relations_primary(child_init, child_updt)


    def create_equivalence_relations_connection(self, connection_node_init, connection_node_updt):
        """
        Traverse the two parsed models starting from ConnectionNodes and find equivalent nodes. Create equilavent_to relations between them.
        """
        # Check if a globalid exists on the nodes and if they are the same.
        if hasattr(connection_node_init, 'GlobalId'):
            if hasattr(connection_node_updt, 'GlobalId'):
                if connection_node_init.GlobalId == connection_node_updt.GlobalId:
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
            self.unique_paths[connection_node_init.element_id] = {"connection_node": connection_node_init.GlobalId}
            self.unique_paths[connection_node_updt.element_id] = {"connection_node": connection_node_updt.GlobalId}           


    ######################
    ### Main Functions ###
    ######################

    def run_diff(self, timestamp_init:str, timestamp_updt:str):
        """
        Recursively compares nodes on graph for equivalence and generates equivalent_to relations between them.
        """
        project_init = Node.nodes.get(EntityType="IfcProject", timestamp=timestamp_init)
        project_updt = Node.nodes.get(EntityType="IfcProject", timestamp=timestamp_updt)
        #Looks directed but is undirectedly treated.
        project_init.equivalent_to.connect(project_updt)

        # For PrimaryNodes, find partners using the globalid, then run the recursive function.
        for primary_node_init in PrimaryNode.nodes.filter(timestamp=timestamp_init):
            try:
                primary_node_updt = PrimaryNode.nodes.get(GlobalId=primary_node_init.GlobalId, timestamp=timestamp_updt)
            except:
                continue
            primary_node_init.equivalent_to.connect(primary_node_updt)
            self.create_equivalence_relations_primary(primary_node_init, primary_node_updt)
        # For ConnectionNodes, find all in both models, then run the Intersection over Union function.
        for connection_node_init in ConnectionNode.nodes.filter(timestamp=timestamp_init):
            for connection_node_updt in ConnectionNode.nodes.filter(timestamp=timestamp_updt):
                self.create_equivalence_relations_connection(connection_node_init, connection_node_updt)