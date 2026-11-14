from neo4j_core.neo4j_connection import Neo4jConnection
import os

def nuke(yes: bool=False):

    Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    if not yes:
        answer = input("\033[91mWARNING: This will delete all added data in the database, delete the timeline, and delete all patch files.\033[0m\nDo you want to continue? (y/n): ")
        if answer.lower() != 'y':
            print("Nuke operation aborted.")
            return
        
    print("Nuking the database...")
    
    # remove timeline
    timeline_file = 'timeline_data/timeline.json'
    if os.path.exists(timeline_file):
        os.remove(timeline_file)

    # remove patch files
    patch_dir = "patch_data"
    for filename in (os.listdir(patch_dir) if os.path.isdir(patch_dir) else []):
        file_path = os.path.join(patch_dir, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)

    # Direct CYPHER query to delete all nodes and relationships in the db.
    query = f"""
    MATCH (n)
    DETACH DELETE n
    """
    Neo4jConnection().cypher_query(query)

    print(f"Database has been nuked. Neo4J is emptied, patch files and version timeline are removed.")