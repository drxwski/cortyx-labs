# Data Engineering Update — 2026-03-28

**Agent**: Market Data Analyst
**Issue**: [COR-4](/COR/issues/COR-4)
**Date**: 2026-03-28

---

## Summary

Established a live ES 5-min data pipeline via yfinance (`ES=F`). Appended **13,278 bars** (2026-01-15 to 2026-03-27) to the existing raw dataset. Clean session parquet regenerated and is **current to 2026-03-27**.

### Partial Backfill Note

yfinance provides only ~60 days of free 5-min intraday data. A **181-trading-day gap** (`2025-05-09` to `2026-01-14`) at 5-min resolution could not be filled.

**Action required to close gap**: Subscribe to a paid provider:
- **Polygon.io** — `GET /v2/aggs/ticker/ES1%21/range/5/minute/{from}/{to}`
- **Databento** — `CME.Globex` schema, `OHLCV-1m` aggregation
- **Interactive Brokers API** — `reqHistoricalData` with `barSizeSetting="5 mins"` (requires TWS/Gateway running)

---

## Raw CSV Quality Check (`ES_5min_18yr.csv`)

| Check | Result | Notes |
|-------|--------|-------|
| Total rows | 1,237,315 | Up from 1,224,037 |
| Date range | 2008-01-02 to 2026-03-27 | Current to within 1 trading day |
| Bars added this run | 13,278 | Via yfinance 60-day window |
| Null values | 0 | |
| Duplicate rows | 0 | |
| High < Low anomalies | 0 | |
| Open/Close outside H-L | 0 | |
| Zero-volume bars | 42 | All overnight bars from yfinance (23:00 UTC / CME settlement); filtered out in clean parquet |
| Gaps > 30min | 4,519 | Expected: weekends, holidays, CME session breaks (+52 from new data period) |
| Spike bars (range > 5x ATR) | 4,142 | Legitimate high-volatility market events (2008 crisis, COVID, 2022 bear); not data anomalies |

**Overall raw data verdict**: Structurally CLEAN. All flagged items are expected market behavior or benign yfinance artifacts.

---

## Clean Parquet Quality Check (`data/cleaned/ES_5min_session.parquet`)

Session filter: 06:00 to 11:55 ET only (72 bars/day max).

| Check | Result |
|-------|--------|
| Total session rows | 325,683 |
| Date range | 2008-01-02 to 2026-03-27 |
| Null values | 0 |
| Duplicates | 0 |
| Zero-volume bars | 0 |

**Clean parquet verdict**: READY FOR RESEARCH

---

## 5-Min Gap Analysis

| Period | Status | Resolution |
|--------|--------|-----------|
| 2008-01-02 to 2025-05-08 | Complete | Original dataset |
| 2025-05-09 to 2026-01-14 | GAP | 181 trading days, 5-min missing — paid source needed |
| 2026-01-15 to 2026-03-27 | Complete | Added via yfinance |

---

## Files Updated

| File | Action |
|------|--------|
| `~/Downloads/Vantyx Trading Algorithm/data/raw/ES_5min_18yr.csv` | 13,278 bars appended |
| `cortyx-labs/data/cleaned/ES_5min_session.parquet` | Regenerated (325,683 session bars) |
| `~/Downloads/Vantyx Trading Algorithm/data/clean/ES_5min_session.parquet` | Regenerated |
| `~/ObsidianVault/Cortyx-Labs/01_Data-Engineering/Data-Ingestion-Log.md` | New entry added |

## Pipeline Script

`cortyx-labs/data/fetch_es_update.py` — run periodically to keep data current:

```bash
python3 cortyx-labs/data/fetch_es_update.py
```

---

## Next Steps

1. **Regime Classifier** — can now run on fresh data (current to 2026-03-27)
2. **Gap backfill** — subscribe to Polygon.io or Databento to fill 2025-05-09 to 2026-01-14
3. **Automation** — schedule `fetch_es_update.py` as a daily cron job to keep data current
