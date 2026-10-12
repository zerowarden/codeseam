def parse_env_lines(lines):
    result = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"')
    return result
