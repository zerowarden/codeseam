def enabled_feature_names(flags, environment):
    names = []
    for flag in flags:
        if flag.environment != environment:
            continue
        if flag.enabled:
            names.append(flag.name)
    return sorted(names)
