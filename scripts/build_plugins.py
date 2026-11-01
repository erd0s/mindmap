#!/usr/bin/env python3
"""Compatibility command: generates only the standalone CLI, never plugins."""
from build_package import main

if __name__ == "__main__":
    raise SystemExit(main())
