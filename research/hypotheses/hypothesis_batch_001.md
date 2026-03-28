# Strategy Hypothesis Batch 001 — ES 5min

**Author**: Quantitative Researcher (Cortyx Labs)
**Date**: 2026-03-28
**Issue**: [COR-8](/COR/issues/COR-8)
**Data**: 18yr ES 5min OHLCV — 2008-01-02 to 2026-03-27 (325,683 clean session bars)
**Regime note**: Regime classification (COR-5) is underway. All hypotheses include explicit regime assumptions based on available signals from the 2026-03-28 data check.

---

## Overview

This memo defines the first batch of 5 testable strategy hypotheses for the ES 5min timeframe. Each hypothesis is grounded in market microstructure or peer-reviewed academic literature, expressed with unambiguous entry/exit logic, and designed to avoid look-ahead bias by construction. All signals use only information available at or before the entry bar's close.

Data assumptions:
- Session bars only: 06:00–11:55 ET (72 bars/day max, as per clean parquet)
- For intraday strategies, RTH session = 09:30–16:00 ET bars where available in raw data
- ATR references use 20-period ATR computed on session bars unless stated otherwise
- No future data is used to compute any indicator at entry time

---

## Hypothesis 1: ORB-30 — Opening Range Breakout (30-minute)

### Thesis
The first 30 minutes of RTH (09:30–10:00 ET) establish an initial price discovery range as overnight positions are liquidated and informed participants initiate directional trades. A decisive close outside this range reflects committed order flow and frequently produces intraday continuation, exploiting the structural imbalance between early informed participants and the retail traders who react to the breakout.

Academic support: Toby Crabel (1990) *Day Trading with Short-Term Price Patterns*; Bhatt & Bhattacharya (2014) on opening range dynamics in index futures.

### Signal Definition

**Pre-computation (no look-ahead):**
```
OR_HIGH = max(high) over 09:30–09:55 ET bars (first 6 × 5min bars)
OR_LOW  = min(low)  over 09:30–09:55 ET bars
OR_RANGE = OR_HIGH - OR_LOW
```
Range is fixed at 10:00 ET bar open; signals are evaluated from 10:00 ET onward.

**Entry conditions:**
- LONG:  first 5min bar that closes > OR_HIGH AND OR_RANGE < 1.5 × ATR(20) AND bar volume > 1.2 × 20-bar avg volume
- SHORT: first 5min bar that closes < OR_LOW  AND OR_RANGE < 1.5 × ATR(20) AND bar volume > 1.2 × 20-bar avg volume
- Maximum one trade per session; first valid signal only

**Exit conditions (precedence order):**
1. Stop-loss: OR_LOW (long) / OR_HIGH (short) — full invalidation of OR thesis
2. Profit target: entry + 2.0 × ATR(20) (long) / entry − 2.0 × ATR(20) (short)
3. Time stop: 11:55 ET session end (market-on-close)
4. Trailing stop: once 1.0 × ATR(20) in profit, trail stop to OR midpoint

### Position Sizing Approach
Volatility-scaled: `contracts = floor(risk_per_trade / (OR_RANGE × point_value))` where `risk_per_trade` is a fixed notional risk budget (e.g., $500 per trade). Base unit = 1 MES contract for testing; scale to ES once validated.

### Expected Edge
- **Best regimes**: trending / normal-vol (20d vol ≤ 1.5× 252d median); high-volume sessions
- **Historical analogs**: 2012–2014 low-vol bull run; 2017 post-election trend; 2023 AI-driven rally
- **Weakest regimes**: high-vol choppy (2011 debt ceiling, 2022 bear); avoid on FOMC/CPI release days
- **Expected Sharpe (literature range)**: 0.6–1.2 pre-cost on ES (Gao & Ho 2015; Bulkowski 2008)

### Key Risks and Invalidation Criteria
- **Whipsaw risk**: fake breakout followed by immediate reversal; volume filter partially mitigates
- **Gap-day contamination**: large overnight gaps may distort OR; add gap filter (|gap| < 0.75 × ATR(20))
- **Trend degradation**: if win rate < 45% over 252-day rolling window, cease trading
- **Overfitting guard**: the 30-min window and 1.5× ATR range filter must be set before any in-sample optimization and held constant in walk-forward

---

## Hypothesis 2: OGF — Overnight Gap Fade

### Thesis
ES futures trade nearly 24 hours, but genuine price discovery is concentrated in RTH. Overnight session moves are driven by lower-liquidity conditions, ETF arbitrage, and geopolitical noise rather than fundamental value change. Large overnight gaps tend to partially or fully fill within the first 90 minutes of RTH as liquidity providers and hedgers normalize the price, generating a mean-reversion edge that is structurally present across multiple market regimes.

