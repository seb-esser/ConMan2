from version_timeline.VersionTimeline import VersionTimeline
from command_line_interface.Backend import get_backend


def commit(project_id: str, branch: str, message: str=""):

    version_timeline = VersionTimeline()
    backend = get_backend()

    added_timestamps = backend.timestamps(project_id)
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

    print(f"Creating increment for project {project_id} on branch {branch} between timestamps {timestamp_init} and {timestamp_updt} (backend: {backend.name}).")
    increment = backend.create_increment(project_id, timestamp_init, timestamp_updt)

    version_timeline = VersionTimeline()
    version_timeline.add_commit_to_timeline(project_id=project_id, branch=branch, timestamp_init=timestamp_init,
                                            timestamp_updt=timestamp_updt, message=message, increment=increment)

    # Remove init model.
    backend.drop(timestamp_init)
