"""Command line entry point: python -m waste_finder --subscription <id>"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from waste_finder.pricing import price_findings, retail_api_fetcher
from waste_finder.report import eur, render, summarize
from waste_finder.rules import find_waste, resource_graph_runner


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="waste-finder", description="Find wasted spend in an Azure subscription.")
    p.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID"),
                   help="Subscription ID (default: $AZURE_SUBSCRIPTION_ID)")
    p.add_argument("--out-dir", type=Path, default=Path("reports"), help="Where to write report.md / report.html")
    p.add_argument("--demo", action="store_true", help="Use built-in fake data, no Azure access needed")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.demo:
        from waste_finder.demo import demo_fetcher, demo_runner

        subscription, run_query, fetch = "demo (Contoso)", demo_runner(), demo_fetcher()
    else:
        if not args.subscription:
            print("error: pass --subscription or set AZURE_SUBSCRIPTION_ID (see `az account show`)", file=sys.stderr)
            return 2
        subscription = args.subscription
        run_query = resource_graph_runner(subscription)
        fetch = retail_api_fetcher(cache_file=Path(".cache/prices.json"))

    findings = price_findings(find_waste(run_query), fetch)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for fmt in ("md", "html"):
        (args.out_dir / f"report.{fmt}").write_text(
            render(findings, subscription, fmt, demo=args.demo), encoding="utf-8"
        )

    s = summarize(findings)
    print(f"{s.count} findings, ~{eur(s.monthly_eur)} per month (~{eur(s.yearly_eur)} per year)")
    for f in sorted(findings, key=lambda f: f.monthly_cost_eur or 0, reverse=True):
        print(f"  {eur(f.monthly_cost_eur):>12}  {f.rule:<20} {f.name}")
    print(f"Report: {args.out_dir / 'report.md'} and {args.out_dir / 'report.html'}")
    return 0
