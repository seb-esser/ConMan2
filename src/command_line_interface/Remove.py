from neo4j_core.neo4j_connection import Neo4jConnection

def remove(timestamp: str, graph_provider: str="neo4j"):

    if graph_provider == "neo4j":
        Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

        # Direct CYPHER query to delete all nodes and relationships with the given timestamp
        query = f"""
        MATCH (n)
        WHERE n.timestamp = '{timestamp}'
        DETACH DELETE n
        """
        Neo4jConnection().cypher_query(query)
        
    elif graph_provider == "networkx":
        pass