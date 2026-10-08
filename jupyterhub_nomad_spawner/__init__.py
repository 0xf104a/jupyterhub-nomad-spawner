from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("jupyterhub-nomad-spawner")
except PackageNotFoundError:  # pragma: no cover - running from a source checkout
    __version__ = "0.0.0"
