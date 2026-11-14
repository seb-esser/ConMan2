# Patch Structure Documentation

This file documents the structure of the JSON files produced by the GraphPatch. The used patch files are taken from the `dissertation_demo.py` script and depict the resulting patch from the example scenario given in the [Dissertation](https://mediatum.ub.tum.de/doc/1736912/1736912.pdf#page=120).

## Topological Patch

The topological patch contains the information on the pushout patterns, the nodes and relations that are not part of the common subgraph between two versions of a model. The basic structure of a single pushout node of the init part of the pushout pattern is as follows:

The whole JSON file is divided into the init and the updt pushout part. Each part contains the respective pushout nodes and relations. Within the timestamps, every pushout node is listed along with its semantic information and relations to other pushout nodes in the patch pattern (referenced by their neo4j node id), as well as relations to and from context nodes (identified by their unique path which is listed under "path").

The full topological patch pattern of the dissertation example is shown below. It has one init pushout node and three updt pushout nodes.

```json
{
    "diss_init": {
        "4:434099e0-34de-4d35-8370-1df7c77b0935:1045": {
            "properties": {
                "EntityType": "IfcWall",
                "timestamp": "diss_init",
                "p21_id": "#2",
                "GlobalId": "2",
                "element_id_property": "4:434099e0-34de-4d35-8370-1df7c77b0935:1045"
            },
            "node_type": "PrimaryNode",
            "path": "[primary_node=2]",
            "relation_to": {},
            "context_to": {
                "4:434099e0-34de-4d35-8370-1df7c77b0935:24": {
                    "path": "[primary_node=1]|[EntityType=IfcDirection,list_index=1,rel_type=b]",
                    "properties": {
                        "rel_type": "c",
                        "list_index": 0,
                        "element_id_property": "5:434099e0-34de-4d35-8370-1df7c77b0935:1155173304420533269"
                    }
                }
            },
            "context_from": {
                "4:434099e0-34de-4d35-8370-1df7c77b0935:22": {
                    "path": "[primary_node=1]",
                    "properties": {
                        "rel_type": "a",
                        "list_index": 0,
                        "element_id_property": "5:434099e0-34de-4d35-8370-1df7c77b0935:1152921504606846998"
                    }
                }
            }
        }
    },
    "diss_updt": {
        "4:434099e0-34de-4d35-8370-1df7c77b0935:28": {
            "properties": {
                "EntityType": "IfcMaterial",
                "timestamp": "diss_updt",
                "p21_id": "#7",
                "element_id_property": "4:434099e0-34de-4d35-8370-1df7c77b0935:28"
            },
            "node_type": "SecondaryNode",
            "path": "[connection_node=5]|[EntityType=IfcMaterial,list_index=0,rel_type=e]",
            "relation_to": {},
            "context_to": {},
            "context_from": {}
        },
        "4:434099e0-34de-4d35-8370-1df7c77b0935:1050": {
            "properties": {
                "EntityType": "IfcRelAssociatesMaterial",
                "timestamp": "diss_updt",
                "p21_id": "#5",
                "GlobalId": "5",
                "element_id_property": "4:434099e0-34de-4d35-8370-1df7c77b0935:1050"
            },
            "node_type": "ConnectionNode",
            "path": "[connection_node=5]",
            "relation_to": {
                "4:434099e0-34de-4d35-8370-1df7c77b0935:28": {
                    "properties": {
                        "rel_type": "e",
                        "list_index": 0,
                        "element_id_property": "5:434099e0-34de-4d35-8370-1df7c77b0935:1155173304420533274"
                    }
                },
                "4:434099e0-34de-4d35-8370-1df7c77b0935:1053": {
                    "properties": {
                        "rel_type": "f",
                        "list_index": 1,
                        "element_id_property": "5:434099e0-34de-4d35-8370-1df7c77b0935:1157425104234218522"
                    }
                }
            },
            "context_to": {},
            "context_from": {
                "4:434099e0-34de-4d35-8370-1df7c77b0935:1049": {
                    "path": "[primary_node=1]",
                    "properties": {
                        "rel_type": "d",
                        "list_index": 0,
                        "element_id_property": "5:434099e0-34de-4d35-8370-1df7c77b0935:1152921504606848025"
                    }
                }
            }
        },
        "4:434099e0-34de-4d35-8370-1df7c77b0935:1053": {
            "properties": {
                "EntityType": "IfcWall",
                "timestamp": "diss_updt",
                "p21_id": "#8",
                "GlobalId": "8",
                "element_id_property": "4:434099e0-34de-4d35-8370-1df7c77b0935:1053"
            },
            "node_type": "PrimaryNode",
            "path": "[primary_node=8]",
            "relation_to": {},
            "context_to": {},
            "context_from": {}
        }
    }
}
```

## Semantic Patch

The semantic patch pattern lists the different attribute values that attibutes carry between different versions of the model. Only persistent nodes (i.e. nodes that are diffed as equivalent) show up here. The structure is as follows:

The file contains a list of all equivalent nodes with their unique path as the identifier. Within a single node, the name of every attribute that has changed is given (e.g. just the p21_id). Within a single attribute, the changed values are identified by the timestamp of the init and the updt version of the model.

The full semantic patch pattern of the dissertation example is shown below.

```json
{
    "[primary_node=1]|[EntityType=IfcDirection,list_index=1,rel_type=b]": {
        "p21_id": {
            "diss_init": "#3",
            "diss_updt": "#5"
        }
    }
}
```

## Extensions for open-schema models (GeoJSON)

In IFC every entity of a class has the same attribute set (a value, `$`, or a relation). In GeoJSON, by
contrast, features gain and lose property keys between versions. The semantic patch therefore
compares the **union** of attribute keys of two equivalent nodes. An attribute that does not exist in
one version is written as `null` for that version:

```json
{
    "[primary_node=bldg-0001]|[EntityType=Properties,list_index=0,rel_type=properties]": {
        "energyRating": { "ts_v1": null, "ts_v2": "B" },
        "comment":      { "ts_v1": "null", "ts_v2": null }
    }
}
```

`apply_patch` removes an attribute whose target value is `null`. A JSON `null` *value* inside GeoJSON
properties is stored as the text `"null"` (see `meta__json_keys`), so the two cannot be confused.

Unique paths percent-encode the characters `% | , = [ ]` inside keys and values
(`[primary_node=way/123]`, `[connection_node=proj::a%2Cb]`). Only `list_index` is parsed as a number.
IFC paths contain none of these characters and are unchanged.
