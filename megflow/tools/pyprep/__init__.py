"""initialize pyprep."""
from . import ransac as ransac  # noqa: F401
from .find_noisy_channels import NoisyChannels  # noqa: F401
from .prep_pipeline import PrepPipeline  # noqa: F401
from .reference import Reference  # noqa: F401

from . import _version

__version__ = _version.get_versions()["version"]
