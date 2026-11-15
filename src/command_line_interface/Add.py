from version_timeline.VersionTimeline import VersionTimeline
from command_line_interface.Backend import get_backend, project_id_of_file


def add(model_path: str, timestamp: str, project_id: str = None):

    backend = get_backend()
    project_id = project_id_of_file(model_path, project_id)
    timestamps = backend.timestamps(project_id)
    if len(timestamps) > 1:
        raise Exception(f"Error: 2 or more timestamps for project ID {project_id} already exist in the {backend.name} backend.")
    if not timestamp:
        timestamp = VersionTimeline.create_timestamp()
    print(f"Adding files from path {model_path} with timestamp {timestamp}. Project: {project_id} (backend: {backend.name})")
    backend.add(model_path, timestamp, project_id)
    return timestamp
