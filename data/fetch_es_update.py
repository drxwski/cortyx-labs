#!/usr/bin/env python3
"""
ES Futures 5-Minute Data Updater
=================================
Downloads available ES 5-min bars from yfinance and merges them with the
existing historical CSV dataset.

yfinance limitation: Only ~60 days of 5-min intraday data are available
for free. This script fills in what is available and documents any gap.

Usage:
    python fetch_es_update.py [--raw-csv PATH] [--output PATH]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# ── Paths ─────────────────────────────────────────────────────────────────────
DEFAULT_RAW_CSV = Path.home() / "Downloads/Vantyx Trading Algorithm/data/raw/ES_5min_18yr.csv"
DEFAULT_OUTPUT  = Path.home() / "Downloads/Vantyx Trading Algorithm/data/raw/ES_5min_18yr.csv"
CORTYX_RAW      = Path(__file__).parent / "raw"
CORTYX_CLEANED  = Path(__file__).parent / "cleaned"

# ── QC thresholds ─────────────────────────────────────────────────────────────
ATR_LOOKBACK = 14 * 72   # 14 trading days × 72 bars/day (session bars)
SPIKE_MULT   = 5
GAP_MINUTES  = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_existing(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_yfinance_5min() -> pd.DataFrame:
    """Fetch up to 60 days of ES 5-min bars from yfinance."""
    print("Fetching ES=F 5-min data from yfinance (60-day limit)...")
    ticker = yf.Ticker("ES=F")
    raw = ticker.history(period="60d", interval="5m")

    if raw.empty:
        raise RuntimeError("yfinance returned empty dataframe for ES=F 5m")

    # Normalize to UTC then strip tz, rename columns
    raw.index = raw.index.tz_convert("UTC").tz_localize(None)
    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index.name = "timestamp"
    df = df.reset_index()
    df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    df["volume"] = df["volume"].astype(int)

    # Round prices to ES tick size (0.25)
    for col in ["open", "high", "low", "close"]:
        df[col] = (df[col] / 0.25).round() * 0.25

    df = df.sort_values("timestamp").reset_index(drop=True)
    print(f"  Fetched {len(df):,} bars: {df['timestamp'].min()} → {df['timestamp'].max()}")
    return df


def merge_dataframes(existing: pd.DataFrame, new: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Append new bars that come after the last existing bar. Returns (merged, added_count)."""
    last_ts = existing["timestamp"].max()
    added = new[new["timestamp"] > last_ts].copy()
    added_count = len(added)

    if added_count == 0:
        return existing.copy(), 0

    merged = pd.concat([existing, added], ignore_index=True)
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    return merged, added_count


def run_qc(df: pd.DataFrame) -> dict:
    """Run the full quality check suite. Returns results dict."""
    results = {}

    results["total_rows"] = len(df)
    results["date_min"] = str(df["timestamp"].min())
    results["date_max"] = str(df["timestamp"].max())

    # Nulls
    results["null_count"] = int(df.isnull().sum().sum())

    # Duplicates
    results["duplicate_rows"] = int(df.duplicated().sum())

    # Price anomalies: high < low
    hl_anomalies = (df["high"] < df["low"]).sum()
    results["high_lt_low"] = int(hl_anomalies)

    # Open/Close outside High-Low range
    oc_outside = (
        (df["open"] < df["low"]) | (df["open"] > df["high"]) |
        (df["close"] < df["low"]) | (df["close"] > df["high"])
    ).sum()
    results["oc_outside_hl"] = int(oc_outside)

    # Zero volume
    results["zero_volume"] = int((df["volume"] == 0).sum())

    # Gaps > GAP_MINUTES
    df_sorted = df.sort_values("timestamp")
    deltas = df_sorted["timestamp"].diff().dt.total_seconds() / 60
    gap_mask = deltas > GAP_MINUTES
    results["gaps_over_30min"] = int(gap_mask.sum())

    # Spike detection (range > SPIKE_MULT × rolling ATR)
    bar_range = df_sorted["high"] - df_sorted["low"]
    rolling_atr = bar_range.rolling(ATR_LOOKBACK, min_periods=10).mean()
    spikes = (bar_range > SPIKE_MULT * rolling_atr).sum()
    results["spike_bars"] = int(spikes)

    return results


