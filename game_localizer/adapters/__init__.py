from .base import EngineAdapter
from .renpy import RenPyAdapter
from .rpgmaker import RpgMakerMVAdapter, RpgMakerMZAdapter


_ADAPTERS: tuple[EngineAdapter, ...] = (
    RenPyAdapter(),
    RpgMakerMZAdapter(),
    RpgMakerMVAdapter(),
)


def get_adapters() -> tuple[EngineAdapter, ...]:
    return _ADAPTERS


__all__ = ["EngineAdapter", "get_adapters"]
