from command_line_interface.Backend import get_backend


def get(model_path: str, timestamp: str):

    get_backend().export(model_path, timestamp)
