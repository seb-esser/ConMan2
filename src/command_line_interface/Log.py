from version_timeline.VersionTimeline import VersionTimeline
import json


def log_timeline(project_id: str):
    timeline = VersionTimeline().timeline
    if project_id not in timeline:
        raise Exception(f"Project {project_id} is not tracked. Tracked projects: {', '.join(timeline) or '-'}")
    print(json.dumps(timeline[project_id], indent=4))
