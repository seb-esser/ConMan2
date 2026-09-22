from graph_diff.GraphDiff import GraphDiff
from graph_patch.GraphPatch import GraphPatch
from neo4j_core.neo4j_connection import Neo4jConnection
from version_timeline.VersionTimeline import VersionTimeline
from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface

def commit(project_id: str, branch: str, message: str="", graph_provider: str="neo4j"):

    version_timeline = VersionTimeline()
    if graph_provider == "neo4j":
        Neo4jConnection(username="neo4j", password="password", hostname="localhost", port=7687)

    added_timestamps = IfcGraphInterface.get_timestamp_from_project_id(project_id, graph_provider=graph_provider)
    if len(added_timestamps) == 0:
        raise Exception(f"No graph models found for project {project_id}. Please add a graph model first.")
    elif len(added_timestamps) == 1:
        if not version_timeline.project_is_tracked(project_id):
            version_timeline.add_project(project_id=project_id, timestamp=added_timestamps[0], message=message)
            print(f"Added project {project_id} to timeline.")
        else:
            raise Exception(f"Only one graph model found for project {project_id}, but project is already tracked. Please add a second graph model to create a commit.")
        return
    elif len(added_timestamps) > 2:
        raise Exception(f"More than two graph models found for project {project_id}. Please ensure only two graph models exist for creating a commit.")
    else:
        if not version_timeline.project_is_tracked(project_id):
            raise Exception(f"Project {project_id} is untracked and 2 versions are added. Please commit one version of project {project_id} first.")
        latest_timestamp = version_timeline.get_latest_commit_on_branch(project_id, branch)
        if latest_timestamp in added_timestamps:
            added_timestamps.remove(latest_timestamp)
        else:
            raise Exception(f"2 model versions are added but the latest commit {latest_timestamp} is not added. No consecutive patch can be generated.")
        timestamp_init = latest_timestamp
        timestamp_updt = added_timestamps[0]

    print(f"Running diff for project {project_id} on branch {branch} between timestamps {timestamp_init} and {timestamp_updt}.")
    graph_diff = GraphDiff(graph_provider=graph_provider)
    graph_diff.run_diff(timestamp_init, timestamp_updt)

    print(f"Creating patch for project {project_id} on branch {branch} between timestamps {timestamp_init} and {timestamp_updt}.")
    graph_patch = GraphPatch(graph_provider=graph_provider)
    graph_patch.create_patch(project_id, timestamp_init, timestamp_updt)

    version_timeline = VersionTimeline()
    version_timeline.add_commit_to_timeline(project_id=project_id, branch=branch, timestamp_init=timestamp_init, timestamp_updt=timestamp_updt, message=message)

    ## Remove init model.
    if graph_provider == "neo4j":
        query = f"""
        MATCH (n)
        WHERE n.timestamp = '{timestamp_init}'
        DETACH DELETE n
        """
        Neo4jConnection().cypher_query(query)
    elif graph_provider == "networkx":
        pass