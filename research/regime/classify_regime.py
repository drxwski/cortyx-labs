#!/usr/bin/env python3
"""
Daily ES Futures Market Regime Classifier
==========================================
Usage:
    python classify_regime.py [--data PATH] [--log PATH] [--date DATE] [--no-append]

Arguments:
    --data PATH     Path to the 5min ES parquet file (default: auto-detect)
    --log PATH      Path to the Regime Classification Log markdown file
    --date DATE     Analysis date in YYYY-MM-DD (default: today)
    --no-append     Print classification only; do not append to log

Output:
    - Prints regime classification to stdout
    - Appends a row to the Regime Classification Log markdown file

Classification Schema:
    Primary regimes (pick the highest-priority that applies):
        HIGH_VOLATILITY   ATR(20d) > 1.5x 20d average ATR, or annualized vol > 25%
        LOW_VOLATILITY    ATR(20d) < 0.7x 20d average ATR, or annualized vol < 10%
        TRENDING_BULL     Trend score >= 3/5 AND 20d return > 0%
        TRENDING_BEAR     Trend score <= 1/5 AND 20d return < 0%
        CHOPPY_RANGE      None of the above

    Secondary tags (all that apply):
        ABOVE_200MA / BELOW_200MA
        ABOVE_50MA  / BELOW_50MA
        ABOVE_20MA  / BELOW_20MA
        GAP_UP (open > prev close + 0.5pt) / GAP_DOWN / FLAT
        INSIDE_VALUE_AREA / OUTSIDE_VALUE_AREA (based on 20-day volume POC ±1.5 ATR)
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Paths (auto-detect from common locations)
# ---------------------------------------------------------------------------
SEARCH_PATHS = [
    Path.home() / "Downloads/Vantyx Trading Algorithm/data/clean/ES_5min_session.parquet",
    Path.home() / "cortyx-labs/data/clean/ES_5min_session.parquet",
    Path.home() / "cortyx-labs/data/ES_5min_session.parquet",
]

DEFAULT_LOG = Path.home() / "ObsidianVault/Cortyx-Labs/01_Data-Engineering/Regime-Classification-Log.md"


def find_data_file() -> Path:
    for p in SEARCH_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find ES_5min_session.parquet. Pass --data PATH explicitly."
    )


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------
def build_daily_ohlcv(df_5min: pd.DataFrame) -> pd.DataFrame:
    """Resample 5-min bars to daily OHLCV (session close = last bar of day)."""
    daily = (
        df_5min.resample("D")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    daily.index = daily.index.normalize()
    return daily


def compute_atr(daily: pd.DataFrame, window: int = 20) -> pd.Series:
    """Average True Range using Wilder smoothing."""
    high = daily["high"]
    low = daily["low"]
    prev_close = daily["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(window).mean()


def classify(df_5min: pd.DataFrame, as_of_date: date | None = None) -> dict:
    """Return a classification dict for the given as_of_date (or last available bar)."""
    daily = build_daily_ohlcv(df_5min)

    if as_of_date:
        # Use all data up to and including as_of_date
        target = pd.Timestamp(as_of_date)
        daily = daily[daily.index <= target]

    if len(daily) < 210:
        raise ValueError("Not enough daily bars for classification (need 210+).")

    last = daily.iloc[-1]
    last_date = daily.index[-1].date()
    prev = daily.iloc[-2]

    close = last["close"]

    # Moving averages
    sma20 = daily["close"].rolling(20).mean().iloc[-1]
    sma50 = daily["close"].rolling(50).mean().iloc[-1]
    sma200 = daily["close"].rolling(200).mean().iloc[-1]

    # Returns
    ret_5d = (close - daily["close"].iloc[-6]) / daily["close"].iloc[-6] * 100
    ret_20d = (close - daily["close"].iloc[-21]) / daily["close"].iloc[-21] * 100
    ret_60d = (close - daily["close"].iloc[-61]) / daily["close"].iloc[-61] * 100

    # Volatility
    log_returns = np.log(daily["close"] / daily["close"].shift(1)).dropna()
    vol_20d_ann = log_returns.iloc[-20:].std() * np.sqrt(252) * 100
    vol_60d_ann = log_returns.iloc[-60:].std() * np.sqrt(252) * 100

    # ATR
    atr_series = compute_atr(daily, 20)
    atr_20d = atr_series.iloc[-1]
    atr_avg_20d = atr_series.iloc[-20:].mean()

    # 52-week metrics
    high_52w = daily["high"].iloc[-252:].max()
    drawdown = (close - high_52w) / high_52w * 100

    # Trend score (0-5)
    trend_score = sum([
        close > sma20,
        close > sma50,
        close > sma200,
        ret_5d > 0,
        ret_20d > 0,
    ])

    # ---- Primary regime classification ----
    atr_ratio = atr_20d / atr_avg_20d if atr_avg_20d > 0 else 1.0

    if vol_20d_ann > 25 or atr_ratio > 1.5:
        # Further split into bull/bear high-vol
        if trend_score >= 3 and ret_20d > 0:
            primary = "HIGH_VOLATILITY / BULL"
        else:
            primary = "HIGH_VOLATILITY / BEAR"
    elif vol_20d_ann < 10 or atr_ratio < 0.7:
        primary = "LOW_VOLATILITY"
    elif trend_score >= 3 and ret_20d > 0:
        primary = "TRENDING_BULL"
    elif trend_score <= 1 and ret_20d < 0:
        primary = "TRENDING_BEAR"
    else:
        primary = "CHOPPY_RANGE"

    # ---- Secondary tags ----
    secondary_tags = []

    # MA tags
    secondary_tags.append("ABOVE_200MA" if close > sma200 else "BELOW_200MA")
    secondary_tags.append("ABOVE_50MA" if close > sma50 else "BELOW_50MA")
    secondary_tags.append("ABOVE_20MA" if close > sma20 else "BELOW_20MA")

    # Gap tag (vs previous session close)
    prev_close = prev["close"]
    open_today = last["open"]
    gap = open_today - prev_close
    if gap > 0.5:
        secondary_tags.append("GAP_UP")
    elif gap < -0.5:
        secondary_tags.append("GAP_DOWN")
    else:
        secondary_tags.append("FLAT")

    # Value area (rough proxy: 20d high/low midpoint ±1.5 ATR)
    range_20d_mid = (daily["high"].iloc[-20:].max() + daily["low"].iloc[-20:].min()) / 2
    va_upper = range_20d_mid + 1.5 * atr_20d
    va_lower = range_20d_mid - 1.5 * atr_20d
    if va_lower <= close <= va_upper:
        secondary_tags.append("INSIDE_VALUE_AREA")
    else:
        secondary_tags.append("OUTSIDE_VALUE_AREA")

    return {
        "analysis_date": datetime.now().strftime("%Y-%m-%d"),
        "last_bar_date": str(last_date),
        "last_close": round(close, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "ret_5d": round(ret_5d, 2),
        "ret_20d": round(ret_20d, 2),
        "ret_60d": round(ret_60d, 2),
        "vol_20d_ann": round(vol_20d_ann, 1),
        "vol_60d_ann": round(vol_60d_ann, 1),
        "atr_20d": round(atr_20d, 2),
        "atr_avg_20d": round(atr_avg_20d, 2),
        "atr_ratio": round(atr_ratio, 2),
        "high_52w": round(high_52w, 2),
        "drawdown_pct": round(drawdown, 2),
        "trend_score": trend_score,
        "primary_regime": primary,
        "secondary_tags": secondary_tags,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(c: dict) -> None:
    tag_str = ", ".join(c["secondary_tags"])
    stale = c["last_bar_date"] != c["analysis_date"]
    stale_note = f"  ⚠️  Data is stale (last bar: {c['last_bar_date']})" if stale else ""

    print(f"""
