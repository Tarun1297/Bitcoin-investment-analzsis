from __future__ import annotations

import csv
import datetime as dt
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import pstdev
from urllib.parse import urlencode
from urllib.request import urlopen

DATA_DIR = Path("data")
OUTPUT_DIR = Path("outputs")


@dataclass
class PriceRow:
    date: dt.date
    close: float
    rsi_14: float | None = None


@dataclass
class ScenarioSummary:
    horizon_days: int
    trades: int
    average_return_pct: float | None
    median_return_pct: float | None
    win_rate_pct: float | None
    annualized_return_pct: float | None
    std_dev_pct: float | None
    p25_return_pct: float | None
    p75_return_pct: float | None
    worst_return_pct: float | None
    best_return_pct: float | None
    benchmark_avg_return_pct: float | None
    alpha_vs_benchmark_pct: float | None


@dataclass
class ThresholdSummary:
    threshold: int
    horizon_days: int
    trades: int
    average_return_pct: float | None
    win_rate_pct: float | None


def fetch_btc_usd_daily(years: int = 15) -> list[PriceRow]:
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=years * 365)

    base_url = "https://min-api.cryptocompare.com/data/v2/histoday"
    all_rows: dict[dt.date, PriceRow] = {}
    to_ts = int(dt.datetime.combine(end_date, dt.time.min, tzinfo=dt.timezone.utc).timestamp())

    while True:
        params = urlencode({"fsym": "BTC", "tsym": "USD", "limit": 2000, "toTs": to_ts})
        with urlopen(f"{base_url}?{params}", timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("Response") != "Success":
            raise RuntimeError(f"CryptoCompare API error: {payload}")

        rows = payload["Data"]["Data"]
        if not rows:
            break

        for row in rows:
            row_date = dt.datetime.fromtimestamp(row["time"], tz=dt.timezone.utc).date()
            all_rows[row_date] = PriceRow(date=row_date, close=float(row["close"]))

        earliest = min(dt.datetime.fromtimestamp(r["time"], tz=dt.timezone.utc).date() for r in rows)
        if earliest <= start_date:
            break

        to_ts = int(dt.datetime.combine(earliest - dt.timedelta(days=1), dt.time.min, tzinfo=dt.timezone.utc).timestamp())

    filtered = [r for r in all_rows.values() if start_date <= r.date <= end_date]
    filtered.sort(key=lambda x: x.date)

    if not filtered:
        raise RuntimeError("No BTC/USD price data was fetched.")

    return filtered


def calculate_rsi(prices: list[PriceRow], period: int = 14) -> None:
    closes = [p.close for p in prices]
    gains = [0.0]
    losses = [0.0]

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))

    avg_gain = 0.0
    avg_loss = 0.0

    for i, price in enumerate(prices):
        if i < period:
            price.rsi_14 = None
            continue

        if i == period:
            avg_gain = sum(gains[1 : period + 1]) / period
            avg_loss = sum(losses[1 : period + 1]) / period
        else:
            avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            price.rsi_14 = 100.0
        else:
            rs = avg_gain / avg_loss
            price.rsi_14 = 100.0 - (100.0 / (1.0 + rs))


def percentile(values: list[float], pct: float) -> float:
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * pct
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return sorted_vals[int(idx)]
    frac = idx - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def compute_forward_returns(prices: list[PriceRow], horizon_days: int) -> list[float]:
    date_to_close = {p.date: p.close for p in prices}
    returns = []
    for p in prices:
        sell_price = date_to_close.get(p.date + dt.timedelta(days=horizon_days))
        if sell_price is not None:
            returns.append((sell_price / p.close) - 1.0)
    return returns


