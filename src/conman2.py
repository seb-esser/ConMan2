import argparse
import sys

from version_timeline.VersionTimeline import VersionTimeline

from command_line_interface.Add import add
from command_line_interface.Get import get
from command_line_interface.Commit import commit
from command_line_interface.Fetch import fetch
from command_line_interface.Pull import pull
from command_line_interface.Push import push
from command_line_interface.Remove import remove
from command_line_interface.Checkout import checkout
from command_line_interface.Reset import reset
from command_line_interface.Nuke import nuke
from command_line_interface.Branch import branch
from command_line_interface.Log import log_timeline
from command_line_interface.DebuggingAdd import debugging_add
from command_line_interface.DebuggingCommit import debugging_commit
from command_line_interface.Config import config_command
from cli_config import ConMan2Config

parser = argparse.ArgumentParser(description='ConMan2 CLI - Version Manager for BIM models (IFC), city models (GeoJSON) and RDF datasets. ')
parser.add_argument('--backend', choices=ConMan2Config.SCHEMA['graph_backend']['choices'], default=None,
                    help='OPTIONAL: graph backend for this call only (overrides the stored config).')
parser.add_argument('--increment', choices=ConMan2Config.SCHEMA['increment_representation']['choices'], default=None,
                    help='OPTIONAL: increment representation for this call only (overrides the stored config).')
subparsers = parser.add_subparsers(dest='command', help='Available commands.')

# "config" command parser
config_parser = subparsers.add_parser('config', help='Shows or changes the base configuration (graph backend, increment representation, ...). '
                                                     'Without arguments an interactive menu opens.')
config_parser.add_argument('action', nargs='?', choices=['menu', 'show', 'get', 'set', 'reset'], default=None,
                           help='menu | show | get <key> | set <key> <value> | reset. Omit for the interactive menu (in a terminal).')
config_parser.add_argument('key', nargs='?', default=None, help=f"Config key: {', '.join(ConMan2Config.SCHEMA)}")
config_parser.add_argument('value', nargs='?', default=None, help='New value (for set).')

# "add" command parser
add_parser = subparsers.add_parser('add', help='Adds a file (.ifc, .geojson, .json, .ttl, .nt, .n3, .rdf, .owl, .jsonld) to the graph backend. Function: IfcGraphInterface.ifc_2_graph() / GeoJsonGraphInterface.geojson_2_graph()')
add_parser.add_argument('-p', '--path', type=str, required=True, help='Path to the file to add.')
add_parser.add_argument('-t', '--timestamp', type=str, required=False, default="", help='OPTIONAL: Manually create a timestamp as a custom graph identifier.')
add_parser.add_argument('-i', '--project_id', type=str, required=False, default=None, help='OPTIONAL (GeoJSON/RDF): project id if the file does not define one (FeatureCollection "id" / owl:Ontology IRI).')

# "debugging add" command parser
debugging_add_parser = subparsers.add_parser('debugging_add', help='\033[91mEXPERIMENTAL: Adds models to DB without checking for existing DB state for debugging purposes. Only use in combination with Debugging Commit for testing.\033[0m Function: IfcGraphInterface.ifc2graph()')
debugging_add_parser.add_argument('-p', '--path', type=str, required=True, help='Path to the file to add.')
debugging_add_parser.add_argument('-t', '--timestamp', type=str, required=False, default="", help='OPTIONAL: Manually create a timestamp as a custom graph identifier.')
debugging_add_parser.add_argument('-i', '--project_id', type=str, required=False, default=None, help='OPTIONAL (GeoJSON/RDF): project id if the file does not define one (FeatureCollection "id" / owl:Ontology IRI).')

# "get" command parser
get_parser = subparsers.add_parser('get', help='Parses a file (.ifc, .geojson, .json, .ttl, ...) back from the graph backend. Function: IfcGraphInterface.graph_2_ifc() / GeoJsonGraphInterface.graph_2_geojson()')
get_parser.add_argument('-p', '--path', type=str, required=True, help='Path the file is parsed to.')
get_parser.add_argument('-t', '--timestamp', type=str, required=True, help='Timestamp of the graph model to get.')

# "commit" command parser
commit_parser = subparsers.add_parser('commit', help='Creates diff and patch from two graphs. Functions: GraphDiff.run_diff() and GraphPatch.create_patch()')
commit_parser.add_argument('-b', '--branch', type=str, required=True, help='Branch name to commit to.')
commit_parser.add_argument('-p', '--project_id', type=str, required=True, help='IfcProject GUID or FeatureCollection id of the project to commit to.')
commit_parser.add_argument('-m', '--message', type=str, required=False, default='', help='OPTIONAL: Commit message.')