def format_qc_report(results: dict, added: int, gap_start: str, gap_end: str) -> str:
    """Format a QC results markdown block."""
    status = "✅ PASS" if (
        results["null_count"] == 0
        and results["duplicate_rows"] == 0
        and results["high_lt_low"] == 0
        and results["oc_outside_hl"] == 0
        and results["zero_volume"] == 0
        and results["spike_bars"] == 0
    ) else "⚠️ ISSUES FOUND"

    lines = [
        f"**QC Status**: {status}",
        "",
        "| Check | Result |",
        "|-------|--------|",
        f"| Total rows | {results['total_rows']:,} |",
        f"| Date range | {results['date_min']} → {results['date_max']} |",
        f"| Bars added this run | {added:,} |",
        f"| Null values | {('✅ 0' if results['null_count'] == 0 else ('❌ ' + str(results['null_count'])))} |",
        f"| Duplicate rows | {('✅ 0' if results['duplicate_rows'] == 0 else ('❌ ' + str(results['duplicate_rows'])))} |",
        f"| High < Low anomalies | {('✅ 0' if results['high_lt_low'] == 0 else ('❌ ' + str(results['high_lt_low'])))} |",
        f"| Open/Close outside H-L | {('✅ 0' if results['oc_outside_hl'] == 0 else ('❌ ' + str(results['oc_outside_hl'])))} |",
        f"| Zero-volume bars | {('✅ 0' if results['zero_volume'] == 0 else ('⚠️ ' + str(results['zero_volume'])))} |",
        f"| Gaps > 30min | ⚠️ {results['gaps_over_30min']:,} (expected: weekends/holidays/session breaks) |",
        f"| Spike bars (range > 5x ATR) | {('✅ 0' if results['spike_bars'] == 0 else ('⚠️ ' + str(results['spike_bars'])))} |",
        "",
    ]
    if gap_start and gap_end:
        lines += [
            f"**⚠️ DATA GAP**: 5-min resolution unavailable from `{gap_start}` to `{gap_end}`.",
            "yfinance only provides ~60 days of intraday history at no cost.",
            "To backfill this gap, a paid provider is required (Polygon.io, Databento, or similar).",
            "",
        ]
    return "\n".join(lines)


