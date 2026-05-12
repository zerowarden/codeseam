def no_mutable_default(items=None):
    return items


def no_mutable_default_two(values=()):
    return values


def no_mutable_default_three(tokens=frozenset()):
    return tokens


def specific_exception_raises():
    try:
        risky()
    except ValueError:
        raise


def specific_exception_handles():
    try:
        risky()
    except ValueError:
        return None


def broad_exception_without_sentinel():
    try:
        risky()
    except Exception:
        raise


def broad_exception_returns_value():
    try:
        risky()
    except Exception:
        return "fallback"
