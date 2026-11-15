"""
End-to-end tests of conman2.py (subprocess, fresh working directory per test).

* graph_backend = networkx: no database needed.
* graph_backend = neo4j: opt-in via CONMAN2_TEST_NEO4J_URI (bolt://user:password@host:port). WIPES that DB.
"""
import json
import os
import subprocess
import sys
from urllib.parse import urlparse

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
CLI = os.path.join(SRC, "conman2.py")
sys.path.insert(0, SRC)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CAMPUS = [os.path.join(SRC, "00_sampleData", "GeoJSON", "citygml_campus", f"campus_v{i}.geojson") for i in range(1, 6)]
CAMPUS_ID = "tum-campus-citygml3-demo"
IFC = os.path.join(SRC, "00_sampleData", "IFC_stepP21", "GeomRepresentation_01")
NEO4J_TEST_URI = os.environ.get("CONMAN2_TEST_NEO4J_URI")


class Cli:
    def __init__(self, cwd):
        self.cwd = str(cwd)

    def __call__(self, *args, check=True, stdin=None):
        result = subprocess.run([sys.executable, CLI, *args], cwd=self.cwd, capture_output=True, text=True, input=stdin)
        if check and result.returncode != 0:
            raise AssertionError(f"conman2 {' '.join(args)} failed:\n{result.stdout[-2000:]}\n{result.stderr[-3000:]}")
        return result

    def path(self, name):
        return os.path.join(self.cwd, name)

    def json(self, name):
        with open(self.path(name), encoding="utf-8") as f:
            return json.load(f)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def cli(tmp_path):
    return Cli(tmp_path)


# ----------------------------------------------------------------------
# config command
# ----------------------------------------------------------------------

def test_config_defaults_and_set(cli):
    out = cli("config", "show").stdout
    assert "graph_backend             neo4j" in out
    cli("config", "set", "graph_backend", "networkx")
    assert cli("config", "get", "graph_backend").stdout.strip() == "networkx"
    assert cli.json("conman2_config.json")["graph_backend"] == "networkx"
    cli("config", "reset")
    assert cli.json("conman2_config.json")["graph_backend"] == "neo4j"


def test_config_rejects_invalid_values(cli):
    result = cli("config", "set", "graph_backend", "oracle", check=False)
    assert result.returncode == 2
    assert "Choices: neo4j, networkx" in result.stderr
    assert "Traceback" not in result.stderr
    assert cli("config", "set", "nonsense", "x", check=False).returncode == 2


def test_config_menu(cli):
    # 1 -> graph_backend, 2 -> networkx; 2 -> increment_representation, 2 -> rdf-patch; save
    out = cli("config", "menu", stdin="1\n2\n2\n2\ns\n").stdout
    assert "Saved to" in out
    cfg = cli.json("conman2_config.json")
    assert cfg["graph_backend"] == "networkx" and cfg["increment_representation"] == "rdf-patch"


def test_config_menu_quit_discards(cli):
    cli("config", "menu", stdin="1\n2\nq\n")
    assert not os.path.exists(cli.path("conman2_config.json"))


def test_backend_override_is_not_persisted(cli):
    cli("config", "set", "graph_backend", "networkx")
    assert cli("--backend", "neo4j", "config", "get", "graph_backend").stdout.strip() == "neo4j"
    assert cli.json("conman2_config.json")["graph_backend"] == "networkx"


def test_debugging_commands_require_neo4j(cli):
    cli("config", "set", "graph_backend", "networkx")
    result = cli("debugging_add", "-p", CAMPUS[0], "-t", "x", check=False)
    assert result.returncode != 0 and "require graph_backend = neo4j" in result.stderr


# ----------------------------------------------------------------------
# full session, both backends
# ----------------------------------------------------------------------

