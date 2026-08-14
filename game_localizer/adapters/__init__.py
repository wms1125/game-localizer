from .base import EngineAdapter
from .godot import GodotAdapter
from .renpy import RenPyAdapter
from .rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter
from .unity import UnityAdapter
from .unreal import UnrealAdapter
from .contract import (
    AdapterCapabilityMatrix,
    AdapterV1,
    CapabilityArea,
    CapabilityDeclaration,
    CapabilityStatus,
)
from .structured import (
    GodotAdapterV1,
    RenPyAdapterV1,
    RpgMakerMVAdapterV1,
    RpgMakerMZAdapterV1,
    StructuredAdapterV1,
    UnityAdapterV1,
    UnrealAdapterV1,
)


_ADAPTERS: tuple[EngineAdapter, ...] = (
    RenPyAdapter(),
    RpgMakerMZAdapter(),
    RpgMakerMVAdapter(),
    GodotAdapter(),
    UnityAdapter(),
    UnrealAdapter(),
)

_ADAPTERS_V1: tuple[AdapterV1, ...] = (
    RenPyAdapterV1(),
    RpgMakerMZAdapterV1(),
    RpgMakerMVAdapterV1(),
    GodotAdapterV1(),
    UnityAdapterV1(),
    UnrealAdapterV1(),
)


def get_adapters() -> tuple[EngineAdapter, ...]:
    return _ADAPTERS


def get_adapters_v1() -> tuple[AdapterV1, ...]:
    return _ADAPTERS_V1


__all__ = [
    "AdapterCapabilityMatrix",
    "EngineAdapter",
    "CapabilityArea",
    "CapabilityDeclaration",
    "CapabilityStatus",
    "GodotAdapterV1",
    "RenPyAdapterV1",
    "RpgMakerMVAdapterV1",
    "RpgMakerMZAdapterV1",
    "StructuredAdapterV1",
    "UnityAdapterV1",
    "UnrealAdapterV1",
    "get_adapters",
    "get_adapters_v1",
]
