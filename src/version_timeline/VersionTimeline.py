from datetime import datetime
import os
import json
from collections import deque, defaultdict

class VersionTimeline:

    # File interation to store the timeline data.

    def __init__(self):
        self.load()
        self.save()

    def load(self):
        os.makedirs("./timeline_data", exist_ok=True)
        if os.path.exists("./timeline_data/timeline.json"):
            with open("./timeline_data/timeline.json", "r") as f:
                self.timeline = json.load(f)
        else:
            self.timeline = {}

    def save(self):
        os.makedirs("./timeline_data", exist_ok=True)
        with open("./timeline_data/timeline.json", "w") as f:
            json.dump(self.timeline, f, indent=4)

    def project_is_tracked(self, project_id: str) -> bool:
        self.load()
        if self.timeline.get(project_id) is None:
            return False
        else:
            return True
        
    def format_commit(self, timestamp_init: str, message: str="", increment: str=None):
        parents = [] if timestamp_init is None else [timestamp_init]
        commit = {"message": message, "parents": parents}
        if increment is not None:
            # How the increment from the parent to this commit is stored ("conman" or "rdf-patch").
            commit["increment"] = increment
        return commit

    def add_project(self, project_id: str, timestamp: str, message: str=""):
        self.load()
        if project_id not in self.timeline:
            self.timeline[project_id] = {
                "branches": {
                    "main": timestamp
                },
                "commits": {
                    timestamp: self.format_commit(None, message)
                }
            }
            self.save()
        else:
            raise Exception(f"Project {project_id} already exists in timeline.")
            

    def add_commit_to_timeline(self, project_id: str, branch: str, timestamp_init: str, timestamp_updt: str, message: str="", increment: str="conman"):
        self.load()
        self.timeline[project_id]["branches"][branch] = timestamp_updt
        self.timeline[project_id]["commits"][timestamp_updt] = self.format_commit(timestamp_init, message, increment)
        self.save()

    def get_latest_commit_on_branch(self, project_id: str, branch: str):
        self.load()
        if self.timeline.get(project_id) is None or self.timeline[project_id]["branches"].get(branch) is None:
            raise Exception(f"Project {project_id} or branch {branch} does not exist in timeline.")
        else:
            return self.timeline[project_id]["branches"][branch]
        
        
    def branch(self, project_id: str, branch_name: str, backend=None):
        self.load()
        if backend is None:
            from command_line_interface.Backend import get_backend
            backend = get_backend()
        root_timestamp = backend.timestamps(project_id)
        if branch_name in self.timeline[project_id]["branches"] or len(root_timestamp) != 1:
            raise Exception(f"Branch {branch_name} already exists in project {project_id} or there isn't exactly 1 added version of the project in the DB.")
        self.timeline[project_id]["branches"][branch_name] = root_timestamp[0]
        self.save()

    def increment_between(self, project_id: str, timestamp_a: str, timestamp_b: str) -> str:
        """Increment type of the timeline edge a-b (stored on the child commit; default 'conman')."""
        commits = self.timeline[project_id]["commits"]
        child = timestamp_b if timestamp_a in commits.get(timestamp_b, {}).get("parents", []) else timestamp_a
        return commits.get(child, {}).get("increment", "conman")

    def checkout(self, project_id: str, target_branch: str, target_timestamp: str, backend=None) -> list[str]:
        """
        Return a list of timestamps [start, ..., target] to move from the single
        model currently in DB to target_timestamp on target_branch.
        Uses shortest path on the undirected commit graph (parents <-> children).
        """
        self.load()

        if backend is None:
            from command_line_interface.Backend import get_backend
            backend = get_backend()
        # start timestamp = the one currently present in DB
        current = backend.timestamps(project_id)
        if not current or len(current) != 1:
            raise Exception("Exactly one model version must be present in the DB to plan checkout.")
        start_ts = str(current[0])

        proj = self.timeline.get(project_id)
        if not proj:
            raise Exception(f"Project {project_id} not found in timeline.")

        commits = proj.get("commits", {})
        branches = proj.get("branches", {})

        if target_branch not in branches:
            raise Exception(f"Branch {target_branch} not found.")
        # trust the provided target_timestamp; optionally validate it is on the branch head path
        if target_timestamp not in commits:
            raise Exception(f"Target timestamp {target_timestamp} not found in commits.")

        # build undirected adjacency from parents lists
        adj = defaultdict(set)
        for child, meta in commits.items():
            for p in meta.get("parents", []):
                adj[child].add(p)
                adj[p].add(child)

        # ensure nodes exist even if isolated
        adj.setdefault(start_ts, set())
        adj.setdefault(target_timestamp, set())

        if start_ts == target_timestamp:
            return [start_ts]

        # BFS to find a shortest path (fewest edges)
        prev = {start_ts: None}
        q = deque([start_ts])
        found = False
        while q and not found:
            n = q.popleft()
            for nb in adj[n]:
                if nb in prev:
                    continue
                prev[nb] = n
                if nb == target_timestamp:
                    found = True
                    break
                q.append(nb)

        if not found:
            raise Exception(f"No path from {start_ts} to {target_timestamp} in timeline.")

        # reconstruct path start -> target
        path = [target_timestamp]
        while prev[path[-1]] is not None:
            path.append(prev[path[-1]])
        path.reverse()
        print(f"Checkout path: {path}")
        patches = []
        for i in range(len(path)-1):
            ts_init = path[i]
            ts_updt = path[i+1]
            patches.append((ts_init, ts_updt))
        print(f"Checkout patches: {patches}")
        for ts_init, ts_updt in patches:
            increment = self.increment_between(project_id, ts_init, ts_updt)
            print(f"Applying {increment} increment from {ts_init} to {ts_updt} (backend: {backend.name}).")
            backend.apply_increment(project_id, ts_init, ts_updt, increment)
        return path

    @staticmethod
    def create_timestamp():
        timestamp = f"ts{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return timestamp