def update_obsidian_log(log_path: Path, date_str: str, results: dict, added: int,
                        gap_start: str, gap_end: str) -> None:
    text = log_path.read_text()

    gap_note = ""
    if gap_start and gap_end:
        gap_note = (
            f"\n- **⚠️ 5-min gap**: `{gap_start}` → `{gap_end}` — no free intraday source covers this period. "
            "Recommend Polygon.io or Databento to backfill."
        )

    new_row = (
        f"| {date_str} | Market Data Analyst (COR-4) "
        f"| ES_5min_18yr.csv | {results['total_rows']:,} "
        f"| {added:,} bars appended via yfinance (60d window){gap_note.replace(chr(10), ' ')} "
        f"| {'CLEAN' if results['null_count']==0 and results['high_lt_low']==0 and results['zero_volume']==0 else 'ISSUES'} — CURRENT TO {results['date_max'][:10]} |\n"
    )

    # Insert after the table header (find the separator line)
    lines = text.splitlines(keepends=True)
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith("|---"):
            insert_at = i + 1
            break

    if insert_at is not None:
        lines.insert(insert_at, new_row)
    else:
        lines.append("\n" + new_row)

    # Add notes section
    notes = f"\n### {date_str} Notes (COR-4 — Live Data Pipeline)\n"
    notes += f"- **Bars added**: {added:,} (yfinance `ES=F` 5-min, 60-day window)\n"
    notes += f"- **New date range**: {results['date_min'][:10]} → {results['date_max'][:10]}\n"
    if gap_start and gap_end:
        notes += f"- **⚠️ 5-min gap not filled**: `{gap_start}` → `{gap_end}` — requires paid data source\n"
    notes += f"- **QC**: nulls={results['null_count']}, dups={results['duplicate_rows']}, "
    notes += f"H<L={results['high_lt_low']}, O/C outside H-L={results['oc_outside_hl']}, "
    notes += f"zero-vol={results['zero_volume']}, gaps>30m={results['gaps_over_30min']}\n"
    notes += "- **Pipeline**: `cortyx-labs/data/fetch_es_update.py`\n"

    lines.append(notes)
    log_path.write_text("".join(lines))
    print(f"Updated Obsidian log: {log_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ES 5-min data updater")
    parser.add_argument("--raw-csv", type=Path, default=DEFAULT_RAW_CSV,
                        help="Path to existing raw CSV")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="Output path for merged CSV (can be same as input)")
    parser.add_argument("--obsidian-log", type=Path,
                        default=Path.home() / "ObsidianVault/Cortyx-Labs/01_Data-Engineering/Data-Ingestion-Log.md",
                        help="Path to Obsidian data ingestion log")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run QC and report but do not write files")
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")

    # 1. Load existing data
    print(f"Loading existing data from {args.raw_csv}...")
    existing = load_existing(args.raw_csv)
    last_existing_ts = existing["timestamp"].max()
    print(f"  Existing: {len(existing):,} rows, last bar: {last_existing_ts}")

    # 2. Fetch new data
    new_data = fetch_yfinance_5min()
    yf_start = str(new_data["timestamp"].min())[:10]

    # Determine gap
    gap_start = str(last_existing_ts + pd.Timedelta(minutes=5))[:16]
    gap_end   = str(new_data["timestamp"].min() - pd.Timedelta(minutes=5))[:16]
    has_gap = new_data["timestamp"].min() > last_existing_ts + pd.Timedelta(hours=1)

    if has_gap:
        print(f"\n⚠️  5-min data gap: {gap_start} → {gap_end}")
        print(f"   yfinance only provides ~60 days. Gap requires a paid provider to fill.")
    else:
        gap_start = gap_end = ""

    # 3. Merge
    merged, added = merge_dataframes(existing, new_data)
    print(f"\nMerge result: {len(merged):,} rows total, {added:,} new bars appended")

    # 4. QC
    print("\nRunning quality checks...")
    results = run_qc(merged)
    print(format_qc_report(results, added, gap_start, gap_end))

    if args.dry_run:
        print("DRY RUN — no files written.")
        return

    if added == 0:
        print("No new bars to add. Dataset already up to date.")
        return

    # 5. Save merged CSV
    args.output.parent.mkdir(parents=True, exist_ok=True)
    merged["timestamp"] = merged["timestamp"].astype(str).str[:19]
    merged.to_csv(args.output, index=False)
    print(f"Saved merged CSV: {args.output} ({len(merged):,} rows)")

    # 6. Run data_pipeline.py to regenerate clean parquet
    pipeline_script = Path.home() / "Downloads/Vantyx Trading Algorithm/data_pipeline.py"
    cortyx_clean = CORTYX_CLEANED / "ES_5min_session.parquet"
    vantyx_clean = Path.home() / "Downloads/Vantyx Trading Algorithm/data/clean/ES_5min_session.parquet"
    if pipeline_script.exists():
        import subprocess
        print(f"\nRegenerating clean parquet via {pipeline_script.name}...")
        for out_path in [cortyx_clean, vantyx_clean]:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(
                ["python3", str(pipeline_script),
                 "--input", str(args.output),
                 "--output", str(out_path)],
                capture_output=True, text=True
            )
            if r.returncode == 0:
                print(f"  ✅ Clean parquet: {out_path}")
            else:
                print(f"  ⚠️  data_pipeline.py stderr: {r.stderr[:300]}")

    # 7. Update Obsidian log
    if args.obsidian_log.exists():
        update_obsidian_log(args.obsidian_log, today, results, added, gap_start, gap_end)
    else:
        print(f"⚠️  Obsidian log not found: {args.obsidian_log}")

    # 8. Write QC report to cortyx-labs/research/
    qc_report_path = Path.home() / f"cortyx-labs/research/data_engineering_update_{today}.md"
    qc_content = f"# Data Engineering Update — {today}\n\n"
    qc_content += f"**Agent**: Market Data Analyst (COR-4)  \n"
    qc_content += f"**Issue**: [COR-4](/COR/issues/COR-4)\n\n"
    qc_content += "## Summary\n\n"
    qc_content += f"Appended `{added:,}` bars via yfinance `ES=F` 5-min feed (60-day free window).\n\n"
    if has_gap:
        qc_content += f"**⚠️ Partial backfill**: A {len(pd.bdate_range(gap_start[:10], gap_end[:10]))}-trading-day gap "
        qc_content += f"(`{gap_start[:10]}` → `{gap_end[:10]}`) at 5-min resolution "
        qc_content += "could not be filled. A paid data provider (Polygon.io, Databento) is required to close it.\n\n"
    qc_content += "## Quality Check Results\n\n"
    qc_content += format_qc_report(results, added, gap_start if has_gap else "", gap_end if has_gap else "")
    qc_report_path.write_text(qc_content)
    print(f"QC report: {qc_report_path}")

    print("\n✅ Pipeline complete.")
    print(f"   Data current to: {results['date_max'][:10]}")
    if has_gap:
        print(f"   ⚠️  Gap remaining: {gap_start[:10]} → {gap_end[:10]} (paid source needed)")


if __name__ == "__main__":
    main()
