class DataHandler:
    """
    (De)serialisation of unique paths, e.g.
        [primary_node=2]|[EntityType=IfcDirection,list_index=1,rel_type=b]

    Values may contain the delimiters themselves (GeoJSON feature ids are arbitrary strings), so the
    characters  % | , = [ ]  are percent-encoded inside keys and values. IFC GlobalIds, attribute names
    and class names never contain them, so paths of existing IFC patches are unchanged.

    Only "list_index" is converted back to int (or None). All other values stay strings: an id such as
    "1001" must not turn into the integer 1001.
    """

    _ESCAPES = {"%": "%25", "|": "%7C", ",": "%2C", "=": "%3D", "[": "%5B", "]": "%5D"}
    _INT_KEYS = ("list_index",)

    @staticmethod
    def _escape(value) -> str:
        return "".join(DataHandler._ESCAPES.get(c, c) for c in str(value))

    @staticmethod
    def _unescape(value: str) -> str:
        if "%" not in value:
            return value
        reverse = {v: k for k, v in DataHandler._ESCAPES.items()}
        out, i = [], 0
        while i < len(value):
            token = value[i:i + 3].upper()
            if value[i] == "%" and token in reverse:
                out.append(reverse[token])
                i += 3
            else:
                out.append(value[i])
                i += 1
        return "".join(out)

    @staticmethod
    def path_to_string(path):
        parts = []
        for item in path:
            if isinstance(item, dict):
                dict_str = ','.join(f"{DataHandler._escape(k)}={DataHandler._escape(v)}" for k, v in sorted(item.items()))
                parts.append(f"[{dict_str}]")
            else:
                parts.append(DataHandler._escape(item))
        return '|'.join(parts)

    @staticmethod
    def string_to_path(string):
        if not string:
            return []
        path = []
        for part in string.split('|'):
            if part.startswith('[') and part.endswith(']'):
                dict_obj = {}
                dict_content = part[1:-1]
                if dict_content:
                    for pair in dict_content.split(','):
                        if '=' not in pair:
                            continue
                        key, value = pair.split('=', 1)
                        key, value = DataHandler._unescape(key), DataHandler._unescape(value)
                        if key in DataHandler._INT_KEYS:
                            dict_obj[key] = None if value == 'None' else int(value)
                        else:
                            dict_obj[key] = value
                path.append(dict_obj)
            else:
                part = DataHandler._unescape(part)
                if part.isdigit():
                    path.append(int(part))
                elif part == 'None':
                    path.append(None)
                else:
                    path.append(part)
        return path