def run_session(cli):
    cli("add", "-p", CAMPUS[0], "-t", "ts1")
    cli("commit", "-p", CAMPUS_ID, "-b", "main", "-m", "initial")
    for i in (2, 3):
        cli("add", "-p", CAMPUS[i - 1], "-t", f"ts{i}")
        cli("commit", "-p", CAMPUS_ID, "-b", "main", "-m", f"v{i}")
    cli("branch", "-n", "alt", "-p", CAMPUS_ID)
    for i in (4, 5):
        cli("add", "-p", CAMPUS[i - 1], "-t", f"ts{i}")
        cli("commit", "-p", CAMPUS_ID, "-b", "main", "-m", f"v{i}")
    cli("get", "-p", "out5.geojson", "-t", "ts5")
    assert cli.json("out5.geojson") == load(CAMPUS[4])
    cli("checkout", "-p", CAMPUS_ID, "-b", "main", "-t", "ts2")
    cli("get", "-p", "out2.geojson", "-t", "ts2")
    assert cli.json("out2.geojson") == load(CAMPUS[1])
    # commit on branch alt on top of a patched state, then walk across branches
    cli("checkout", "-p", CAMPUS_ID, "-b", "alt", "-t", "ts3")
    cli("add", "-p", CAMPUS[4], "-t", "ts6")
    cli("commit", "-p", CAMPUS_ID, "-b", "alt", "-m", "v5 on alt")
    cli("checkout", "-p", CAMPUS_ID, "-b", "main", "-t", "ts1")
    cli("get", "-p", "out1.geojson", "-t", "ts1")
    assert cli.json("out1.geojson") == load(CAMPUS[0])
    # an IFC project next to it
    from ifc_graph_interface.IfcGraphInterface import IfcGraphInterface
    from ifc_signature import ifc_signature
    init, updt = os.path.join(IFC, "Initial_GeomRepresentation_01.ifc"), os.path.join(IFC, "Update_GeomRepresentation_01.ifc")
    pid = IfcGraphInterface.get_project_id_from_ifc_path(init)
    cli("add", "-p", init, "-t", "ifc1")
    cli("commit", "-p", pid, "-b", "main")
    cli("get", "-p", "ref1.ifc", "-t", "ifc1")
    cli("add", "-p", updt, "-t", "ifc2")
    cli("commit", "-p", pid, "-b", "main")
    cli("get", "-p", "ref2.ifc", "-t", "ifc2")
    cli("checkout", "-p", pid, "-b", "main", "-t", "ifc1")
    cli("get", "-p", "out_ifc1.ifc", "-t", "ifc1")
    assert ifc_signature(cli.path("out_ifc1.ifc")) == ifc_signature(cli.path("ref1.ifc"))
    cli("checkout", "-p", pid, "-b", "main", "-t", "ifc2")
    cli("get", "-p", "out_ifc2.ifc", "-t", "ifc2")
    assert ifc_signature(cli.path("out_ifc2.ifc")) == ifc_signature(cli.path("ref2.ifc"))
    # GeoJSON project untouched by the IFC checkouts
    cli("get", "-p", "out1b.geojson", "-t", "ts1")
    assert cli.json("out1b.geojson") == load(CAMPUS[0])
    timeline = cli.json("timeline_data/timeline.json")[CAMPUS_ID]
    assert timeline["branches"] == {"main": "ts5", "alt": "ts6"}
    assert timeline["commits"]["ts2"]["increment"] == "conman"


def test_cli_session_networkx(cli):
    cli("config", "set", "graph_backend", "networkx")
    run_session(cli)
    index = cli.json("graph_data/index.json")
    assert sorted(index) == ["ifc2", "ts1"]   # exactly one version per project is stored
    cli("nuke", "-y")
    assert cli.json("graph_data/index.json") == {}


@pytest.mark.skipif(not NEO4J_TEST_URI, reason="CONMAN2_TEST_NEO4J_URI not set")
def test_cli_session_neo4j(cli):
    u = urlparse(NEO4J_TEST_URI)
    with open(cli.path(".env"), "w") as f:
        f.write(f"NEO4J_URI=bolt://{u.hostname}:{u.port}\nNEO4J_USERNAME={u.username}\nNEO4J_PASSWORD={u.password}\n")
    # Safety: a harmless probe must report the test instance before anything destructive runs.
    probe = cli("remove", "-t", "__conman2_probe__").stdout
    assert f"Using connection from .env: {u.hostname}:{u.port}" in probe, probe
    cli("nuke", "-y")
    run_session(cli)
    cli("nuke", "-y")
