"""Base dataclass model with JSON serialization support."""

from dataclasses import dataclass as _dataclass
from dataclasses import field
from datetime import datetime
from typing import Any

from dataclasses_json import (
    CatchAll,
    DataClassJsonMixin,
    LetterCase,
    Undefined,
    config,
)


def dataclass(cls: type) -> type:
    """Decorator that wraps ``dataclasses.dataclass`` with ``kw_only=True``.

    Args:
        cls: The class to decorate.

    Returns:
        The decorated dataclass.
    """
    return _dataclass(kw_only=True)(cls)


def timestamp(field_name: str | None = None) -> Any:
    """Create a dataclass field with millisecond-epoch timestamp encoding.

    Args:
        field_name: Optional JSON field name override.

    Returns:
        A ``dataclasses.field`` configured for timestamp serialization.
    """
    return field(
        metadata=config(
            decoder=lambda x: datetime.fromtimestamp(x / 1000),
            encoder=lambda x: 1000 * x.timestamp(),
            field_name=field_name,
        )
    )


@dataclass
class Model(DataClassJsonMixin):
    """Base model with camelCase JSON and catch-all for unknown fields."""

    dataclass_json_config = config(
        letter_case=LetterCase.CAMEL,
        undefined=Undefined.INCLUDE,
        exclude=lambda x: x is None,
    )["dataclasses_json"]

    _properties: CatchAll | None = field(default_factory=dict)

    def __getitem__(self, name: str) -> Any:
        try:
            return self.__getattribute__(name)
        except AttributeError:
            properties = self._properties if self._properties is not None else {}
            return properties[name]