╔══════════════════════════════════════════════════════════╗
║         ES FUTURES — DAILY REGIME CLASSIFICATION         ║
╚══════════════════════════════════════════════════════════╝

  Analysis date : {c['analysis_date']}{stale_note}
  Last bar      : {c['last_bar_date']}
  Last close    : {c['last_close']}

  ── Price vs MAs ──────────────────────────────────────────
  SMA20  : {c['sma20']:>10.2f}  ({'ABOVE ✅' if c['last_close'] > c['sma20'] else 'BELOW ⚠️'})
  SMA50  : {c['sma50']:>10.2f}  ({'ABOVE ✅' if c['last_close'] > c['sma50'] else 'BELOW ⚠️'})
  SMA200 : {c['sma200']:>10.2f}  ({'ABOVE ✅' if c['last_close'] > c['sma200'] else 'BELOW ⚠️'})

  ── Returns ───────────────────────────────────────────────
  5d  : {c['ret_5d']:>+7.2f}%
  20d : {c['ret_20d']:>+7.2f}%
  60d : {c['ret_60d']:>+7.2f}%

  ── Volatility & ATR ──────────────────────────────────────
  Vol 20d (ann) : {c['vol_20d_ann']:>6.1f}%
  Vol 60d (ann) : {c['vol_60d_ann']:>6.1f}%
  ATR(20d)      : {c['atr_20d']:>6.2f} pts
  ATR ratio     : {c['atr_ratio']:>6.2f}x

  ── 52-Week ───────────────────────────────────────────────
  52w high      : {c['high_52w']:>10.2f}
  Drawdown      : {c['drawdown_pct']:>+7.2f}%

  ── Trend Score : {c['trend_score']}/5 ─────────────────────────────

  ┌──────────────────────────────────────────────────────┐
  │  PRIMARY REGIME : {c['primary_regime']:<34} │
  │  SECONDARY TAGS : {tag_str:<34} │
  └──────────────────────────────────────────────────────┘
