from __future__ import annotations

from typing import Any, get_args, get_origin, get_type_hints

try:  # pragma: no cover - exercised when the optional dependency is installed.
    from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
except ImportError:  # pragma: no cover - lightweight fallback for minimal/offline envs.
    class ValidationError(ValueError):
        pass

    class _FieldInfo:
        def __init__(self, default: Any = None, default_factory=None) -> None:
            self.default = default
            self.default_factory = default_factory

        def value(self) -> Any:
            if self.default_factory is not None:
                return self.default_factory()
            return self.default

    def Field(default: Any = None, *, default_factory=None, **_kwargs):
        return _FieldInfo(default=default, default_factory=default_factory)

    def ConfigDict(**kwargs):
        return dict(kwargs)

    def model_validator(*_args, **_kwargs):
        def deco(fn):
            return fn
        return deco

    class BaseModel:
        model_config: dict[str, Any] = {}

        def __init__(self, **data: Any) -> None:
            hints = get_type_hints(type(self))
            for name, annotation in hints.items():
                if name == "model_config":
                    continue
                if name in data:
                    value = data.pop(name)
                else:
                    default = getattr(type(self), name, None)
                    value = default.value() if isinstance(default, _FieldInfo) else default
                setattr(self, name, self._coerce(annotation, value))
            for key, value in data.items():
                setattr(self, key, value)

        @classmethod
        def model_validate(cls, data: Any):
            if isinstance(data, cls):
                return data
            if not isinstance(data, dict):
                raise ValidationError(f"expected mapping for {cls.__name__}")
            return cls(**data)

        @classmethod
        def _coerce(cls, annotation: Any, value: Any) -> Any:
            if value is None:
                return None
            origin = get_origin(annotation)
            args = get_args(annotation)
            if origin is list and args:
                inner = args[0]
                if isinstance(value, list):
                    return [cls._coerce(inner, item) for item in value]
                return value
            targets = args
            for target in targets or (annotation,):
                try:
                    if isinstance(target, type) and issubclass(target, BaseModel) and isinstance(value, dict):
                        return target.model_validate(value)
                except TypeError:
                    continue
            try:
                if isinstance(annotation, type) and issubclass(annotation, BaseModel) and isinstance(value, dict):
                    return annotation.model_validate(value)
            except TypeError:
                pass
            return value

        def model_dump(self, **_kwargs) -> dict[str, Any]:
            return dict(self.__dict__)
