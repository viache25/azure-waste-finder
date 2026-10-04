"""Command line entry point: python -m waste_finder --subscription <id>

Exit codes: 0 = ok, 2 = usage or config error, 3 = monthly waste above --fail-over.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from waste_finder.config import (
    IGNORE_TAG,
    ConfigError,
    parse_currency,
    parse_downgrade_lookback,
    parse_fail_over,
    parse_formats,
    parse_min_savings,
    parse_rules,
    parse_snapshot_min_age,
    resolve_settings,
    split_below_threshold,
    split_ignored,
)
from waste_finder.export import EXPORTERS, FORMATS, RunInfo, render_summary
from waste_finder.pricing import price_findings, retail_api_fetcher
from waste_finder.registry import REGISTRY
from waste_finder.report import eur, render, summarize
from waste_finder.rules import Scope, find_waste, resource_graph_runner

EXIT_OK, EXIT_USAGE, EXIT_OVER_THRESHOLD = 0, 2, 3


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="waste-finder",
        description="Find wasted spend in Azure subscriptions.",
        epilog=(
            "Settings come from defaults < waste-finder.toml < these flags. "
            "Exit codes: 0 ok, 2 usage or config error, 3 monthly waste above --fail-over."
        ),
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
    p.add_argument(
        "--format",
        metavar="A,B",
        help=f"Comma-separated output formats ({', '.join(FORMATS)}; default md,html)",
    )
    p.add_argument(
        "--fail-over",
        type=float,
        metavar="AMOUNT",
        help="Exit with code 3 when the monthly waste is above this amount",
    )
    p.add_argument(
        "--snapshot-min-age",
        type=int,
        metavar="DAYS",
        help="Report disk snapshots at least this many days old (default 30)",
    )
    p.add_argument(
        "--downgrade-lookback",
        type=int,
        metavar="DAYS",
        help="Report SSD disks of VMs deallocated for at least this many days (default 30)",
    )
    p.add_argument(
        "--summary",
        metavar="FILE",
        help="Append a Markdown summary, e.g. $GITHUB_STEP_SUMMARY (empty value: no summary)",
    )
    p.add_argument("--config", type=Path, help="Config file (default: ./waste-finder.toml if it exists)")
    p.add_argument("--out-dir", type=Path, default=Path("reports"), help="Where to write report.<format>")
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
                "formats": parse_formats(args.format.split(",")) if args.format is not None else None,
                "fail_over": parse_fail_over(args.fail_over) if args.fail_over is not None else None,
                "snapshot_min_age_days": (
                    parse_snapshot_min_age(args.snapshot_min_age) if args.snapshot_min_age is not None else None
                ),
                "downgrade_lookback_days": (
                    parse_downgrade_lookback(args.downgrade_lookback) if args.downgrade_lookback is not None else None
                ),
            },
        )
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE

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
            return EXIT_USAGE
        currency = settings.currency
        scope_label, run_query = scope.label(), resource_graph_runner(scope)
        fetch = retail_api_fetcher(cache_file=Path(f".cache/prices-{currency.lower()}.json"), currency=currency)

    findings, ignored = split_ignored(find_waste(run_query, settings.rules, settings.min_age_days), settings.exclude)
    findings, below = split_below_threshold(price_findings(findings, fetch), settings.min_monthly_savings)

    run = RunInfo(scope_label, currency, args.demo, settings.min_monthly_savings)
    s = summarize(findings, ignored=len(ignored), below_threshold=len(below))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in settings.formats:
        if fmt in EXPORTERS:
            text = EXPORTERS[fmt](findings, s, run)
        else:
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
        path = args.out_dir / f"report.{fmt}"
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    if args.summary:  # empty when $GITHUB_STEP_SUMMARY is not set, e.g. outside GitHub Actions
        with Path(args.summary).open("a", encoding="utf-8") as summary_file:
            summary_file.write(render_summary(findings, s, run, settings.fail_over))

    print(f"{s.count} findings, ~{eur(s.monthly_eur, currency)} per month (~{eur(s.yearly_eur, currency)} per year)")
    if ignored:
        print(f"  {len(ignored)} ignored (tag {IGNORE_TAG}=true or exclude pattern)")
    if below:
        print(f"  {len(below)} below the threshold of {eur(settings.min_monthly_savings, currency)} per month")
    for f in sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True):
        print(f"  {eur(f.savings_eur, currency):>12}  {f.severity:<6}  {REGISTRY[f.rule].title_en:<32} {f.name}")
    print(f"Report: {', '.join(written)}")
    if settings.fail_over is not None and s.monthly_eur > settings.fail_over:
        print(
            f"error: monthly waste {eur(s.monthly_eur, currency)} is above --fail-over "
            f"{eur(settings.fail_over, currency)}",
            file=sys.stderr,
        )
        return EXIT_OVER_THRESHOLD
    return EXIT_OK