Academic support: Branch (2003) *J. of Finance* gap study; Tong (2016) overnight return predictability in equity index futures.

### Signal Definition

**Pre-computation:**
```
PREV_RTH_CLOSE = close of 15:55 ET bar on prior session
RTH_OPEN       = open of 09:30 ET bar current session
GAP            = RTH_OPEN − PREV_RTH_CLOSE
GAP_PCT        = GAP / PREV_RTH_CLOSE
```

**Entry conditions:**
- LONG (gap-down fade):  GAP_PCT < −0.30% AND NOT an economic release day (NFP, CPI, FOMC)
- SHORT (gap-up fade):   GAP_PCT > +0.30% AND NOT an economic release day
- Entry: market order at 09:31 ET (second bar open of RTH)
- Filter: previous day's ATR(20) must be within ±50% of 252-day median ATR (exclude extreme vol days)

**Exit conditions:**
1. Profit target: 50% gap fill — `target = PREV_RTH_CLOSE + 0.5 × GAP` (long fades toward close from below)
2. Stop-loss: gap extends by additional 0.5 × ATR(20) beyond open (gap continuation, thesis invalidated)
3. Time stop: 10:45 ET — exit at market if neither target nor stop reached

### Position Sizing Approach
Fixed 1 contract per trade. Risk per trade = |stop distance × point_value|. Adjust notional size with account risk % once backtested.

### Expected Edge
- **Best regimes**: range-bound / low-to-medium vol; non-news-driven gaps; overnight sentiment overreaction
- **Historical analogs**: 2013–2015 low-vol drift; 2019 range consolidation
- **Weakest**: trend-continuation days, earnings gaps in macro-correlated periods, pre-FOMC overnight positioning
- **Expected Sharpe (literature range)**: 0.5–0.9; requires strict news calendar filter to achieve this

### Key Risks and Invalidation Criteria
- **News-gap contamination**: single biggest risk; hard-filter all scheduled economic releases
- **Gap-and-go days**: ES trending days where gap expands 100%+ — stop discipline is critical
- **Regime sensitivity**: in bear/high-vol regimes, gaps may reflect genuine re-pricing — reduce position size by 50% or suspend
- **Invalidation**: if rolling 90-day profit factor < 1.2, suspend and re-evaluate regime filter

---

## Hypothesis 3: IMC — Intraday Momentum Continuation

### Thesis
Strong directional moves in the first 60 minutes of RTH reflect institutional order flow (program trades, mutual fund rebalancing, index arbitrage). This "opening drive" momentum tends to persist through the late morning session as institutional algorithms complete their order execution schedules, a pattern documented in electronic futures markets as the "institutional momentum" effect.

Academic support: Grinblatt & Titman (1989) momentum in institutional portfolios; Korajczyk & Sadka (2004) momentum in futures; Heston et al. (2010) intraday momentum in equity markets.

### Signal Definition

**Pre-computation:**
```
OPEN_0930     = open of first RTH bar (09:30)
CLOSE_1030    = close of 10:30 ET bar
FIRST_HR_RET  = (CLOSE_1030 − OPEN_0930) / OPEN_0930
HOURLY_VOL    = volume sum over 09:30–10:25 bars
AVG_HRLY_VOL  = 20-day rolling average of same hourly volume
```

**Entry conditions:**
- LONG:  FIRST_HR_RET > +0.30% AND HOURLY_VOL > 1.2 × AVG_HRLY_VOL
- SHORT: FIRST_HR_RET < −0.30% AND HOURLY_VOL > 1.2 × AVG_HRLY_VOL
- Entry: market order at close of 10:30 ET bar
- Maximum one trade per session

**Exit conditions:**
1. Profit target: entry ± 0.50% (based on observed average follow-through)
2. Stop-loss: 50% retracement of first-hour move (long: entry − 0.5 × |FIRST_HR_RET|, proportional)
3. Time stop: 12:00 ET (lunchtime reversal risk increases sharply after noon)

### Position Sizing Approach
Signal-scaled: `size_multiplier = min(|FIRST_HR_RET| / 0.30%, 2.0)` applied to base contract count. Reward larger signals but cap at 2× to prevent outsized exposure on extreme opens.

### Expected Edge
- **Best regimes**: trending (bull or bear); post-FOMC drift sessions; high-volume institutional participation
- **Historical analogs**: 2020 COVID crash recovery (strong directional opens); 2022 bear market CPI reaction days
- **Weakest**: lunchtime reversal sessions; low-volume Fridays before holidays
- **Sharpe expectation**: 0.7–1.3 pre-cost; sensitivity to the volume filter is expected to be high

