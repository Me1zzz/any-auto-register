import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from custom_tools import usage_cost_summary


class UsageCostSummaryTests(unittest.TestCase):
    def write_file(self, directory: Path, name: str, content: str) -> Path:
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_aggregate_usage_sums_tokens_per_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = self.write_file(
                Path(temp_dir),
                "usage.csv",
                "timestamp,model,input_tokens,output_tokens,cached_tokens\n"
                "2026-04-17T11:56:01+08:00,gpt-5.4,100,10,5\n"
                "2026-04-17T11:56:02+08:00,gpt-5.4,200,20,15\n"
                "2026-04-17T11:56:03+08:00,o4-mini,50,6,1\n",
            )

            rows = usage_cost_summary.load_usage_rows(csv_path)
            aggregated = usage_cost_summary.aggregate_usage(rows)

            self.assertEqual(
                aggregated,
                {
                    "gpt-5.4": {
                        "input_tokens": 300,
                        "output_tokens": 30,
                        "cached_tokens": 20,
                        "total_tokens": 350,
                    },
                    "o4-mini": {
                        "input_tokens": 50,
                        "output_tokens": 6,
                        "cached_tokens": 1,
                        "total_tokens": 57,
                    },
                },
            )

    def test_main_prints_cost_columns_with_global_and_per_model_prices(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            csv_path = self.write_file(
                temp_path,
                "usage.csv",
                "timestamp,model,input_tokens,output_tokens,cached_tokens\n"
                "2026-04-17T11:56:01+08:00,gpt-5.4,1000000,2000000,500000\n"
                "2026-04-17T11:56:02+08:00,o4-mini,500000,1000000,250000\n",
            )
            price_file = temp_path / "prices.json"
            price_file.write_text(
                json.dumps(
                    {
                        "o4-mini": {
                            "input_price": 4.0,
                            "output_price": 8.0,
                            "cached_price": 1.5,
                        }
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = usage_cost_summary.main(
                    [
                        str(csv_path),
                        "--input-price-per-million",
                        "2",
                        "--output-price-per-million",
                        "3",
                        "--cache-price-per-million",
                        "1",
                        "--price-file",
                        str(price_file),
                    ]
                )

            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("input_cost", output)
            self.assertIn("total_cost", output)
            self.assertIn("gpt-5.4", output)
            self.assertIn("o4-mini", output)
            self.assertIn("TOTAL", output)
            self.assertIn("7.50", output)
            self.assertIn("9.38", output)
            self.assertIn("16.88", output)

    def test_load_usage_rows_rejects_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = self.write_file(
                Path(temp_dir),
                "usage.csv",
                "timestamp,model,input_tokens,output_tokens\n"
                "2026-04-17T11:56:01+08:00,gpt-5.4,100,10\n",
            )

            with self.assertRaisesRegex(ValueError, "cached_tokens"):
                usage_cost_summary.load_usage_rows(csv_path)

    def test_load_price_overrides_rejects_malformed_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            price_file = self.write_file(Path(temp_dir), "prices.json", "{not-json}")

            with self.assertRaisesRegex(ValueError, "price"):
                usage_cost_summary.load_price_overrides(price_file)


if __name__ == "__main__":
    unittest.main()
