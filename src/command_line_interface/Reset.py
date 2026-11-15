from command_line_interface.Backend import get_backend


def reset():

    backend = get_backend()
    backend.reset()
    print(f"All graph versions in the {backend.name} backend have been removed.")
