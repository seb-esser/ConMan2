from version_timeline.VersionTimeline import VersionTimeline
from command_line_interface.Backend import get_backend


def branch(project_id: str, branch_name: str):

    VersionTimeline().branch(project_id, branch_name, backend=get_backend())
