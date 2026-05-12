from collections.abc import Callable
from typing import TypeVar

Data = TypeVar("Data")
Result = TypeVar("Result")
T = TypeVar("T")
U = TypeVar("U")


def identity(value: T) -> T:
    return value


def renamed(item: U) -> U:
    return item


def split(value: T) -> U:
    raise NotImplementedError


def missing(value):
    return value


def make_rule(spec: T) -> Callable[[Data], Result]:
    return lambda data: data


def build_rule(config: T) -> Callable[[Data], Result]:
    return lambda data: data


immediate_result = make_rule("spec")("data")
stored_rule = build_rule("config")
stored_rule("first")
stored_rule("second")
handlers = []
handlers.append(make_rule("spec"))
register_handler(make_rule("spec"))
mapped = map(make_rule("spec"), ["first", "second"])
cache = {}
cache["rule"] = build_rule("config")
