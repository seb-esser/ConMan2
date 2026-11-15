from version_timeline.VersionTimeline import VersionTimeline
from command_line_interface.Backend import get_backend


def checkout(project_id: str, branch_updt: str, timestamp_updt: str):

    VersionTimeline().checkout(project_id, branch_updt, timestamp_updt, backend=get_backend())
