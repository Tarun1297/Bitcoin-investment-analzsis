# Bitcoin RSI Backtest (BTC/USD)

This project downloads the last **15 years of daily BTC/USD close prices**, calculates a **14-day RSI**, and evaluates signal quality when buying BTC whenever **RSI < 20**.

## What this analysis includes

### Core strategy test
- Daily BTC/USD close history for ~15 years.
- RSI(14) calculation (Wilder smoothing).
- Buy signal rule: `RSI_14 < 20`.
- Forward return tests for:
  - **1 year (365 days)**
  - **2 years (730 days)**
  - **3 years (1095 days)**
- Buy/sell point visualizations for each horizon.

### Additional decision-making analyses
- Distribution metrics: average, median, p25/p75, volatility (std dev), best/worst outcomes.
- Win rate and annualized return per horizon.
- Benchmark comparison vs unconditional BTC forward returns for each horizon.
- Alpha metric (`signal avg return - benchmark avg return`).
- RSI threshold sensitivity sweep for `RSI < {15, 20, 25, 30}` across each holding horizon.
- A compact threshold/horizon heatmap-style SVG table.

## Data source

The script uses the public CryptoCompare daily historical endpoint:

- `https://min-api.cryptocompare.com/data/v2/histoday`

## Run

```bash
python src/btc_rsi_analysis.py
```

## Outputs

After running, these files are generated:

- `data/btc_usd_daily_15y.csv`
  - Daily close data + RSI(14).
- `outputs/rsi_below_20_trades.csv`
  - Buy points where RSI<20 plus sell points and returns for each horizon.
- `outputs/scenario_summary.csv`
  - Core scenario summary with risk/distribution and benchmark/alpha fields.
- `outputs/threshold_sweep_summary.csv`
  - RSI threshold sensitivity table.
- `outputs/buy_sell_365d.svg`
- `outputs/buy_sell_730d.svg`
- `outputs/buy_sell_1095d.svg`
- `outputs/threshold_sweep_table.svg`

## Notes

- Return formula: `(sell_price / buy_price) - 1`.
- Sell dates use exact day offsets from buy date.
- Trades with sell dates beyond available history are left blank in return columns.

## Quick test (offline logic checks)

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
