"""BusinessOS runtime version metadata."""

from importlib.metadata import PackageNotFoundError, version


def runtime_version() -> str:
    """Return installed distribution version or a source-tree fallback."""
    try:
        return version("businessos")
    except PackageNotFoundError:
        return "0.1.0+source"
