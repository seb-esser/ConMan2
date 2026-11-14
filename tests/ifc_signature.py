"""Order- and id-independent structural signature of an IFC file (test helper)."""
from collections import Counter

import ifcopenshell


def ifc_signature(path: str) -> Counter:
    model = ifcopenshell.open(path)
    memo = {}

    def canonical(value):
        if isinstance(value, ifcopenshell.entity_instance):
            if value.id() == 0:
                return ("inline", value.is_a(), canonical(value.wrappedValue))
            return ("ref", entity_hash(value))
        if isinstance(value, (tuple, list)):
            return tuple(canonical(v) for v in value)
        if isinstance(value, float):
            return round(value, 9)
        return value

    def entity_hash(entity):
        if entity.id() not in memo:
            memo[entity.id()] = hash((entity.is_a(), tuple(canonical(entity[i]) for i in range(len(entity)))))
        return memo[entity.id()]

    return Counter(entity_hash(e) for e in model if e.id() != 0)
