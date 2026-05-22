"""Buglens sub-agent package."""

__all__ = ["SubAgent", "main"]


def __getattr__(name: str):
    if name == "SubAgent":
        from .agent import SubAgent

        return SubAgent
    if name == "main":
        from .cli import main

        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
