from .base import EngineAdapter
from .godot import GodotAdapter
from .renpy import RenPyAdapter
from .rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter
from .unity import UnityAdapter
from .unreal import UnrealAdapter


_ADAPTERS: tuple[EngineAdapter, ...] = (
    RenPyAdapter(),
    RpgMakerMZAdapter(),
    RpgMakerMVAdapter(),
    GodotAdapter(),
    UnityAdapter(),
    UnrealAdapter(),
)


def get_adapters() -> tuple[EngineAdapter, ...]:
    return _ADAPTERS


__all__ = ["EngineAdapter", "get_adapters"]
