"""Command-line interface.

Usage:
    python -m leadscraper "restaurants 10001 new york ny usa"
    python -m leadscraper "dentists 90210 beverly hills ca usa" --limit 60
    python -m leadscraper "cafes 400050 mumbai india" --source osm --verify-smtp
"""
from __future__ import annotations

import argparse
import logging
import sys

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import (BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
                           TextColumn, TimeElapsedColumn)
from rich.table import Table

from .config import Settings
from .output import write_outputs
from .pipeline import discover, enrich_leads
from .query import parse_query

console = Console()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="leadscraper",
        description="Scrape, enrich, verify and score business leads for owner outreach.",
    )
    p.add_argument("query", nargs="+",
                   help='search key, e.g. "restaurants 10001 new york ny usa"')
    p.add_argument("--source", choices=["google", "osm"], default="google",
                   help="business source (default: google)")
    p.add_argument("--limit", type=int, default=40, help="max businesses (default: 40)")
    p.add_argument("--out", default="output", help="output directory (default: ./output)")
    p.add_argument("--concurrency", type=int, default=8,
                   help="parallel website workers (default: 8)")
    p.add_argument("--max-pages", type=int, default=6,
                   help="max pages crawled per website (default: 6)")
    p.add_argument("--timeout", type=float, default=15.0,
                   help="per-request HTTP timeout seconds (default: 15)")
    p.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True,
                   help="run the browser headless (default: on)")
    p.add_argument("--respect-robots", action=argparse.BooleanOptionalAction, default=True,
                   help="honour robots.txt when crawling sites (default: on)")
    p.add_argument("--verify-smtp", action="store_true",
                   help="probe mailbox deliverability over SMTP (port 25 often blocked)")
    p.add_argument("--smtp-from", default="verify@example.com",
                   help="MAIL FROM address used for SMTP probing")
    p.add_argument("--include-discarded", action="store_true",
                   help="also write DISCARD-tier rows to the exported file")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def settings_from_args(a: argparse.Namespace) -> Settings:
    return Settings(
        source=a.source,
        limit=a.limit,
        headless=a.headless,
        concurrency=a.concurrency,
        out_dir=a.out,
        max_pages_per_site=a.max_pages,
        http_timeout=a.timeout,
        respect_robots=a.respect_robots,
        verify_smtp=a.verify_smtp,
        smtp_from=a.smtp_from,
        include_discarded=a.include_discarded,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )
    settings = settings_from_args(args)
    raw = " ".join(args.query)
    spec = parse_query(raw)

    console.rule("[bold cyan]leadscraper")
    console.print(f"[bold]Query:[/] {spec.raw}")
    console.print(
        f"[dim]what=[/]{spec.what!r} [dim]where=[/]{spec.where!r} "
        f"[dim]zip=[/]{spec.zip or '-'} [dim]source=[/]{settings.source} "
        f"[dim]limit=[/]{settings.limit}\n"
    )

    # Phase 1 -- discovery
    console.print("[cyan]Discovering businesses...[/] (this can take a bit for Maps)")
    leads, source_name = discover(spec, settings)
    if not leads:
        console.print("[yellow]No businesses found. Try --source osm, a broader query, "
                      "or check your network / Playwright install.[/]")
        return 1
    console.print(f"[green]Found {len(leads)} businesses[/] via {source_name}\n")

    # Phase 2 -- enrichment (with progress bar)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Enriching + scoring", total=len(leads))
        enriched = enrich_leads(
            leads, spec, settings,
            progress=lambda done, total: progress.update(task, completed=done, total=total),
        )

    summary = write_outputs(enriched, spec, settings)
    _print_summary(enriched, summary, settings)
    return 0


def _print_summary(leads, summary, settings: Settings) -> None:
    tiers = summary["tiers"]
    t = Table(title="Results by tier", show_edge=False)
    t.add_column("Tier"); t.add_column("Meaning"); t.add_column("Count", justify="right")
    t.add_row("T1", "Verified owner/founder email on company domain", str(tiers.get("T1", 0)))
    t.add_row("T2", "Decision-maker / personal email on company domain", str(tiers.get("T2", 0)))
    t.add_row("T3", "Owner email on free domain (confirmed)", str(tiers.get("T3", 0)))
    t.add_row("[dim]DISCARD[/]", "[dim]generic / invalid / closed / dup[/]", f"[dim]{tiers.get('DISCARD', 0)}[/]")
    console.print(t)

    top = [l for l in leads if l.tier != "DISCARD"][:10]
    if top:
        preview = Table(title="Top leads", show_lines=False)
        for col in ("Tier", "Score", "Business", "Owner", "Email", "Verified"):
            preview.add_column(col)
        for l in top:
            preview.add_row(l.tier, str(l.score), l.business_name[:30],
                            (l.owner_name or "-")[:20], l.email or "-",
                            "✓" if l.email_verified else ("mx" if l.email_status == "mx_ok" else "-"))
        console.print(preview)

    console.print(
        f"\n[bold green]Done.[/] {summary['qualified']} qualified / "
        f"{summary['total']} total businesses."
    )
    for label, path in summary["paths"].items():
        console.print(f"  [dim]{label}:[/] {path}")
    console.print(
        "\n[dim]Note: use scraped contacts responsibly and comply with the destination's "
        "ToS and outreach laws (CAN-SPAM / GDPR / local rules).[/]"
    )


if __name__ == "__main__":
    sys.exit(main())