def evaluate(prices: list[PriceRow], threshold: float = 20.0, horizons: list[int] | None = None):
    if horizons is None:
        horizons = [365, 730, 1095]

    date_to_close = {p.date: p.close for p in prices}
    buys = [p for p in prices if p.rsi_14 is not None and p.rsi_14 < threshold]

    trade_rows: list[dict[str, str | float]] = []
    for buy in buys:
        row: dict[str, str | float] = {
            "BuyDate": buy.date.isoformat(),
            "BuyPrice": round(buy.close, 6),
            "BuyRSI": round(buy.rsi_14 or 0.0, 4),
        }
        for horizon in horizons:
            sell_date = buy.date + dt.timedelta(days=horizon)
            sell_price = date_to_close.get(sell_date)
            row[f"SellDate_{horizon}d"] = sell_date.isoformat()
            row[f"SellPrice_{horizon}d"] = "" if sell_price is None else round(sell_price, 6)
            row[f"Return_{horizon}d"] = "" if sell_price is None else round((sell_price / buy.close) - 1.0, 6)
        trade_rows.append(row)

    summaries: list[ScenarioSummary] = []
    for horizon in horizons:
        returns = [float(r[f"Return_{horizon}d"]) for r in trade_rows if r[f"Return_{horizon}d"] != ""]
        benchmark_returns = compute_forward_returns(prices, horizon)

        if returns:
            years = horizon / 365.0
            annualized = [((1 + r) ** (1 / years) - 1) for r in returns]
            benchmark_avg = sum(benchmark_returns) / len(benchmark_returns) if benchmark_returns else None
            avg = sum(returns) / len(returns)

            summaries.append(
                ScenarioSummary(
                    horizon_days=horizon,
                    trades=len(returns),
                    average_return_pct=round(avg * 100, 4),
                    median_return_pct=round(percentile(returns, 0.5) * 100, 4),
                    win_rate_pct=round(sum(1 for r in returns if r > 0) / len(returns) * 100, 4),
                    annualized_return_pct=round(sum(annualized) / len(annualized) * 100, 4),
                    std_dev_pct=round(pstdev(returns) * 100, 4),
                    p25_return_pct=round(percentile(returns, 0.25) * 100, 4),
                    p75_return_pct=round(percentile(returns, 0.75) * 100, 4),
                    worst_return_pct=round(min(returns) * 100, 4),
                    best_return_pct=round(max(returns) * 100, 4),
                    benchmark_avg_return_pct=None if benchmark_avg is None else round(benchmark_avg * 100, 4),
                    alpha_vs_benchmark_pct=None if benchmark_avg is None else round((avg - benchmark_avg) * 100, 4),
                )
            )
        else:
            summaries.append(
                ScenarioSummary(
                    horizon_days=horizon,
                    trades=0,
                    average_return_pct=None,
                    median_return_pct=None,
                    win_rate_pct=None,
                    annualized_return_pct=None,
                    std_dev_pct=None,
                    p25_return_pct=None,
                    p75_return_pct=None,
                    worst_return_pct=None,
                    best_return_pct=None,
                    benchmark_avg_return_pct=None,
                    alpha_vs_benchmark_pct=None,
                )
            )

    return buys, trade_rows, summaries


def threshold_sweep(prices: list[PriceRow], thresholds: list[int], horizons: list[int]) -> list[ThresholdSummary]:
    results: list[ThresholdSummary] = []
    for threshold in thresholds:
        _, trades, _ = evaluate(prices, threshold=threshold, horizons=horizons)
        for horizon in horizons:
            returns = [float(r[f"Return_{horizon}d"]) for r in trades if r[f"Return_{horizon}d"] != ""]
            if returns:
                results.append(
                    ThresholdSummary(
                        threshold=threshold,
                        horizon_days=horizon,
                        trades=len(returns),
                        average_return_pct=round(sum(returns) / len(returns) * 100, 4),
                        win_rate_pct=round(sum(1 for r in returns if r > 0) / len(returns) * 100, 4),
                    )
                )
            else:
                results.append(
                    ThresholdSummary(
                        threshold=threshold,
                        horizon_days=horizon,
                        trades=0,
                        average_return_pct=None,
                        win_rate_pct=None,
                    )
                )
    return results


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_price_data(prices: list[PriceRow], path: Path) -> None:
    rows = [
        {
            "Date": p.date.isoformat(),
            "Close": round(p.close, 6),
            "RSI_14": "" if p.rsi_14 is None else round(p.rsi_14, 4),
        }
        for p in prices
    ]
    write_csv(path, rows, ["Date", "Close", "RSI_14"])


def create_svg_buy_sell_plot(prices: list[PriceRow], trade_rows: list[dict], horizon: int, output_path: Path) -> None:
    width, height = 1400, 700
    left, right, top, bottom = 80, 30, 40, 80
    plot_w = width - left - right
    plot_h = height - top - bottom

    closes = [p.close for p in prices]
    p_min, p_max = min(closes), max(closes)
    date_index = {p.date.isoformat(): i for i, p in enumerate(prices)}

    def x_at(idx: int) -> float:
        return left if len(prices) == 1 else left + (idx / (len(prices) - 1)) * plot_w

    def y_at(price: float) -> float:
        return top + (1 - (price - p_min) / (p_max - p_min)) * plot_h if p_max != p_min else top + plot_h / 2

    line_points = " ".join(f"{x_at(i):.2f},{y_at(p.close):.2f}" for i, p in enumerate(prices))

    buys, sells = [], []
    for t in trade_rows:
        buy_i = date_index.get(str(t["BuyDate"]))
        sell_date = str(t.get(f"SellDate_{horizon}d", ""))
        sell_i = date_index.get(sell_date)
        sell_price = t.get(f"SellPrice_{horizon}d")
        if buy_i is not None:
            buys.append((x_at(buy_i), y_at(float(t["BuyPrice"]))))
        if sell_i is not None and sell_price != "":
            sells.append((x_at(sell_i), y_at(float(sell_price))))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="24" text-anchor="middle" font-size="20" font-family="Arial">BTC/USD Buy (RSI&lt;20) and Sell ({horizon}d) Points</text>',
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#333"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#333"/>',
        f'<polyline fill="none" stroke="#1f77b4" stroke-width="1.5" points="{line_points}"/>',
        f'<text x="{left}" y="{height-30}" font-size="12" font-family="Arial">{prices[0].date.isoformat()}</text>',
        f'<text x="{left+plot_w}" y="{height-30}" text-anchor="end" font-size="12" font-family="Arial">{prices[-1].date.isoformat()}</text>',
    ]

    for x, y in buys:
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="green"/>')
    for x, y in sells:
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="red"/>')

    svg.extend(
        [
            f'<rect x="{width-260}" y="{top+10}" width="230" height="70" fill="white" stroke="#ccc"/>',
            f'<circle cx="{width-240}" cy="{top+32}" r="4" fill="green"/><text x="{width-228}" y="{top+36}" font-size="12" font-family="Arial">Buy (RSI&lt;20)</text>',
            f'<circle cx="{width-240}" cy="{top+56}" r="4" fill="red"/><text x="{width-228}" y="{top+60}" font-size="12" font-family="Arial">Sell ({horizon}d)</text>',
            "</svg>",
        ]
    )

    output_path.write_text("\n".join(svg), encoding="utf-8")


