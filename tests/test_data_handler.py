import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

from data_handler.DataHandler import DataHandler  # noqa: E402


def test_existing_ifc_path_format_is_unchanged():
    path = [{"primary_node": "2KrDsiaI1FkRwWUa5EvoNK"},
            {"rel_type": "Representation", "list_index": 0, "EntityType": "IfcProductDefinitionShape"}]
    s = DataHandler.path_to_string(path)
    assert s == "[primary_node=2KrDsiaI1FkRwWUa5EvoNK]|[EntityType=IfcProductDefinitionShape,list_index=0,rel_type=Representation]"
    assert DataHandler.string_to_path(s) == path


def test_parses_paths_from_existing_patch_files():
    s = "[primary_node=1]|[EntityType=IfcDirection,list_index=1,rel_type=b]"
    assert DataHandler.string_to_path(s) == [{"primary_node": "1"},
                                             {"EntityType": "IfcDirection", "list_index": 1, "rel_type": "b"}]


@pytest.mark.parametrize("value", ["a,b", "x|y", "k=v", "[weird]", "100%", "way/123", "tum::bldg-1", "1001",
                                   " padded ", "Straße", "%7C"])
def test_values_with_delimiters_roundtrip(value):
    path = [{"primary_node": value}, {"rel_type": value, "list_index": 3, "EntityType": "Feature"}]
    assert DataHandler.string_to_path(DataHandler.path_to_string(path)) == path


def test_only_list_index_is_numeric():
    path = DataHandler.string_to_path("[connection_node=42]|[EntityType=Position,list_index=7,rel_type=1]")
    assert path[0]["connection_node"] == "42"
    assert path[1]["list_index"] == 7
    assert path[1]["rel_type"] == "1"


def test_empty():
    assert DataHandler.string_to_path("") == []
