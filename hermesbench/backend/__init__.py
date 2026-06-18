"""hermesbench.backend: execution environment backends.

The `tmux_isolated` backend is the v0.1 default. To add a new
backend, create a new module here and import it below.
"""

from __future__ import annotations

# Importing the module triggers the @register_backend decorator.
from hermesbench.backend import tmux_isolated

__all__ = ["tmux_isolated"]