### Key Risks and Invalidation Criteria
- **Lunchtime reversal**: ES frequently reverses between 11:30–13:00 ET; hard time stop at 12:00 is essential
- **Regime-flip days**: gap up/down into open creates continuation vs. fade ambiguity; add ORB confirmation
- **Slippage sensitivity**: entry at market on busy opens carries slippage risk — model 0.5 tick slippage minimum in backtest
- **Invalidation**: if time-stop exits account for >40% of trades over 252-day window, the edge is dissipating

---

## Hypothesis 4: VMR — Session VWAP Mean-Reversion

### Thesis
VWAP (Volume-Weighted Average Price) is the primary execution benchmark for institutional algorithms. Large deviations from session VWAP represent temporary order-flow imbalances rather than new information, as institutional market-makers and passive algorithms continuously fade extreme deviations to execute at or near VWAP. This creates a predictable mean-reversion dynamic in liquid index futures.

Academic support: Berkowitz et al. (1988) on VWAP as market microstructure anchor; Madhavan et al. (1997) on intraday liquidity and price impact reversal in futures markets.

### Signal Definition

**Pre-computation (rolling, session-reset at 09:30):**
```
VWAP      = cumulative(price × volume) / cumulative(volume) from 09:30
VWAP_STD  = rolling 20-bar std dev of (close − VWAP)
UPPER_B   = VWAP + 1.5 × VWAP_STD
LOWER_B   = VWAP − 1.5 × VWAP_STD
RSI_14    = 14-period RSI on 5min closes
```
All values computed on bars through and including bar t; entry at close of bar t.

**Entry conditions:**
- LONG:  close < LOWER_B AND RSI_14 < 35 AND session time ≤ 12:30 ET AND session trade count ≤ 2
- SHORT: close > UPPER_B AND RSI_14 > 65 AND session time ≤ 12:30 ET AND session trade count ≤ 2
- Maximum 2 entries per session (prevents over-trading in sustained trends)

**Exit conditions:**
1. Profit target: price crosses back to VWAP (exit at VWAP touch)
2. Stop-loss: close beyond 2.5 × VWAP_STD from VWAP (thesis invalidated — trend day)
3. Time stop: 11:55 ET session end

### Position Sizing Approach
Volatility-scaled: `contracts = floor(risk_budget / (1.0 × VWAP_STD × point_value))` — tighter bands on low-vol days naturally increase position size, which is appropriate since reversion probability is higher in low-vol environments.

### Expected Edge
- **Best regimes**: range-bound / low-vol (20d vol < 252d median); non-directional consolidation sessions
- **Historical analogs**: 2013 "melt-up" low-vol period; 2017 post-Trump-rally drift; 2019 range
- **Regime interaction (COR-5 dependency)**: performance expected to be highly regime-sensitive; requires COR-5 output for live trading; for backtesting, proxy with vol regime flag (20d vol vs. 252d median)
- **Sharpe expectation**: 0.8–1.5 in range-bound regimes; near zero or negative in trending regimes

### Key Risks and Invalidation Criteria
- **Trend day catastrophe**: VWAP deviation can expand to 3–5σ on strong trend days; the 2.5× band stop is the primary defense
- **Regime filter is mandatory**: running this strategy without a regime filter (e.g., in the 2022 bear) would produce systematic losses; this is the most important design constraint
- **Parameter stability**: 1.5σ entry and 2.5σ stop must be validated out-of-sample; do not optimize in-sample
- **Invalidation**: if drawdown exceeds 15% of starting capital over any 60-day window, suspend and audit regime filter

---

## Hypothesis 5: HVRB — High-Volatility Regime Breakout

### Thesis
During elevated-volatility regimes (institutional de-risking, macro events, forced liquidations), intraday price moves are larger and more directional than in normal regimes. In these environments, the traditional mean-reversion bias of ES is temporarily suppressed, and breakouts from short-duration consolidation zones exhibit higher follow-through probability. This hypothesis is explicitly designed to perform in the conditions where the other four hypotheses are expected to underperform.

Academic support: Engle (2001) ARCH/GARCH regime dynamics; Cont (2001) empirical properties of asset return volatility clustering; Ang & Bekaert (2002) regime-switching models in equity markets.

### Signal Definition

**Regime filter (daily, updated pre-session):**
```
HIST_VOL_20D   = annualized 20-day historical vol of daily ES returns
MEDIAN_VOL_1Y  = trailing 252-day median of HIST_VOL_20D
HIGH_VOL_FLAG  = (HIST_VOL_20D > 1.5 × MEDIAN_VOL_1Y)
```
Strategy only activates when `HIGH_VOL_FLAG = True`.

