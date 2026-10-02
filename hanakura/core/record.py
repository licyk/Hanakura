"""Base class for records that cross the API boundary."""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from typing import TYPE_CHECKING, Any

import pydantic
from pydantic import BaseModel

if TYPE_CHECKING:
    from typing_extensions import Self

PYDANTIC_V2 = hasattr(BaseModel, "model_validate")


def _call_v1(model: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    """Dispatch v1 APIs whose signatures differ from their deprecated v2 counterparts."""
    return getattr(model, method)(*args, **kwargs)


class _ComputedProperty(property):
    """Mark a property for v1 serialization without accepting it as model input."""


def _computed_field(prop: property) -> property:
    return _ComputedProperty(prop.fget, prop.fset, prop.fdel, prop.__doc__)


computed_field = getattr(pydantic, "computed_field", _computed_field)


def _computed_properties(model: type[BaseModel]) -> dict[str, _ComputedProperty]:
    return {name: prop for base in reversed(model.__mro__) for name, prop in vars(base).items() if isinstance(prop, _ComputedProperty)}


class Record(BaseModel):
    """Use native models on both Pydantic versions, with a shared v2-style API."""

    if PYDANTIC_V2:
        # Defaulted fields are always present in output; the v2 schema reflects that.
        model_config = {"json_schema_serialization_defaults_required": True}
    else:

        @classmethod
        def model_validate(cls, obj: Any, **kwargs: Any) -> Self:
            return _call_v1(cls, "parse_obj", obj, **kwargs)

        @classmethod
        def model_validate_json(cls, json_data: str | bytes | bytearray, **kwargs: Any) -> Self:
            return _call_v1(cls, "parse_raw", json_data, **kwargs)

        def model_dump(self, *, mode: str = "python", **kwargs: Any) -> dict[str, Any]:
            if mode == "json":
                return json.loads(_call_v1(self, "json", **kwargs))
            return _call_v1(self, "dict", **kwargs)

        def model_dump_json(self, **kwargs: Any) -> str:
            return _call_v1(self, "json", **kwargs)

        def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
            return _call_v1(self, "copy", update=update, deep=deep)

        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            # Keep the event-schema merger independent of Pydantic's definitions key.
            schema = dict(_call_v1(cls, "schema", *args, **kwargs))
            if "definitions" in schema:
                schema["$defs"] = schema.pop("definitions")
            return schema

        def _iter(self, *args: Any, **kwargs: Any) -> Generator[tuple[str, Any], None, None]:
            yield from _call_v1(super(), "_iter", *args, **kwargs)
            # v1 uses _iter for nested models, FastAPI responses and JSON persistence.
            # copy() also uses it, but computed properties must never become stored fields.
            if not kwargs.get("to_dict"):
                return
            include, exclude = kwargs.get("include"), kwargs.get("exclude")
            for name in _computed_properties(type(self)):
                if include is not None and name not in include:
                    continue
                if exclude is not None and name in exclude and (not isinstance(exclude, dict) or exclude[name] is True or exclude[name] is ...):
                    continue
                yield name, getattr(self, name)

        class Config:
            @staticmethod
            def schema_extra(schema: dict[str, Any], model: type[BaseModel]) -> None:
                for name in _computed_properties(model):
                    # The only computed value in the contract is DownloadJob.can_pause.
                    schema.setdefault("properties", {})[name] = {"title": name.replace("_", " ").title(), "type": "boolean", "readOnly": True}
                    schema.setdefault("required", []).append(name)
