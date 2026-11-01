"""Durable project maps shared by coding agents."""

import sys

# Generated plugin trees are immutable build artifacts. Hosts and validators may
# import the package directly instead of using our launchers, so enforce this at
# the earliest package boundary as well as in those entry points.
sys.dont_write_bytecode = True

__version__ = "0.3.1"
