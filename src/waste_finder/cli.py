"""Command line entry point: python -m waste_finder --subscription <id>

Exit codes: 0 = ok, 2 = usage or config error, 3 = monthly waste above --fail-over.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from waste_finder import __version__
from waste_finder.config import (
    COST_SOURCES,
    IGNORE_TAG,
    ConfigError,
    parse_cost_source,
    parse_currency,
    parse_downgrade_lookback,
    parse_fail_over,
    parse_formats,
    parse_min_savings,
    parse_rules,
    parse_snapshot_min_age,
    resolve_settings,
    split_below_threshold,
    split_free,
    split_ignored,
)
from waste_finder.costs import (
    CostPeriod,
    CostQuery,
    apply_actual_costs,
    collect_actual_costs,
    cost_management_query,
    last_days,
)
from waste_finder.export import EXPORTERS, FORMATS, RunInfo, render_summary
from waste_finder.pricing import price_findings, retail_api_fetcher
from waste_finder.registry import REGISTRY
from waste_finder.report import cleanup_order, eur, render, signed_eur, summarize
from waste_finder.rules import Scope, find_waste, resource_graph_runner
from waste_finder.trend import PreviousReport, compare, load_previous

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
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
        "--cost-source",
        metavar="SOURCE",
        help=(
            f"{' or '.join(COST_SOURCES)} (default retail): 'actual' uses the amortized cost of the last 30 days "
            "from Cost Management (role Cost Management Reader), retail prices as fallback per finding"
        ),
    )
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
    p.add_argument(
        "--previous",
        metavar="REPORT_JSON",
        help=(
            "report.json of an earlier run: the report shows new, resolved and unchanged findings and the change "
            "per month (--demo uses a built-in previous run; empty value: no trend)"
        ),
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


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


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
                "cost_source": parse_cost_source(args.cost_source) if args.cost_source is not None else None,
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
        run_currency = "EUR" if args.demo else settings.currency  # demo prices are in EUR
        previous: PreviousReport | None = load_previous(Path(args.previous)) if args.previous else None
        if previous and previous.currency != run_currency:
            raise ConfigError(
                f"--previous {args.previous} is in {previous.currency}, this run in {run_currency}; "
                "amounts cannot be compared"
            )
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_USAGE

    period: CostPeriod | None = last_days(date.today()) if settings.cost_source == "actual" else None
    cost_query: CostQuery | None = None
    if args.demo:
        from waste_finder.demo import demo_cost_query, demo_fetcher, demo_previous_report, demo_runner

        if settings.currency != "EUR":
            print(f"note: demo prices are in EUR, ignoring currency {settings.currency}", file=sys.stderr)
        currency = "EUR"
        scope_label, run_query, fetch = "demo (Contoso)", demo_runner(), demo_fetcher()
        if period:
            cost_query = demo_cost_query()
        if args.previous is None:  # the demo report shows a trend against a built-in earlier run
            previous = demo_previous_report()
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
        if period:
            cost_query = cost_management_query(period)

    findings, ignored = split_ignored(find_waste(run_query, settings.rules, settings.min_age_days), settings.exclude)
    findings = price_findings(findings, fetch)
    if cost_query and period:
        # Actual costs replace retail prices where Cost Management has a row; everything else stays retail.
        costs = collect_actual_costs(cost_query, (f.subscription_id for f in findings if f.subscription_id), warn=_warn)
        applied = apply_actual_costs(findings, costs, currency, period)
        if applied.other_currency:
            print(
                f"note: Cost Management reports {applied.other_currency} finding(s) in another currency than "
                f"{currency}; they keep retail prices (set --currency to the billing currency)",
                file=sys.stderr,
            )
    # Free clean-up findings get their own section, outside the total and the savings threshold.
    findings, cleanup = split_free(findings)
    findings, below = split_below_threshold(findings, settings.min_monthly_savings)

    run = RunInfo(scope_label, currency, args.demo, settings.min_monthly_savings, settings.cost_source, period)
    s = summarize(findings, ignored=len(ignored), below_threshold=len(below), cleanup=len(cleanup))
    trend = compare(previous, findings, settings.rules) if previous else None
    args.out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in settings.formats:
        if fmt in EXPORTERS:
            text = EXPORTERS[fmt](findings, s, run, cleanup, trend)
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
                cleanup=cleanup,
                cost_source=settings.cost_source,
                cost_period=period,
                trend=trend,
            )
        path = args.out_dir / f"report.{fmt}"
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    if args.summary:  # empty when $GITHUB_STEP_SUMMARY is not set, e.g. outside GitHub Actions
        with Path(args.summary).open("a", encoding="utf-8") as summary_file:
            summary_file.write(render_summary(findings, s, run, settings.fail_over, trend))

    print(f"{s.count} findings, ~{eur(s.monthly_eur, currency)} per month (~{eur(s.yearly_eur, currency)} per year)")
    if period:
        print(f"  {s.actual} priced from Cost Management ({period.start} to {period.end}), the rest from retail prices")
    if trend:
        print(
            f"  trend since {trend.previous.generated}: {signed_eur(trend.monthly_change, currency)} per month "
            f"({len(trend.new)} new, {len(trend.resolved)} resolved, {len(trend.unchanged)} unchanged)"
        )
    if ignored:
        print(f"  {len(ignored)} ignored (tag {IGNORE_TAG}=true or exclude pattern)")
    if below:
        print(f"  {len(below)} below the threshold of {eur(settings.min_monthly_savings, currency)} per month")
    for f in sorted(findings, key=lambda f: f.savings_eur or 0, reverse=True):
        print(f"  {eur(f.savings_eur, currency):>12}  {f.severity:<6}  {REGISTRY[f.rule].title_en:<32} {f.name}")
    if cleanup:
        print(f"  {len(cleanup)} free clean-up finding(s), not in the total:")
        for f in cleanup_order(cleanup):
            print(f"  {'free':>12}  {f.severity:<6}  {REGISTRY[f.rule].title_en:<32} {f.name}")
    print(f"Report: {', '.join(written)}")
    if settings.fail_over is not None and s.monthly_eur > settings.fail_over:
        print(
            f"error: monthly waste {eur(s.monthly_eur, currency)} is above --fail-over "
            f"{eur(settings.fail_over, currency)}",
            file=sys.stderr,
        )
        return EXIT_OVER_THRESHOLD
    return EXIT_OK