# "debugging commit" command parser
debugging_commit_parser = subparsers.add_parser('debugging_commit', help='\033[91mEXPERIMENTAL: Creates a diff from 2 paths but does not create a patch or remove the init path. Only use for for viewing a chain of model versions in the DB, not for actual version tracking.\033[0m Function: GraphDiff.run_diff()')
debugging_commit_parser.add_argument('-p', '--project_id', type=str, required=True, help='IfcProject GUID or FeatureCollection id of the project to commit to.')
debugging_commit_parser.add_argument('-i', '--timestamp_init', type=str, required=True, help='Init timestamp for diff creation.')
debugging_commit_parser.add_argument('-u', '--timestamp_updt', type=str, required=True, help='Updt timestamp for diff creation.')

# "checkout" command parser
checkout_parser = subparsers.add_parser('checkout', help='Checks out a specific timestamp version of the model. Function: GraphPatch.apply_patch()')
checkout_parser.add_argument('-p', '--project_id', type=str, required=True, help='Branch name to checkout from.')
checkout_parser.add_argument('-b', '--branch_updt', type=str, required=True, help='Branch name to checkout to.')
checkout_parser.add_argument('-t', '--timestamp_updt', type=str, required=True, help='Timestamp of the updated graph model.')

# "branch" command parser
branch_parser = subparsers.add_parser('branch', help='Creates a new branch in the version timeline. Function: VersionTimeline.branch()')
branch_parser.add_argument('-n', '--name', type=str, required=True, help='Name of the new branch.')
branch_parser.add_argument('-p', '--project_id', type=str, required=True, help='IfcProject GUID of the project to create the branch in.')

# "remove" command parser
remove_parser = subparsers.add_parser('remove', help='Removes all nodes and relationships with the given timestamp from the database.')
remove_parser.add_argument('-t', '--timestamp', type=str, required=True, help='Timestamp of the graph model to remove.')

# "reset" command parser
reset_parser = subparsers.add_parser('reset', help='Removes all nodes and relationships from the database.')

# "nuke" command parser
nuke_parser = subparsers.add_parser('nuke', help='Deletes all added data in the database, deletes the timeline, and deletes all patch files.')
nuke_parser.add_argument('-y', '--yes', action="store_true", help='Automatically confirm the nuke operation without prompting.')

# "fetch" command parser
fetch_parser = subparsers.add_parser('fetch', help='Fetches updates from the remote repository.')

# "pull" command parser
pull_parser = subparsers.add_parser('pull', help='Fetches updates from the remote repository. And merges them into the local repository.')

# "push" command parser
push_parser = subparsers.add_parser('push', help='Pushes local commits to the remote repository.')

# "log" command parser
log_parser = subparsers.add_parser('log', help='Displays the commit graph for a project.')
log_parser.add_argument('-p', '--project_id', type=str, required=True, help='IfcProject GUID of the project to display the commit graph for.')

def _excepthook(exc_type, exc, tb):
    # Configuration errors are user errors: print them without a traceback.
    if issubclass(exc_type, ConMan2Config.ConfigError):
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(2)
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _excepthook

args = parser.parse_args()

if args.backend:
    ConMan2Config.OVERRIDES['graph_backend'] = args.backend
if args.increment:
    ConMan2Config.OVERRIDES['increment_representation'] = args.increment

if args.command == 'config':
    config_command(args.action, args.key, args.value)
elif args.command == 'add':
    path = args.path
    timestamp = args.timestamp
    add(path, timestamp, args.project_id)
elif args.command == 'debugging_add':
    path = args.path
    timestamp = args.timestamp
    debugging_add(path, timestamp, args.project_id)
elif args.command == 'get':
    path = args.path
    timestamp = args.timestamp
    print(f"Parsing file to path: {path}")
    get(path, timestamp)
elif args.command == 'commit':
    project_id = args.project_id
    branch_name = args.branch
    message = args.message
    commit(project_id=project_id, branch=branch_name, message=message)
elif args.command == 'debugging_commit':
    project_id = args.project_id
    ts_init = args.timestamp_init
    ts_updt = args.timestamp_updt
    debugging_commit(project_id=project_id, timestamp_init=ts_init, timestamp_updt=ts_updt)
elif args.command == 'checkout':
    project_id = args.project_id
    b_updt = args.branch_updt
    ts_updt = args.timestamp_updt
    checkout(project_id, b_updt, ts_updt)
elif args.command == 'branch':
    name = args.name
    project_id = args.project_id
    branch(project_id, name)
elif args.command == 'remove':
    timestamp = args.timestamp
    remove(timestamp)
elif args.command == 'reset':
    reset()
elif args.command == 'nuke':
    yes = args.yes
    nuke(yes)
elif args.command == 'fetch':
    fetch()
elif args.command == 'pull':
    pull()
elif args.command == 'push':
    push()
elif args.command == 'log':
    project_id = args.project_id
    log_timeline(project_id)
else:
    print("No command specified.")