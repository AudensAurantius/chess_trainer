from typing import Any, Literal, Self, Optional
from datetime import datetime
from dataclasses import dataclass as _dataclass, field
from dataclasses_json import (
    LetterCase,
    config,
    Undefined,
    DataClassJsonMixin,
    CatchAll,
)


def dataclass(cls):
    return _dataclass(kw_only=True)(cls)


def timestamp(field_name: str | None = None):
    return field(
        metadata=config(
            decoder=lambda x: datetime.fromtimestamp(x / 1000),
            encoder=lambda x: 1000 * x.timestamp,
            field_name=field_name,
        )
    )


@dataclass
class Model(DataClassJsonMixin):
    dataclass_json_config = config(
        letter_case=LetterCase.CAMEL,
        undefined=Undefined.INCLUDE,
        exclude=lambda x: x is None,
    )["dataclasses_json"]

    _properties: Optional[CatchAll] = field(default_factory=dict)

    def __getitem__(self, name):
        try:
            return self.__getattribute__(name)
        except AttributeError:
            properties = self._properties if self._properties is not None else {}
            return properties[name]
