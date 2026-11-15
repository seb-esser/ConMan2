from command_line_interface.Backend import get_backend
import os

def nuke(yes: bool=False):

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

    # Remove all graph versions in the configured backend.
    get_backend().reset()

    print(f"Nuked: all graph versions in the configured backend, patch files and the version timeline are removed.")