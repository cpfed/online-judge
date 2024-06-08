from dataclasses import asdict


def asdict_notnull(dc) -> dict:
    """Convert a dataclass to a dictionary, excluding None values."""
    return asdict(dc, dict_factory=lambda x: {k: v for (k, v) in x if v is not None})
