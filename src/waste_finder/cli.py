"""Command line entry point: python -m waste_finder --subscription <id>"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from waste_finder.config import (
    IGNORE_TAG,
    ConfigError,
    parse_currency,
    parse_min_savings,
    parse_rules,
    resolve_settings,
    split_below_threshold,
    split_ignored,
)
from waste_finder.pricing import price_findings, retail_api_fetcher
from waste_finder.registry import REGISTRY
from waste_finder.report import eur, render, summarize
from waste_finder.rules import Scope, find_waste, resource_graph_runner


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="waste-finder",
        description="Find wasted spend in Azure subscriptions.",
        epilog="Settings come from defaults < waste-finder.toml < these flags.",
    )
    scope = p.add_mutually_exclusive_group()
    scope.add_argument(
        "--subscription",
        action="append",
        metavar="ID",
        help="Subscription ID; repeat for several (default: $AZURE_SUBSCRIPTION_ID)",
    )
    scope.add_argument("--all-subscriptions", action="store_true", help="Every subscription the credential can read")
    scope.add_argument("--management-group", metavar="ID", help="All subscriptions below this management group")
    p.add_argument("--rules", metavar="A,B", help=f"Comma-separated subset of rules ({', '.join(REGISTRY)})")
    p.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        help="Glob on the resource ID to ignore, e.g. '*/resourceGroups/rg-sandbox/*'; repeatable",
    )
    p.add_argument("--min-savings", type=float, metavar="AMOUNT", help="Leave out findings saving less per month")
    p.add_argument("--currency", metavar="CODE", help="Currency for Retail API prices (default EUR)")
    p.add_argument("--config", type=Path, help="Config file (default: ./waste-finder.toml if it exists)")
    p.add_argument("--out-dir", type=Path, default=Path("reports"), help="Where to write report.md / report.html")
    p.add_argument("--demo", action="store_true", help="Use built-in fake data, no Azure access needed")
    return p.parse_args(argv)


def scope_from_args(args: argparse.Namespace) -> Scope | None:
    if args.all_subscriptions:
        return Scope()
    if args.management_group:
        return Scope(management_group=args.management_group)
    subscriptions = args.subscription or (
        [os.environ["AZURE_SUBSCRIPTION_ID"]] if os.environ.get("AZURE_SUBSCRIPTION_ID") else []
    )
    return Scope(subscriptions=tuple(subscriptions)) if subscriptions else None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        settings = resolve_settings(
            args.config,
            {
                "rules": parse_rules(args.rules.split(",")) if args.rules is not None else None,
                "exclude": tuple(args.exclude) if args.exclude else None,
                "min_monthly_savings": parse_min_savings(args.min_savings) if args.min_savings is not None else None,
                "currency": parse_currency(args.currency) if args.currency else None,
            },
        )
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.demo:
        from waste_finder.demo import demo_fetcher, demo_runner

        if settings.currency != "EUR":
            print(f"note: demo prices are in EUR, ignoring currency {settings.currency}", file=sys.stderr)
        currency = "EUR"
        scope_label, run_query, fetch = "demo (Contoso)", demo_runner(), demo_fetcher()
    else:
        scope = scope_from_args(args)
        if scope is None:
            print(
                "error: pass --subscription, --all-subscriptions or --management-group, "
                "or set AZURE_SUBSCRIPTION_ID (see `az account show`)",
                file=sys.stderr,
            )
            return 2
        currency = settings.currency
        scope_label, run_query = scope.label(), resource_graph_runner(scope)
        fetch = retail_api_fetcher(cache_file=Path(f".cache/prices-{currency.lower()}.json"), currency=currency)

    findings, ignored = split_ignored(find_waste(run_query, settings.rules), settings.exclude)
    findings, below = split_below_threshold(price_findings(findings, fetch), settings.min_monthly_savings)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for fmt in ("md", "html"):
        text = render(
            findings,
            scope_label,
            fmt,
            demo=args.demo,
            ignored=len(ignored),
            below_threshold=len(below),
            min_savings=settings.min_monthly_savings,
            currency=currency,
        )
        (args.out_dir / f"report.{fmt}").write_text(text, encoding="utf-8")

    s = summarize(findings)
    print(f"{s.count} findings, ~{eur(s.monthly_eur, currency)} per month (~{eur(s.yearly_eur, currency)} per year)")
    if ignored:
        print(f"  {len(ignored)} ignored (tag {IGNORE_TAG}=true or exclude pattern)")
    if below:
        print(f"  {len(below)} below the threshold of {eur(settings.min_monthly_savings, currency)} per month")
    for f in sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True):
        print(f"  {eur(f.savings_eur, currency):>12}  {f.severity:<6}  {REGISTRY[f.rule].title_en:<32} {f.name}")
    print(f"Report: {args.out_dir / 'report.md'} and {args.out_dir / 'report.html'}")
    return 0
