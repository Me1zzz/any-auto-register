#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Sequence


REQUIRED_COLUMNS = ("model", "input_tokens", "output_tokens", "cached_tokens")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize per-model input, output, and cached token usage from a CSV file. "
            "Optionally compute costs from per-million-token prices."
        )
    )
    parser.add_argument("csv_path", help="Path to the usage CSV file.")
    parser.add_argument(
        "--input-price-per-million",
        type=float,
        default=None,
        help="Global input token price per 1,000,000 tokens.",
    )
    parser.add_argument(
        "--output-price-per-million",
        type=float,
        default=None,
        help="Global output token price per 1,000,000 tokens.",
    )
    parser.add_argument(
        "--cache-price-per-million",
        type=float,
        default=None,
        help="Global cached token price per 1,000,000 tokens.",
    )
    parser.add_argument(
        "--price-file",
        help=(
            "Optional JSON file keyed by model name. Each value may contain "
            "input_price, output_price, and cached_price."
        ),
    )
    return parser


def validate_required_columns(fieldnames: Sequence[str] | None) -> None:
    available = set(fieldnames or [])
    missing = [column for column in REQUIRED_COLUMNS if column not in available]
    if missing:
        raise ValueError(f"missing required CSV columns: {', '.join(missing)}")


def load_usage_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        validate_required_columns(reader.fieldnames)
        return list(reader)


def parse_token_int(value: Any, field_name: str, model_name: str) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(
            f"invalid integer value for {field_name} in model {model_name!r}: {text!r}"
        ) from exc


def aggregate_usage(rows: list[dict[str, str]]) -> dict[str, dict[str, int]]:
    aggregated: dict[str, dict[str, int]] = {}
    for row in rows:
        model_name = str(row.get("model") or "").strip()
        if not model_name:
            raise ValueError("encountered a row with an empty model value")

        summary = aggregated.setdefault(
            model_name,
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "cached_tokens": 0,
                "total_tokens": 0,
            },
        )
        input_tokens = parse_token_int(row.get("input_tokens"), "input_tokens", model_name)
        output_tokens = parse_token_int(
            row.get("output_tokens"), "output_tokens", model_name
        )
        cached_tokens = parse_token_int(
            row.get("cached_tokens"), "cached_tokens", model_name
        )
        summary["input_tokens"] += input_tokens
        summary["output_tokens"] += output_tokens
        summary["cached_tokens"] += cached_tokens
        summary["total_tokens"] += input_tokens + output_tokens + cached_tokens
    return aggregated


def load_price_overrides(json_path: Path | None) -> dict[str, dict[str, float]]:
    if json_path is None:
        return {}

    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"price file contains invalid JSON: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"unable to read price file: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("price file must contain a top-level JSON object")

    overrides: dict[str, dict[str, float]] = {}
    for model_name, model_prices in raw.items():
        if not isinstance(model_name, str) or not model_name.strip():
            raise ValueError("price file model keys must be non-empty strings")
        if not isinstance(model_prices, dict):
            raise ValueError(f"price file entry for {model_name!r} must be an object")

        parsed_prices: dict[str, float] = {}
        for source_key, target_key in (
            ("input_price", "input_price"),
            ("output_price", "output_price"),
            ("cached_price", "cached_price"),
            ("cache_price", "cached_price"),
        ):
            if source_key not in model_prices:
                continue
            try:
                parsed_prices[target_key] = float(model_prices[source_key])
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"price file value for {model_name!r}.{source_key} must be numeric"
                ) from exc
        overrides[model_name] = parsed_prices
    return overrides


def resolve_model_prices(
    model_name: str, args: argparse.Namespace, overrides: dict[str, dict[str, float]]
) -> dict[str, float] | None:
    prices = {
        "input_price": args.input_price_per_million,
        "output_price": args.output_price_per_million,
        "cached_price": args.cache_price_per_million,
    }
    for key, value in overrides.get(model_name, {}).items():
        prices[key] = value
    if all(value is None for value in prices.values()):
        return None
    return {key: float(value or 0.0) for key, value in prices.items()}


def compute_model_cost(summary: dict[str, int], prices: dict[str, float] | None) -> dict[str, float]:
    if prices is None:
        return {
            "input_cost": 0.0,
            "output_cost": 0.0,
            "cached_cost": 0.0,
            "total_cost": 0.0,
        }

    billable_input_tokens = max(summary["input_tokens"] - summary["cached_tokens"], 0)
    input_cost = billable_input_tokens / 1_000_000 * prices["input_price"]
    output_cost = summary["output_tokens"] / 1_000_000 * prices["output_price"]
    cached_cost = summary["cached_tokens"] / 1_000_000 * prices["cached_price"]
    return {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "cached_cost": cached_cost,
        "total_cost": input_cost + output_cost + cached_cost,
    }


def build_display_rows(
    aggregated: dict[str, dict[str, int]],
    args: argparse.Namespace,
    overrides: dict[str, dict[str, float]],
) -> tuple[list[dict[str, Any]], bool]:
    rows: list[dict[str, Any]] = []
    include_costs = False
    total_row: dict[str, Any] = {
        "model": "TOTAL",
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "cached_cost": 0.0,
        "total_cost": 0.0,
    }

    for model_name in sorted(aggregated):
        usage_summary = aggregated[model_name]
        prices = resolve_model_prices(model_name, args, overrides)
        include_costs = include_costs or prices is not None
        costs = compute_model_cost(usage_summary, prices)
        display_row = {"model": model_name, **usage_summary, **costs}
        rows.append(display_row)
        for key in (
            "input_tokens",
            "output_tokens",
            "cached_tokens",
            "total_tokens",
            "input_cost",
            "output_cost",
            "cached_cost",
            "total_cost",
        ):
            total_row[key] += display_row[key]

    rows.append(total_row)
    return rows, include_costs


def format_summary_table(rows: list[dict[str, Any]], include_costs: bool) -> str:
    columns = ["model", "input_tokens", "output_tokens", "cached_tokens", "total_tokens"]
    if include_costs:
        columns.extend(["input_cost", "output_cost", "cached_cost", "total_cost"])

    formatted_rows: list[dict[str, str]] = []
    for row in rows:
        formatted_row: dict[str, str] = {}
        for column in columns:
            value = row[column]
            if column.endswith("_cost"):
                formatted_row[column] = f"{float(value):.2f}"
            else:
                formatted_row[column] = str(value)
        formatted_rows.append(formatted_row)

    widths = {
        column: max(len(column), *(len(row[column]) for row in formatted_rows))
        for column in columns
    }

    header = "  ".join(column.ljust(widths[column]) for column in columns)
    separator = "  ".join("-" * widths[column] for column in columns)
    body = [
        "  ".join(row[column].ljust(widths[column]) for column in columns)
        for row in formatted_rows
    ]
    return "\n".join([header, separator, *body])


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        csv_path = Path(args.csv_path)
        rows = load_usage_rows(csv_path)
        aggregated = aggregate_usage(rows)
        overrides = load_price_overrides(Path(args.price_file) if args.price_file else None)
        display_rows, include_costs = build_display_rows(aggregated, args, overrides)
        print(format_summary_table(display_rows, include_costs))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
