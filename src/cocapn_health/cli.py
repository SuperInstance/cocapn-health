#!/usr/bin/env python3
"""cocapn-health — CLI for fleet health checks.

Usage:
    cocapn-health                    # Check all fleet services
    cocapn-health --format json      # JSON output
    cocapn-health --format md        # Markdown report
    cocapn-health --format oneline   # One-line summary
    cocapn-health --watch 30         # Check every 30 seconds
    cocapn-health --system           # Check system (disk, memory, CPU)
    cocapn-health --serve 8902       # Start REST API on port 8902
"""
import argparse
import os
import sys
import time
from dataclasses import replace
from cocapn_health import HealthChecker, ServiceDef, FLEET_SERVICES, check_system


def main():
    parser = argparse.ArgumentParser(prog="cocapn-health", description="Fleet health checker")
    parser.add_argument("--format", choices=["json", "md", "oneline"], default="md", help="Output format")
    parser.add_argument("--watch", type=int, help="Watch mode: recheck every N seconds")
    parser.add_argument("--fail", action="store_true", help="Exit with error code if any service down")
    parser.add_argument("--host", default=None, help="Override default host (env: COCAPN_HEALTH_HOST)")
    parser.add_argument("--services", default=None, help="Comma-separated name:host:port list")
    parser.add_argument("--system", action="store_true", help="Include system checks (disk, memory, CPU)")
    parser.add_argument("--serve", type=int, metavar="PORT", nargs="?", const=8902,
                        help="Start REST API server on given port (default: 8902)")
    parser.add_argument("--ttl", type=float, default=30.0, help="API cache TTL in seconds (default: 30)")
    args = parser.parse_args()

    # REST API mode
    if args.serve is not None:
        from cocapn_health.api import run_api
        services = _resolve_services(args)
        run_api(host="0.0.0.0", port=args.serve, ttl=args.ttl, services=services)
        return

    services = _resolve_services(args)
    checker = HealthChecker(services)

    def run_check():
        results = checker.check_all()
        if args.system:
            results = results + check_system()
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


def _resolve_services(args):
    services = FLEET_SERVICES
    host = args.host or os.environ.get("COCAPN_HEALTH_HOST")
    if host:
        services = [replace(svc, host=host) for svc in services]

    if args.services:
        services = []
        for spec in args.services.split(","):
            parts = spec.split(":")
            if len(parts) == 2:
                name, port = parts
                services.append(ServiceDef(name, host or "127.0.0.1", int(port)))
            elif len(parts) == 3:
                name, h, port = parts
                services.append(ServiceDef(name, h, int(port)))
            else:
                print(f"Invalid service spec: {spec} (expected name:port or name:host:port)")
                sys.exit(1)
    return services


if __name__ == "__main__":
    main()
