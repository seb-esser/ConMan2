import argparse
import os
import re
import shutil
from typing import Dict, Iterable, List, Set, Tuple

import ifcopenshell


class IfcDecomposer:
    def __init__(self, ifc_path: str, output_root: str = None):
        self.ifc_path = os.path.abspath(ifc_path)
        self.model = ifcopenshell.open(self.ifc_path)
        self.output_root = os.path.abspath(output_root) if output_root else os.path.dirname(self.ifc_path)
        self.output_dir = os.path.join(self.output_root, f"chunks_{os.path.splitext(os.path.basename(self.ifc_path))[0]}")
        self.all_entities = [e for e in self.model if e.id() != 0]
        self.all_object_defs = [e for e in self.model.by_type("IfcObjectDefinition") if e.id() != 0]
        self.entity_ids = {e.id() for e in self.all_entities}
        self.object_def_ids = {e.id() for e in self.all_object_defs}
        self.primary_roots = self._find_primary_roots()
        self.root_file_by_root_id = {
            root.id(): self._get_entity_filename(root)
            for root in self.primary_roots
        }
        self.object_root_map = {entity.id(): entity.id() for entity in self.all_object_defs}
        self.entity_to_file: Dict[int, str] = {}
        self._build_mappings()

    def _build_mappings(self) -> None:
        if os.path.isdir(self.output_dir):
            shutil.rmtree(self.output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        value = re.sub(r"[\s\\/:*?\"<>|]+", "_", value)
        value = re.sub(r"[^A-Za-z0-9_.\-]+", "_", value)
        return value.strip("_.") or "entity"

    def _get_entity_filename(self, entity: ifcopenshell.entity_instance) -> str:
        global_id = getattr(entity, "GlobalId", None)
        if global_id:
            id_part = str(global_id)
        else:
            id_part = f"id{entity.id()}"
        name = getattr(entity, "Name", None) or entity.is_a()
        safe_name = self._sanitize_filename(str(name))
        filename = f"{self._sanitize_filename(id_part)}_{safe_name}.pifc"
        return filename

    def _get_containment_parent_map(self) -> Dict[int, Set[int]]:
        parent_map: Dict[int, Set[int]] = {}

        def add_parent(child, parent):
            if child.id() == 0:
                return
            parent_map.setdefault(child.id(), set()).add(parent.id())

        for rel in self.model.by_type("IfcRelAggregates"):
            for obj in rel.RelatedObjects:
                add_parent(obj, rel.RelatingObject)

        for rel in self.model.by_type("IfcRelContainedInSpatialStructure"):
            for obj in rel.RelatedElements:
                add_parent(obj, rel.RelatingStructure)

        for rel in self.model.by_type("IfcRelVoidsElement"):
            add_parent(rel.RelatedOpeningElement, rel.RelatingBuildingElement)

        for rel in self.model.by_type("IfcRelFillsElement"):
            add_parent(rel.RelatingOpeningElement, rel.RelatedBuildingElement)

        for rel in self.model.by_type("IfcRelNests"):
            for obj in rel.RelatedObjects:
                add_parent(obj, rel.RelatingObject)

        return parent_map

    def _is_primary_root_candidate(self, entity: ifcopenshell.entity_instance) -> bool:
        if entity.id() == 0:
            return False
        if entity.is_a() == "IfcProject":
            return False
        if entity.is_a().endswith("Type"):
            return False
        if entity.is_a().endswith("Style"):
            return False
        if entity.is_a() == "IfcTypeProduct":
            return False
        return True

    def _find_primary_roots(self) -> List[ifcopenshell.entity_instance]:
        return sorted(self.all_object_defs, key=lambda x: x.id())

    def _find_root_for_object(self, entity_id: int, parent_map: Dict[int, Set[int]], memo: Dict[int, int]) -> int | None:
        return None

    def _get_object_root_map(self) -> Dict[int, int]:
        return {entity.id(): entity.id() for entity in self.all_object_defs}

    def _find_project_root(self) -> ifcopenshell.entity_instance | None:
        projects = self.model.by_type("IfcProject")
        if projects:
            return projects[0]
        return None

    def _iter_entity_references(self, entity: ifcopenshell.entity_instance) -> Iterable[ifcopenshell.entity_instance]:
        def traverse(value):
            if isinstance(value, ifcopenshell.entity_instance):
                yield value
            elif isinstance(value, (list, tuple)):
                for item in value:
                    yield from traverse(item)

        info = entity.get_info()
        for value in info.values():
            yield from traverse(value)

    def _build_object_def_graph(self) -> Dict[int, Set[int]]:
        graph: Dict[int, Set[int]] = {}
        for entity in self.all_object_defs:
            targets: Set[int] = set()
            for target in self._iter_entity_references(entity):
                if target.id() in self.object_def_ids and target.id() != entity.id():
                    targets.add(target.id())
            graph[entity.id()] = targets
        return graph

    def _build_traversal_order(self) -> List[ifcopenshell.entity_instance]:
        order: List[ifcopenshell.entity_instance] = []
        visited: Set[int] = set()
        graph = self._build_object_def_graph()
        project = self._find_project_root()

        def dfs(entity: ifcopenshell.entity_instance) -> None:
            eid = entity.id()
            if eid in visited:
                return
            visited.add(eid)
            order.append(entity)
            for child_id in sorted(graph.get(eid, [])):
                child = self.model.by_id(child_id)
                if child is not None:
                    dfs(child)

        if project and project.id() in self.object_def_ids:
            dfs(project)

        for entity in sorted(self.all_object_defs, key=lambda x: x.id()):
            if entity.id() not in visited:
                order.append(entity)
                visited.add(entity.id())
        return order

    def _format_step_string(self, value: str) -> str:
        value = value.replace("'", "''")
        return f"'{value}'"

    def _format_value(self, value) -> str:
        if value is None:
            return "$"
        if isinstance(value, bool):
            return ".T." if value else ".F."
        if isinstance(value, str):
            return self._format_step_string(value)
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, ifcopenshell.entity_instance):
            if value.id() == 0:
                return self._serialize_inline_entity(value)
            return f"#{value.id()}"
        if isinstance(value, (list, tuple)):
            values = ",".join(self._format_value(item) for item in value)
            return f"({values})"
        return self._format_step_string(str(value))

    def _serialize_inline_entity(self, entity: ifcopenshell.entity_instance) -> str:
        info = entity.get_info()
        args = []
        for key, value in info.items():
            if key in ("type", "id"):
                continue
            args.append(self._format_value(value))
        joined = ",".join(args)
        return f"{entity.is_a().upper()}({joined})"

    def _serialize_entity(self, entity: ifcopenshell.entity_instance) -> str:
        info = entity.get_info()
        values: List[str] = []
        for key, value in info.items():
            if key in ("type", "id"):
                continue
            values.append(self._format_value(value))
        joined = ",".join(values)
        return f"#{entity.id()}={entity.is_a().upper()}({joined});"

    def _collect_entities_for_root(self, root: ifcopenshell.entity_instance, seen_global: Set[int]) -> Tuple[List[int], Set[str]]:
        # Return an ordered list of entity ids (first-visited order) and a set of include filenames
        ordered_ids: List[int] = []
        seen_local: Set[int] = set()
        includes: Set[str] = set()
        stack = [root]

        while stack:
            entity = stack.pop()
            if entity.id() == 0:
                continue

            # If already assigned globally, reference its file as include and skip expansion
            if entity.id() in seen_global:
                file_path = self.entity_to_file.get(entity.id())
                if file_path:
                    includes.add(file_path)
                continue

            # If entity belongs to another primary root, reference that root file
            if entity.id() != root.id() and entity.id() in self.object_root_map:
                other_root_id = self.object_root_map[entity.id()]
                if other_root_id != root.id() and other_root_id in self.root_file_by_root_id:
                    includes.add(self.root_file_by_root_id[other_root_id])
                    continue

            if entity.id() in seen_local:
                continue

            # mark visited locally and append to ordered list
            seen_local.add(entity.id())
            ordered_ids.append(entity.id())

            # push referenced targets to stack to explore; use reversed order to keep natural traversal
            refs = [t for t in self._iter_entity_references(entity) if getattr(t, 'id', lambda: 0)() != 0]
            for target in reversed(refs):
                stack.append(target)

        return ordered_ids, includes

    def _serialize_chunk_file(self, root: ifcopenshell.entity_instance, included_ids: List[int], includes: Set[str]) -> str:
        lines: List[str] = [f"-- Chunk file for primary root {root.is_a()} #{root.id()} ({getattr(root, 'Name', '$')})"]
        for included_file in sorted(includes):
            if included_file != self.root_file_by_root_id[root.id()]:
                lines.append(f'#include "{included_file}"')

        # write entities in traversal (first-visited) order
        for entity_id in included_ids:
            entity = self.model.by_id(entity_id)
            if entity is not None:
                lines.append(self._serialize_entity(entity))

        return "\n".join(lines)

    def _serialize_relationships(self) -> str:
        relationships = [entity for entity in self.model.by_type("IfcRelationship") if entity.id() != 0]
        included_files: Set[str] = set()
        chunks: List[str] = ["-- Relationships file containing all IfcRelationship instances"]

        for relationship in relationships:
            for target in self._iter_entity_references(relationship):
                if target.id() == 0:
                    continue
                file_path = self.entity_to_file.get(target.id())
                if file_path:
                    included_files.add(file_path)
                elif target.id() in self.root_file_by_root_id:
                    included_files.add(self.root_file_by_root_id[target.id()])
            chunks.append(self._serialize_entity(relationship))

        for included_file in sorted(included_files):
            chunks.insert(1, f'#include "{included_file}"')
        return "\n".join(chunks)

    def write_chunks(self) -> None:
        seen_global: Set[int] = set()
        for root in self.primary_roots:
            filename = self.root_file_by_root_id[root.id()]
            included_ids, includes = self._collect_entities_for_root(root, seen_global)
            for entity_id in included_ids:
                if entity_id not in self.entity_to_file:
                    self.entity_to_file[entity_id] = filename

            content = self._serialize_chunk_file(root, included_ids, includes)
            target_path = os.path.join(self.output_dir, filename)
            with open(target_path, "w", encoding="utf-8") as handle:
                handle.write(content)
            seen_global.update(included_ids)

        # Exclude IFC relationship instances from orphaned entities: they belong in _relationships.pifc
        remaining = [e for e in self.all_entities if e.id() not in self.entity_to_file and not e.is_a().startswith('IfcRel')]
        if remaining:
            orphan_filename = "orphaned_entities.pifc"
            for entity in sorted(remaining, key=lambda e: e.id()):
                self.entity_to_file[entity.id()] = orphan_filename
            lines = ["-- Orphaned instances not assigned to a primary root"]
            for entity in sorted(remaining, key=lambda e: e.id()):
                lines.append(self._serialize_entity(entity))
            with open(os.path.join(self.output_dir, orphan_filename), "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))

    def write_relationships_file(self) -> None:
        output_path = os.path.join(self.output_dir, "_relationships.pifc")
        content = self._serialize_relationships()
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(content)

    def summarize(self) -> str:
        total_instances = len([e for e in self.model if e.id() != 0])
        return (
            f"Decomposed IFC file: {os.path.basename(self.ifc_path)}\n"
            f"Output folder: {self.output_dir}\n"
            f"Primary root chunks: {len(self.primary_roots)}\n"
            f"IfcRelationship instances: {len(self.model.by_type('IfcRelationship'))}\n"
            f"Total non-zero IFC instances in source: {total_instances}"
        )

    def run(self) -> None:
        self.write_chunks()
        self.write_relationships_file()
        print(self.summarize())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Decompose an IFC file into object-definition chunks with cross-file references.")
    parser.add_argument("ifc_file", help="Path to the IFC file to decompose.")
    parser.add_argument("--output", help="Optional output root folder to store the chunk directory.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    decomposer = IfcDecomposer(args.ifc_file, args.output)
    decomposer.run()


if __name__ == "__main__":
    main()
