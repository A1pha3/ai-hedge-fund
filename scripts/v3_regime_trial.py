#!/usr/bin/env python3
"""Operator entrypoint for the BTST regime paired shadow trial CLI.

A thin ``sys.exit(main())`` wrapper over :mod:`src.cli.v3_regime_trial`.
See that module's docstring for the four subcommands and the security
boundary. Run with ``--help`` for usage.

    python scripts/v3_regime_trial.py validate --root PATH --trial-id ID
"""

from __future__ import annotations

import sys

from src.cli.v3_regime_trial import main

if __name__ == "__main__":
    sys.exit(main())
