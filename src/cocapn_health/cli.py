#!/usr/bin/env python3
"""cocapn-health — CLI for fleet health checks.

Usage:
    cocapn-health                    # Check all fleet services
    cocapn-health --format json      # JSON output
    cocapn-health --format md        # Markdown report
    cocapn-health --format oneline   # One-line summary
    cocapn-health --watch 30         # Check every 30 seconds
"""
import argparse
import sys
import time
from cocapn_health import HealthChecker, FLEET_SERVICES


def main():
    parser = argparse.ArgumentParser(prog="cocapn-health", description="Fleet health checker")
    parser.add_argument("--format", choices=["json", "md", "oneline"], default="md", help="Output format")
    parser.add_argument("--watch", type=int, help="Watch mode: recheck every N seconds")
    parser.add_argument("--fail", action="store_true", help="Exit with error code if any service down")
    args = parser.parse_args()

    checker = HealthChecker(FLEET_SERVICES)

    def run_check():
        results = checker.check_all()
        print(checker.report(results, format=args.format))
        down = sum(1 for r in results if not r.ok)
        return down == 0

    if args.watch:
        try:
            while True:
                ok = run_check()
                print(f"\n--- Rechecking in {args.watch}s ---\n")
                time.sleep(args.watch)
        except KeyboardInterrupt:
            pass
    else:
        ok = run_check()
        if args.fail and not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
