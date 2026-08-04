from .base import EngineAdapter


def get_adapters() -> tuple[EngineAdapter, ...]:
    return ()


__all__ = ["EngineAdapter", "get_adapters"]
