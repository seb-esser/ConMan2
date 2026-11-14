import os
from pathlib import Path
from urllib.parse import urlparse
from dotenv import load_dotenv
from neomodel import config, db
from neo4j import GraphDatabase


def load_neo4j_config_from_env():
    """
    Load Neo4j configuration from .env file if it exists.
    Searches for .env file in the current directory and parent directories.
    Returns a dictionary with connection parameters or None if .env not found.
    """
    # Search for .env file starting from current directory up to repo root
    search_paths = [
        Path.cwd(),
        Path.cwd().parent,
        Path(__file__).parent.parent,  # src directory
        Path(__file__).parent.parent.parent,  # repo root
    ]
    
    for search_path in search_paths:
        env_file = search_path / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            neo4j_uri = os.getenv("NEO4J_URI")
            neo4j_username = os.getenv("NEO4J_USERNAME")
            neo4j_password = os.getenv("NEO4J_PASSWORD")
            
            if neo4j_uri and neo4j_username and neo4j_password:
                print(f"[Neo4j] Found .env file at: {env_file}")
                return {
                    "uri": neo4j_uri,
                    "username": neo4j_username,
                    "password": neo4j_password,
                    "from_env": True
                }
    
    # print(f"[Neo4j] No .env file found. Searched in: {[str(p) for p in search_paths]}")
    return None


class Neo4jConnection:

    """
    Class that handles database connection. Only needed when running direct CYPHER queries, as neomodel handles db interaction internally.
    An instance of this class can be used for CYPHER queries using <instance_name>.cypher_query("<cypher_query>").
    
    Connection behavior:
    - If a .env file with NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD is found, it uses the remote server
    - Otherwise, falls back to localhost connection with provided credentials
    """

    def __init__(self, username: str="neo4j", password: str="password", hostname: str="localhost", port: int=7687):
        # Try to load from .env file first
        env_config = load_neo4j_config_from_env()
        
        if env_config:
            self.username = env_config["username"]
            self.password = env_config["password"]
            self.uri = env_config["uri"]
            self.hostname = None
            self.port = None
            
            parsed = urlparse(self.uri)
            if parsed.scheme in ("bolt", "neo4j"):
                # Unencrypted (typically local / docker) instance, e.g. NEO4J_URI=bolt://localhost:7688.
                # Keep host and port as given so that non-default ports can be used.
                self.hostname = parsed.hostname
                self.port = parsed.port or 7687
                config.DATABASE_URL = f"bolt://{self.username}:{self.password}@{self.hostname}:{self.port}"
                print(f"[Neo4j] Using connection from .env: {self.hostname}:{self.port}")
            else:
                # For Aura, construct bolt+ssc:// URI with credentials
                # Extract host from neo4j+s://host format
                host = self.uri.replace("neo4j+s://", "").replace("neo4j://", "")
                bolt_uri = f"bolt+ssc://{self.username}:{self.password}@{host}:7687"

                config.DATABASE_URL = bolt_uri
                print(f"[Neo4j] Connected to remote Aura instance: {self.uri}")
        else:
            # Fallback to localhost
            self.username = username
            self.password = password
            self.hostname = hostname
            self.port = port
            self.uri = None
            config.DATABASE_URL = f"bolt://{self.username}:{self.password}@{self.hostname}:{self.port}"
            print(f"[Neo4j] Using localhost connection: {self.hostname}:{self.port}")

    def __getattr__(self, name):
        return getattr(db, name)