from graph_diff.GraphDiff import GraphDiff
from graph_patch.GraphPatch import GraphPatch
from neo4j_core.neo4j_connection import Neo4jConnection
from version_timeline.VersionTimeline import VersionTimeline
from cli_config import ConMan2Config as cfgmod
from command_line_interface.ModelFormats import root_entity_type

def debugging_commit(project_id: str, timestamp_init: str, timestamp_updt: str):

    if cfgmod.get("graph_backend") != "neo4j":
        raise Exception("debugging_add/debugging_commit keep equivalence edges in the database for inspection and "
                        "require graph_backend = neo4j (conman2.py config set graph_backend neo4j).")
    # version_timeline = VersionTimeline()
    Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    graph_diff = GraphDiff()
    graph_diff.run_diff(timestamp_init, timestamp_updt, root_entity_type=root_entity_type(project_id))

    print(f"Diff created between models of project {project_id} with timestamps {timestamp_init} and {timestamp_updt}.")

    # print(f"Creating patch for project {project_id} on branch {branch} between timestamps {timestamp_init} and {timestamp_updt}.")
    # graph_patch = GraphPatch(timestamp_init, timestamp_updt)
    # graph_patch.create_patch(project_id, timestamp_init, timestamp_updt)

    # version_timeline = VersionTimeline()
    # version_timeline.add_commit_to_timeline(project_id=project_id, branch=branch, timestamp_init=timestamp_init, timestamp_updt=timestamp_updt, message=message)

    # if remove_init_model:
    #     ## Remove init model.
    #     query = f"""
    #     MATCH (n)
    #     WHERE n.timestamp = '{timestamp_init}'
    #     DETACH DELETE n
    #     """
    #     Neo4jConnection().cypher_query(query)