def create_threshold_table_svg(rows: list[ThresholdSummary], horizons: list[int], output_path: Path) -> None:
    thresholds = sorted({r.threshold for r in rows})
    row_h = 40
    col_w = 190
    margin = 30
    width = margin * 2 + col_w * (len(horizons) + 1)
    height = margin * 2 + row_h * (len(thresholds) + 1)

    lookup = {(r.threshold, r.horizon_days): r for r in rows}

    def cell_color(value: float | None) -> str:
        if value is None:
            return "#f2f2f2"
        if value >= 50:
            return "#c7f9cc"
        if value >= 20:
            return "#d8f3dc"
        if value >= 0:
            return "#fff3bf"
        return "#ffc9c9"

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="20" text-anchor="middle" font-size="16" font-family="Arial">Average Return (%) by RSI Threshold and Holding Horizon</text>',
    ]

    y0 = margin + 10
    svg.append(f'<text x="{margin + 8}" y="{y0 + row_h - 12}" font-size="12" font-family="Arial">RSI Threshold</text>')
    for i, horizon in enumerate(horizons):
        x = margin + col_w * (i + 1)
        svg.append(f'<text x="{x + 8}" y="{y0 + row_h - 12}" font-size="12" font-family="Arial">{horizon}d</text>')

    for ridx, threshold in enumerate(thresholds):
        y = y0 + row_h * (ridx + 1)
        svg.append(f'<rect x="{margin}" y="{y}" width="{col_w}" height="{row_h}" fill="#f8f9fa" stroke="#dee2e6"/>')
        svg.append(f'<text x="{margin + 8}" y="{y + 25}" font-size="12" font-family="Arial">RSI &lt; {threshold}</text>')

        for cidx, horizon in enumerate(horizons):
            x = margin + col_w * (cidx + 1)
            row = lookup[(threshold, horizon)]
            value = row.average_return_pct
            label = "NA" if value is None else f"{value:.2f}% ({row.trades})"
            svg.append(f'<rect x="{x}" y="{y}" width="{col_w}" height="{row_h}" fill="{cell_color(value)}" stroke="#dee2e6"/>')
            svg.append(f'<text x="{x + 8}" y="{y + 25}" font-size="12" font-family="Arial">{label}</text>')

    svg.append("</svg>")
    output_path.write_text("\n".join(svg), encoding="utf-8")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)

    prices = fetch_btc_usd_daily(years=15)
    calculate_rsi(prices, period=14)

    save_price_data(prices, DATA_DIR / "btc_usd_daily_15y.csv")

    horizons = [365, 730, 1095]
    _, trade_rows, summaries = evaluate(prices, threshold=20.0, horizons=horizons)

    fields = ["BuyDate", "BuyPrice", "BuyRSI"]
    for h in horizons:
        fields.extend([f"SellDate_{h}d", f"SellPrice_{h}d", f"Return_{h}d"])
    write_csv(OUTPUT_DIR / "rsi_below_20_trades.csv", trade_rows, fields)

    write_csv(
        OUTPUT_DIR / "scenario_summary.csv",
        [asdict(s) for s in summaries],
        [
            "horizon_days",
            "trades",
            "average_return_pct",
            "median_return_pct",
            "win_rate_pct",
            "annualized_return_pct",
            "std_dev_pct",
            "p25_return_pct",
            "p75_return_pct",
            "worst_return_pct",
            "best_return_pct",
            "benchmark_avg_return_pct",
            "alpha_vs_benchmark_pct",
        ],
    )

    threshold_rows = threshold_sweep(prices, thresholds=[15, 20, 25, 30], horizons=horizons)
    write_csv(
        OUTPUT_DIR / "threshold_sweep_summary.csv",
        [asdict(s) for s in threshold_rows],
        ["threshold", "horizon_days", "trades", "average_return_pct", "win_rate_pct"],
    )

    for h in horizons:
        create_svg_buy_sell_plot(prices, trade_rows, h, OUTPUT_DIR / f"buy_sell_{h}d.svg")
    create_threshold_table_svg(threshold_rows, horizons, OUTPUT_DIR / "threshold_sweep_table.svg")

    print("Created outputs in data/ and outputs/ directories.")


if __name__ == "__main__":
    main()
