# Cortyx Labs — Research Repository
Quantitative research engine for Vantyx Research.
All ES futures strategy development, backtesting,
and validation lives here.

## Structure
- data/ — cleaned 5min ES data and regime classifications
- research/ — hypotheses and strategy specifications
- backtests/ — Python backtest scripts and results
- validation/ — walk-forward, Monte Carlo, bootstrap reports
- performance/ — live strategy tracking and weekly reports
- publishing/ — article drafts and published content

## Rules
- No raw uncleaned data ever gets committed
- Every backtest script is reproducible
- Every result file links to its backtest script
- No strategy reaches Vantyx without a validation report
