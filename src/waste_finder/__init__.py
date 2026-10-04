"""Azure Waste Finder: find idle Azure resources and put a price tag on them."""

from importlib.metadata import PackageNotFoundError, version


def _installed_version() -> str:
    """Version of the installed package; setuptools-scm takes it from the git tag at build time."""
    try:
        return version("azure-waste-finder")
    except PackageNotFoundError:  # imported from a source tree that was never installed
        return "0.0.0+unknown"


__version__ = _installed_version()
