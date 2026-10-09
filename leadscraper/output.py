"""Write results to CSV + Excel."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime

from .config import Settings
from .models import Lead
from .query import QuerySpec

log = logging.getLogger(__name__)


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:50] or "leads"


def write_outputs(leads: list[Lead], spec: QuerySpec, settings: Settings) -> dict:
    import pandas as pd

    os.makedirs(settings.out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{_slug(spec.raw)}_{stamp}"

    qualified = [l for l in leads if l.tier in ("T1", "T2", "T3")]
    df_all = pd.DataFrame([l.to_row() for l in leads]) if leads else pd.DataFrame()
    df_q = pd.DataFrame([l.to_row() for l in qualified]) if qualified else pd.DataFrame()

    # The qualified file is the deliverable. The full dump (incl. DISCARD) is
    # written when asked for, or whenever there are no qualified leads so the
    # user always has something to inspect.
    write_all = settings.include_discarded or df_q.empty

    paths: dict[str, str] = {}
    q_csv = os.path.join(settings.out_dir, f"{base}_qualified.csv")
    df_q.to_csv(q_csv, index=False, encoding="utf-8-sig")
    paths["qualified_csv"] = q_csv

    if write_all:
        all_csv = os.path.join(settings.out_dir, f"{base}_all.csv")
        df_all.to_csv(all_csv, index=False, encoding="utf-8-sig")
        paths["all_csv"] = all_csv

    try:
        xlsx = os.path.join(settings.out_dir, f"{base}.xlsx")
        with pd.ExcelWriter(xlsx, engine="openpyxl") as xw:
            (df_q if not df_q.empty else df_all).to_excel(xw, sheet_name="Qualified", index=False)
            if write_all:
                df_all.to_excel(xw, sheet_name="All", index=False)
        paths["xlsx"] = xlsx
    except Exception as exc:
        log.warning("Excel export skipped (%s). CSVs are written.", exc)

    return {
        "paths": paths,
        "total": len(leads),
        "qualified": len(qualified),
        "tiers": _tier_counts(leads),
    }


def _tier_counts(leads: list[Lead]) -> dict[str, int]:
    counts = {"T1": 0, "T2": 0, "T3": 0, "DISCARD": 0}
    for l in leads:
        counts[l.tier] = counts.get(l.tier, 0) + 1
    return counts
