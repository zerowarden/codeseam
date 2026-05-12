def mutable_default(items=[]):
    return items


def mutable_default_two(values=[]):
    return values


def mutable_default_three(tokens=[]):
    return tokens


def bare_except_pass():
    try:
        risky()
    except:
        pass


def bare_except_pass_two():
    try:
        risky()
    except:
        pass


def bare_except_pass_three():
    try:
        risky()
    except:
        pass


def broad_exception_sentinel():
    try:
        risky()
    except Exception:
        return None


def broad_exception_sentinel_two():
    try:
        risky()
    except Exception:
        return None


def broad_exception_sentinel_three():
    try:
        risky()
    except Exception:
        return None