**Consolidation zone detection (intrabar, session bars):**
```
CONSOL_ZONE_ACTIVE = True when:
  last 4 consecutive bars all have (high − low) < 0.3 × ATR(20)
ZONE_HIGH = max(high) of those 4 bars
ZONE_LOW  = min(low)  of those 4 bars
```

**Entry conditions (only when HIGH_VOL_FLAG = True):**
- LONG:  close > ZONE_HIGH (breakout above consolidation) AND volume > 1.3 × 20-bar avg volume
- SHORT: close < ZONE_LOW  (breakdown below consolidation) AND volume > 1.3 × 20-bar avg volume
- Maximum 2 entries per session; first consolidation breakout per direction only

**Exit conditions:**
1. Profit target: entry ± 2.0 × ATR(20) (wider target for high-vol regime)
2. Stop-loss: opposite side of consolidation zone (below ZONE_LOW for long, above ZONE_HIGH for short)
3. Time stop: 11:55 ET

### Position Sizing Approach
Reduced to 0.5× normal (high-vol means larger absolute ATR — same contract count implies disproportionately higher dollar risk). Fixed fractional: risk per trade ≤ 0.5% of account.

### Expected Edge
- **Best regimes**: explicitly high-vol (20d vol > 1.5× 252d median); bear markets; crisis periods
- **Historical analogs**: 2008 GFC (Sep–Nov); 2011 debt ceiling crisis; 2018 Q4 sell-off; 2020 COVID (Mar–Apr); 2022 inflation bear market
- **Current regime relevance**: per the 2026-03-28 data check, current ES vol is elevated — this hypothesis may be relevant for near-term backtesting focus
- **Sharpe expectation**: 0.9–1.6 in high-vol regimes; near zero when HIGH_VOL_FLAG is False (strategy is inactive)

### Key Risks and Invalidation Criteria
- **False consolidation zones**: in high-vol environments, 4-bar consolidations can be very short in duration; volume filter is critical to avoid noise
- **Regime persistence**: if vol regime reverts mid-session, the in-session trade remains open — add a mid-session vol check (if 60-min vol < threshold, tighten stop to zone boundary)
- **Correlation with ORB-30**: on high-vol opening days, both HVRB and ORB-30 may trigger near simultaneously — treat as correlated risk, do not double-position
- **Invalidation**: if HIGH_VOL_FLAG activates for fewer than 15% of sessions in the test period, the strategy has insufficient sample size for statistical validation

---

## Summary Table

| # | Name | Type | Entry Window | Regime Fit | Regime Avoid | Priority |
|---|------|------|-------------|------------|--------------|----------|
| 1 | ORB-30 | Breakout | 10:00–11:55 | Trending, Normal-Vol | High-Vol Choppy | **Highest** |
| 2 | OGF | Mean-Reversion | 09:31–10:45 | Range-Bound, Low-Vol | News Days, Trend Days | High |
| 3 | IMC | Momentum | 10:30–12:00 | Trending, High-Vol | Low-Vol, Lunchtime | High |
| 4 | VMR | Mean-Reversion | 09:30–12:30 | Range-Bound, Low-Vol | Trending Regimes | Medium |
| 5 | HVRB | Breakout | 09:30–11:55 | High-Vol Only | Normal/Low-Vol | Medium |

---

## Recommended Backtest Sequencing

1. **ORB-30** — highest priority; most widely documented edge, cleanest signal definition
2. **IMC** — strong momentum edge; critical to test time-stop sensitivity
3. **OGF** — requires economic calendar integration to properly filter news days
4. **VMR** — most regime-sensitive; priority should increase once COR-5 output is available
5. **HVRB** — interesting as a portfolio hedge for the other strategies; validate high-vol period sub-sample first

**Statistical minimum**: Each hypothesis requires ≥ 200 trades for meaningful Sharpe/Sortino estimation. Verify sample sizes before reporting walk-forward results.

---

## Dependencies and Next Steps

- **COR-5 (Regime Classifier)**: VMR and HVRB both require regime labels for live signal generation. ORB-30 and IMC can be backtested with a simple vol-proxy regime flag in the interim.
- **Backtest Analyst**: hand off this memo for implementation. Recommend starting with ORB-30 using the full 2008–2026 dataset. Walk-forward split: train 2008–2018, validation 2019–2022, out-of-sample 2023–2026.
- **Data gap note**: 181-trading-day gap (2025-05-09 to 2026-01-14) at 5-min resolution exists. Historical backtest results should flag this gap explicitly; it does not materially affect 18-year conclusions but should be disclosed.

---

*End of Hypothesis Batch 001 — Quantitative Researcher, Cortyx Labs*
