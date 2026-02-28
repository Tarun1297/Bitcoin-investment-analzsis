import datetime as dt
import unittest

from src.btc_rsi_analysis import PriceRow, calculate_rsi, evaluate, threshold_sweep


class TestBtcRsiAnalysis(unittest.TestCase):
    def make_prices(self, n=1500):
        start = dt.date(2018, 1, 1)
        rows = []
        price = 100.0
        for i in range(n):
            # repeatable wave-like movement to create RSI excursions
            if i % 20 < 10:
                price *= 1.01
            else:
                price *= 0.99
            rows.append(PriceRow(date=start + dt.timedelta(days=i), close=price))
        return rows

    def test_calculate_rsi_populates_values(self):
        prices = self.make_prices(100)
        calculate_rsi(prices)
        self.assertTrue(any(p.rsi_14 is not None for p in prices[20:]))
        non_null = [p.rsi_14 for p in prices if p.rsi_14 is not None]
        self.assertTrue(all(0 <= v <= 100 for v in non_null))

    def test_evaluate_and_threshold_sweep(self):
        prices = self.make_prices(1800)
        calculate_rsi(prices)

        _, trades, summaries = evaluate(prices, threshold=40.0, horizons=[365, 730, 1095])
        self.assertGreater(len(trades), 0)
        self.assertEqual(len(summaries), 3)
        self.assertTrue(any(s.trades > 0 for s in summaries))

        sweep = threshold_sweep(prices, thresholds=[20, 30, 40], horizons=[365, 730])
        self.assertEqual(len(sweep), 6)


if __name__ == "__main__":
    unittest.main()
