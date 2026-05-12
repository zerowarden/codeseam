from typing import overload
from abc import abstractmethod


class Descriptor:
    def __get__(self, obj, owner):
        return self.value


class Operator:
    def __add__(self, other):
        return self._binary("+", other)


class NumericProtocol:
    def __float__(self):
        return float(self.value)


class FrameworkHook:
    def __tablename__(self):
        return "items"


class Facade:
    @property
    def value(self):
        return self._value

    @declared_attr.directive
    def declared(self):
        return self._declared

    def query(self, *args, **kwargs):
        return self._proxied.query(*args, **kwargs)

    def load(self, *args, **kwargs):
        return self._proxied.fetch(*args, **kwargs)

    async def execute(self, *args, **kwargs):
        return await self._proxied.execute(*args, **kwargs)


class Overloaded:
    @overload
    def get(self, key: str) -> str: ...

    def get(self, key):
        return self._values[key]


class Interface:
    @abstractmethod
    def build(self):
        return self._build()