""")


def append_log(c: dict, log_path: Path) -> None:
    """Append a new row to the Regime Classification Log markdown table."""
    tag_str = ", ".join(c["secondary_tags"])
    stale = c["last_bar_date"] != c["analysis_date"]
    notes = f"Based on {c['last_bar_date']} data (stale)" if stale else "Live data"

    new_row = (
        f"| {c['analysis_date']} | {c['primary_regime']} | {tag_str} "
        f"| {c['atr_20d']} | {c['atr_avg_20d']} | "
        f"{next((t for t in c['secondary_tags'] if t.startswith('GAP')), 'FLAT')} "
        f"| {notes} |"
    )

    detail_block = f"""
### {c['analysis_date']} Regime Detail
- **Analysis date**: {c['analysis_date']} (based on last available bar: {c['last_bar_date']})
- **Last close**: {c['last_close']}
- **SMA20**: {c['sma20']} — price **{'ABOVE' if c['last_close'] > c['sma20'] else 'BELOW'}** {'✅' if c['last_close'] > c['sma20'] else '⚠️'}
- **SMA50**: {c['sma50']} — price **{'ABOVE' if c['last_close'] > c['sma50'] else 'BELOW'}** {'✅' if c['last_close'] > c['sma50'] else '⚠️'}
- **SMA200**: {c['sma200']} — price **{'ABOVE' if c['last_close'] > c['sma200'] else 'BELOW'}** {'✅' if c['last_close'] > c['sma200'] else '⚠️'}
- **Trend score**: {c['trend_score']}/5
- **5d return**: {c['ret_5d']:+.2f}%
- **20d return**: {c['ret_20d']:+.2f}%
- **60d return**: {c['ret_60d']:+.2f}%
- **Annualized vol (20d)**: {c['vol_20d_ann']}% — **{'HIGH VOLATILITY' if c['vol_20d_ann'] > 25 else 'LOW VOLATILITY' if c['vol_20d_ann'] < 10 else 'NORMAL'}**
- **Annualized vol (60d)**: {c['vol_60d_ann']}%
- **52-week high**: {c['high_52w']}
- **Drawdown from 52w high**: {c['drawdown_pct']:.2f}%
- **ATR(20d)**: {c['atr_20d']} pts
- **Classified regime**: **{c['primary_regime']}**
- **Secondary tags**: {tag_str}
"""

    content = log_path.read_text()

    # Find the table and insert row after the header
    table_header = "| Date | Primary Regime |"
    table_sep = "|------|"
    lines = content.split("\n")
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith(table_sep):
            insert_idx = i + 1
            break

    if insert_idx is None:
        # Append at end
        content = content.rstrip() + "\n" + new_row + "\n" + detail_block
    else:
        # Check if today's date already has a row
        today_str = c["analysis_date"]
        already_logged = any(line.startswith(f"| {today_str}") for line in lines)
        if already_logged:
            print(f"ℹ️  Log already has an entry for {today_str}. Skipping append.")
            return

        lines.insert(insert_idx, new_row)
        content = "\n".join(lines)
        content = content.rstrip() + "\n" + detail_block

    log_path.write_text(content)
    print(f"✅  Appended to {log_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Daily ES regime classifier")
    parser.add_argument("--data", type=Path, default=None, help="Path to 5min parquet")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help="Path to regime log")
    parser.add_argument("--date", type=str, default=None, help="Analysis date YYYY-MM-DD")
    parser.add_argument("--no-append", action="store_true", help="Don't write to log")
    args = parser.parse_args()

    data_path = args.data or find_data_file()
    print(f"Loading data from: {data_path}")
    df = pd.read_parquet(data_path)

    as_of = date.fromisoformat(args.date) if args.date else None
    c = classify(df, as_of_date=as_of)
    print_report(c)

    if not args.no_append:
        append_log(c, args.log)


if __name__ == "__main__":
    main()
