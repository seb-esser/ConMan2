import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from neomodel import config
from neo4j_core import neo4j_connection
from neo4j_core.neo4j_connection import Neo4jConnection


def _env(uri):
    return {"uri": uri, "username": "neo4j", "password": "pw", "from_env": True}


def test_env_bolt_uri_keeps_host_and_port():
    with patch.object(neo4j_connection, "load_neo4j_config_from_env", return_value=_env("bolt://localhost:7688")):
        conn = Neo4jConnection()
    assert config.DATABASE_URL == "bolt://neo4j:pw@localhost:7688"
    assert conn.port == 7688


def test_env_aura_uri_unchanged_behaviour():
    with patch.object(neo4j_connection, "load_neo4j_config_from_env", return_value=_env("neo4j+s://abc.databases.neo4j.io")):
        Neo4jConnection()
    assert config.DATABASE_URL == "bolt+ssc://neo4j:pw@abc.databases.neo4j.io:7687"


def test_no_env_falls_back_to_localhost():
    with patch.object(neo4j_connection, "load_neo4j_config_from_env", return_value=None):
        Neo4jConnection(username="u", password="p", hostname="localhost", port=7687)
    assert config.DATABASE_URL == "bolt://u:p@localhost:7687"
