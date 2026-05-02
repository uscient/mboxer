from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("uscient-mboxer")
except PackageNotFoundError:
    __version__ = "unknown"
