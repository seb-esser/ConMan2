from command_line_interface.Backend import get_backend


def remove(timestamp: str):

    get_backend().drop(timestamp)
    print(f"Removed graph version {timestamp}.")
