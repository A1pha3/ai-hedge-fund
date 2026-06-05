#!/usr/bin/env python3
"""CLI entry point for lookback audit.

Usage:
    python scripts/run_lookback_audit.py --date 20260505 --days 30
    python scripts/run_lookback_audit.py --date 20260505 --days 30 --json
    python scripts/run_lookback_audit.py --date 20260505 --artifact-root data/reports/my_report/selection_artifacts
"""

from src.research.lookback_audit import main

if __name__ == "__main__":
    main()
