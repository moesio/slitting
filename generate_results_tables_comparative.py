from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd


PERIODS = [f"period_{i}" for i in range(1, 6)]
SCENARIO_PATTERN = re.compile(
    r"^retail_y_(?P<retail_y>[24])__retail_v_(?P<retail_v>[24])__"
    r"rolled_leftover_(?P<rolled_leftover>[24])$"
)

COIL_COLUMNS = [
    "instance", "objective", "configuration", "retail_y_coefficient",
    "retail_v_coefficient", "rolled_leftover_coefficient", "period",
    "period_number", "coil_id", "processed", "used", "coil_width",
    "coil_weight", "coil_ton_value", "used_length", "strip_count",
    "strip_produced_weight", "strip_leftover_weight", "strip_retail_weight",
    "strip_scrap_weight", "strip_loss_weight", "lateral_leftover_weight",
    "lateral_leftover_retail_weight", "lateral_leftover_scrap_weight",
    "edge_trim_weight", "rolled_leftover_weight", "rolled_leftover_width",
    "rolled_leftover_length", "processed_scrap_weight",
]

SUM_COLUMNS = [
    "new_coils_used_count", "new_coils_weight", "new_coils_value",
    "new_strip_produced_weight", "new_strip_produced_value",
    "new_strip_retail_weight", "new_strip_retail_value",
    "new_strip_scrap_weight", "new_strip_scrap_value",
    "new_strip_loss_weight", "new_strip_loss_value",
    "new_lateral_leftover_weight", "new_lateral_leftover_value",
    "new_lateral_retail_weight", "new_lateral_retail_value",
    "new_lateral_scrap_weight", "new_lateral_scrap_value",
    "new_edge_trim_weight", "new_edge_trim_value",
    "new_rolled_leftover_weight", "new_rolled_leftover_value",
    "new_partially_used_count", "processed_coils_total_count",
    "processed_coils_used_count", "processed_coils_weight",
    "processed_coils_value", "processed_strip_produced_weight",
    "processed_strip_produced_value", "processed_scrap_weight",
    "processed_scrap_value", "total_strip_produced_weight",
    "total_strip_produced_value", "retails_generated_count",
    "retails_generated_weight", "retails_generated_value",
]

KEY_COMPARISON_METRICS = [
    "new_coils_weight", "new_coils_value", "total_strip_produced_weight",
    "processed_strip_produced_weight", "reusable_generated_weight",
    "total_scrap_weight", "total_scrap_value", "total_loss_weight",
    "total_loss_value", "new_production_rate", "new_reusable_rate",
    "new_scrap_rate", "processed_recovery_rate", "reuse_dependency_rate",
]


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_div(num: float, den: float) -> float:
    return 0.0 if abs(den) < 1e-12 else num / den


def round2(value: float) -> float:
    return round(float(value), 2)


def scenario_metadata(objective: str, configuration: str) -> dict[str, Any]:
    match = SCENARIO_PATTERN.fullmatch(configuration)
    if objective == "weighted_loss" and match:
        weights = {key: int(value) for key, value in match.groupdict().items()}
        label = (
            f"WL-y{weights['retail_y']}-v{weights['retail_v']}-"
            f"r{weights['rolled_leftover']}"
        )
        return {
            "scenario": label,
            "objective": objective,
            "configuration": configuration,
            "retail_y_coefficient": weights["retail_y"],
            "retail_v_coefficient": weights["retail_v"],
            "rolled_leftover_coefficient": weights["rolled_leftover"],
        }

    label = "NCV" if objective == "new_coils_value" else f"{objective}/{configuration}"
    return {
        "scenario": label,
        "objective": objective,
        "configuration": configuration,
        "retail_y_coefficient": pd.NA,
        "retail_v_coefficient": pd.NA,
        "rolled_leftover_coefficient": pd.NA,
    }


def discover_scenarios(output_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    scenarios: dict[tuple[str, str], dict[str, Any]] = {}
    warnings: list[str] = []

    for instance_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        for objective_dir in sorted(path for path in instance_dir.iterdir() if path.is_dir()):
            for configuration_dir in sorted(path for path in objective_dir.iterdir() if path.is_dir()):
                if any((configuration_dir / period / "cutting_plan.json").exists() for period in PERIODS):
                    key = (objective_dir.name, configuration_dir.name)
                    scenarios[key] = scenario_metadata(*key)

    if not scenarios:
        warnings.append(
            "No scenarios found. Expected: output/<instance>/<objective>/"
            "<configuration>/period_<n>/cutting_plan.json"
        )
    expected = {("new_coils_value", "default")}
    expected.update(
        (
            "weighted_loss",
            f"retail_y_{retail_y}__retail_v_{retail_v}__rolled_leftover_{rolled}",
        )
        for retail_y in (2, 4)
        for retail_v in (2, 4)
        for rolled in (2, 4)
    )
    for objective, configuration in sorted(expected - set(scenarios)):
        warnings.append(f"Expected scenario not found: {objective}/{configuration}")
    return sorted(scenarios.values(), key=lambda row: row["scenario"]), warnings


def read_cutting_plan(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        content = json.load(stream)
    if not isinstance(content, dict):
        raise ValueError(f"Invalid cutting plan (expected JSON object): {path}")
    return content


def coil_record(meta: dict[str, Any], instance: str, period: str,
                coil_id: str, coil: dict[str, Any]) -> dict[str, Any]:
    rolled = coil.get("rolled_leftover", {}) or {}
    lateral = coil.get("lateral_leftover", {}) or {}
    strips = coil.get("strips", []) or []
    return {
        "instance": instance,
        **{key: meta[key] for key in [
            "objective", "configuration", "retail_y_coefficient",
            "retail_v_coefficient", "rolled_leftover_coefficient"
        ]},
        "period": period,
        "period_number": int(period.split("_")[1]),
        "coil_id": str(coil_id),
        "processed": int(coil.get("processed", 0)),
        "used": int(coil.get("used", 0)),
        "coil_width": as_float(coil.get("coil_width")),
        "coil_weight": as_float(coil.get("coil_weight")),
        "coil_ton_value": as_float(coil.get("coil_ton_value")),
        "used_length": as_float(coil.get("used_length")),
        "strip_count": len(strips),
        "strip_produced_weight": as_float(coil.get("---strip_produced_weight")),
        "strip_leftover_weight": as_float(coil.get("---strip_leftover_weight")),
        "strip_retail_weight": as_float(coil.get("------strip_retail_weight")),
        "strip_scrap_weight": as_float(coil.get("------strip_scrap_weight")),
        "strip_loss_weight": as_float(coil.get("---strip_loss_weight")),
        "lateral_leftover_weight": as_float(coil.get("---lateral_leftover_weight")),
        "lateral_leftover_retail_weight": as_float(lateral.get("---retail_weight")),
        "lateral_leftover_scrap_weight": as_float(lateral.get("---scrap_weight")),
        "edge_trim_weight": as_float(coil.get("---edge_trim_weight")),
        "rolled_leftover_weight": as_float(coil.get("---rolled_leftover_weight")),
        "rolled_leftover_width": as_float(rolled.get("width")),
        "rolled_leftover_length": as_float(rolled.get("length")),
        "processed_scrap_weight": as_float(coil.get("---processed_scrap_weight")),
    }


def add_values(coils: pd.DataFrame) -> pd.DataFrame:
    result = coils.copy()
    weight_columns = [
        "coil_weight", "strip_produced_weight", "strip_retail_weight",
        "strip_scrap_weight", "strip_loss_weight", "lateral_leftover_weight",
        "lateral_leftover_retail_weight", "lateral_leftover_scrap_weight",
        "edge_trim_weight", "rolled_leftover_weight", "processed_scrap_weight",
    ]
    for column in weight_columns:
        result[f"{column}_value"] = result[column] / 1000.0 * result["coil_ton_value"]
    return result


def read_generated_retails(scenario_root: Path, period: str) -> dict[str, Any]:
    next_period = f"period_{int(period.split('_')[1]) + 1}"
    path = scenario_root / next_period / "Retails.csv"
    if not path.exists():
        return {
            "retails_generated_count": 0,
            "retails_generated_weight": 0.0,
            "retails_generated_value": 0.0,
            "retails_file_exists": False,
        }
    frame = pd.read_csv(path)
    if frame.empty:
        return {
            "retails_generated_count": 0,
            "retails_generated_weight": 0.0,
            "retails_generated_value": 0.0,
            "retails_file_exists": True,
        }
    weights = pd.to_numeric(frame.get("Weight", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    values = pd.to_numeric(frame.get("Value", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    return {
        "retails_generated_count": int(len(frame)),
        "retails_generated_weight": round2(weights.sum()),
        "retails_generated_value": round2((weights / 1000.0 * values).sum()),
        "retails_file_exists": True,
    }


def aggregate_period(meta: dict[str, Any], instance: str, period: str,
                     coils: pd.DataFrame, retails: dict[str, Any]) -> dict[str, Any]:
    frame = add_values(coils)
    new = frame[(frame["processed"] == 0) & (frame["used"] == 1)]
    processed = frame[frame["processed"] == 1]

    def total(data: pd.DataFrame, column: str) -> float:
        return round2(data[column].sum())

    produced_weight = new["strip_produced_weight"].sum() + processed["strip_produced_weight"].sum()
    produced_value = new["strip_produced_weight_value"].sum() + processed["strip_produced_weight_value"].sum()

    row = {
        "scenario": meta["scenario"],
        "instance": instance,
        **{key: meta[key] for key in [
            "objective", "configuration", "retail_y_coefficient",
            "retail_v_coefficient", "rolled_leftover_coefficient"
        ]},
        "period": period,
        "period_number": int(period.split("_")[1]),
        "new_coils_used_count": int(len(new)),
        "new_coils_weight": total(new, "coil_weight"),
        "new_coils_value": total(new, "coil_weight_value"),
        "new_strip_produced_weight": total(new, "strip_produced_weight"),
        "new_strip_produced_value": total(new, "strip_produced_weight_value"),
        "new_strip_retail_weight": total(new, "strip_retail_weight"),
        "new_strip_retail_value": total(new, "strip_retail_weight_value"),
        "new_strip_scrap_weight": total(new, "strip_scrap_weight"),
        "new_strip_scrap_value": total(new, "strip_scrap_weight_value"),
        "new_strip_loss_weight": total(new, "strip_loss_weight"),
        "new_strip_loss_value": total(new, "strip_loss_weight_value"),
        "new_lateral_leftover_weight": total(new, "lateral_leftover_weight"),
        "new_lateral_leftover_value": total(new, "lateral_leftover_weight_value"),
        "new_lateral_retail_weight": total(new, "lateral_leftover_retail_weight"),
        "new_lateral_retail_value": total(new, "lateral_leftover_retail_weight_value"),
        "new_lateral_scrap_weight": total(new, "lateral_leftover_scrap_weight"),
        "new_lateral_scrap_value": total(new, "lateral_leftover_scrap_weight_value"),
        "new_edge_trim_weight": total(new, "edge_trim_weight"),
        "new_edge_trim_value": total(new, "edge_trim_weight_value"),
        "new_rolled_leftover_weight": total(new, "rolled_leftover_weight"),
        "new_rolled_leftover_value": total(new, "rolled_leftover_weight_value"),
        "new_partially_used_count": int((new["rolled_leftover_weight"] > 1e-9).sum()),
        "processed_coils_total_count": int(len(processed)),
        "processed_coils_used_count": int((processed["used"] == 1).sum()),
        "processed_coils_weight": total(processed, "coil_weight"),
        "processed_coils_value": total(processed, "coil_weight_value"),
        "processed_strip_produced_weight": total(processed, "strip_produced_weight"),
        "processed_strip_produced_value": total(processed, "strip_produced_weight_value"),
        "processed_scrap_weight": total(processed, "processed_scrap_weight"),
        "processed_scrap_value": total(processed, "processed_scrap_weight_value"),
        "total_strip_produced_weight": round2(produced_weight),
        "total_strip_produced_value": round2(produced_value),
        **retails,
    }
    return add_derived_metrics(row)


def add_derived_metrics(row: dict[str, Any]) -> dict[str, Any]:
    new_weight = as_float(row["new_coils_weight"])
    processed_weight = as_float(row["processed_coils_weight"])
    total_produced = as_float(row["total_strip_produced_weight"])
    reusable_weight = (
        as_float(row["new_strip_retail_weight"])
        + as_float(row["new_lateral_retail_weight"])
        + as_float(row["new_rolled_leftover_weight"])
    )
    reusable_value = (
        as_float(row["new_strip_retail_value"])
        + as_float(row["new_lateral_retail_value"])
        + as_float(row["new_rolled_leftover_value"])
    )
    scrap_weight = (
        as_float(row["new_strip_scrap_weight"])
        + as_float(row["new_lateral_scrap_weight"])
        + as_float(row["new_strip_loss_weight"])
        + as_float(row["new_edge_trim_weight"])
        + as_float(row["processed_scrap_weight"])
    )
    scrap_value = (
        as_float(row["new_strip_scrap_value"])
        + as_float(row["new_lateral_scrap_value"])
        + as_float(row["new_strip_loss_value"])
        + as_float(row["new_edge_trim_value"])
        + as_float(row["processed_scrap_value"])
    )
    row.update({
        "reusable_generated_weight": round2(reusable_weight),
        "reusable_generated_value": round2(reusable_value),
        "total_scrap_weight": round2(scrap_weight),
        "total_scrap_value": round2(scrap_value),
        "total_loss_weight": round2(scrap_weight),
        "total_loss_value": round2(scrap_value),
        "new_production_rate": round2(100.0 * safe_div(as_float(row["new_strip_produced_weight"]), new_weight)),
        "new_reusable_rate": round2(100.0 * safe_div(reusable_weight, new_weight)),
        "new_scrap_rate": round2(100.0 * safe_div(
            scrap_weight - as_float(row["processed_scrap_weight"]), new_weight
        )),
        "processed_recovery_rate": round2(100.0 * safe_div(
            as_float(row["processed_strip_produced_weight"]), processed_weight
        )),
        "processed_discard_rate": round2(100.0 * safe_div(
            as_float(row["processed_scrap_weight"]), processed_weight
        )),
        "reuse_dependency_rate": round2(100.0 * safe_div(
            as_float(row["processed_strip_produced_weight"]), total_produced
        )),
    })
    return row


def aggregate_groups(period_df: pd.DataFrame, group_columns: list[str]) -> pd.DataFrame:
    metadata = [
        "scenario", "objective", "configuration", "retail_y_coefficient",
        "retail_v_coefficient", "rolled_leftover_coefficient"
    ]
    grouping = metadata + group_columns
    aggregated = period_df.groupby(grouping, dropna=False, as_index=False)[SUM_COLUMNS].sum()
    rows = [add_derived_metrics(row) for row in aggregated.to_dict(orient="records")]
    return pd.DataFrame(rows)


def original_style_tables(period_df: pd.DataFrame, coil_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    identity = ["instance", "period", "period_number"]
    summary_columns = identity + [column for column in SUM_COLUMNS if not column.endswith("_value")]
    value_columns = identity + [
        column for column in SUM_COLUMNS
        if column.endswith("_value") or column.endswith("_count")
    ]
    rate_columns = identity + [
        "new_production_rate", "new_reusable_rate", "new_scrap_rate",
        "processed_recovery_rate", "processed_discard_rate", "reuse_dependency_rate"
    ]
    coil_columns = [column for column in COIL_COLUMNS if column not in {
        "objective", "configuration", "retail_y_coefficient", "retail_v_coefficient",
        "rolled_leftover_coefficient"
    }]
    return {
        "summary_by_instance_period.csv": period_df[summary_columns],
        "summary_value_by_instance_period.csv": period_df[value_columns],
        "rates_by_instance_period.csv": period_df[rate_columns],
        "coil_level_summary.csv": coil_df[coil_columns],
    }


def add_baseline_differences(instance_df: pd.DataFrame) -> pd.DataFrame:
    result = instance_df.copy()
    baseline = result[
        (result["objective"] == "new_coils_value")
        & (result["configuration"] == "default")
    ]
    if baseline.empty:
        return result
    baseline = baseline.set_index("instance")
    for metric in KEY_COMPARISON_METRICS:
        base_map = baseline[metric].to_dict()
        base_column = f"{metric}_baseline_ncv"
        diff_column = f"{metric}_diff_from_ncv"
        pct_column = f"{metric}_pct_diff_from_ncv"
        result[base_column] = result["instance"].map(base_map)
        result[diff_column] = result[metric] - result[base_column]
        result[pct_column] = result.apply(
            lambda row: round2(100.0 * safe_div(row[diff_column], row[base_column])), axis=1
        )
    return result


def build(project_root: Path, strict: bool) -> tuple[dict[str, pd.DataFrame], list[str]]:
    output_root = project_root / "output"
    scenarios, warnings = discover_scenarios(output_root)
    instances = sorted(path.name for path in output_root.iterdir() if path.is_dir())
    coil_rows: list[dict[str, Any]] = []
    period_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []

    for meta in scenarios:
        for instance in instances:
            scenario_root = output_root / instance / meta["objective"] / meta["configuration"]
            for period in PERIODS:
                plan_path = scenario_root / period / "cutting_plan.json"
                status = {
                    "scenario": meta["scenario"], "instance": instance,
                    "objective": meta["objective"], "configuration": meta["configuration"],
                    "period": period, "cutting_plan_exists": plan_path.exists(),
                    "retails_next_period_exists": (
                        scenario_root / f"period_{int(period.split('_')[1]) + 1}" / "Retails.csv"
                    ).exists(),
                }
                status_rows.append(status)
                if not plan_path.exists():
                    warnings.append(f"Missing cutting plan: {plan_path.relative_to(project_root)}")
                    continue
                if not status["retails_next_period_exists"]:
                    warnings.append(
                        "Missing generated retails: "
                        + str((
                            scenario_root
                            / f"period_{int(period.split('_')[1]) + 1}"
                            / "Retails.csv"
                        ).relative_to(project_root))
                    )
                try:
                    plan = read_cutting_plan(plan_path)
                    rows = [
                        coil_record(meta, instance, period, coil_id, coil)
                        for coil_id, coil in plan.items()
                    ]
                    if not rows:
                        warnings.append(f"Empty cutting plan: {plan_path.relative_to(project_root)}")
                        continue
                    coils = pd.DataFrame(rows, columns=COIL_COLUMNS)
                    retails = read_generated_retails(scenario_root, period)
                    period_rows.append(aggregate_period(meta, instance, period, coils, retails))
                    coil_rows.extend(rows)
                except Exception as error:
                    warnings.append(f"Error reading {plan_path.relative_to(project_root)}: {error}")

    if strict and warnings:
        raise RuntimeError("Validation failed:\n" + "\n".join(warnings))
    if not period_rows:
        raise RuntimeError("No valid cutting_plan.json was processed.")

    period_df = pd.DataFrame(period_rows).sort_values(["scenario", "instance", "period_number"])
    coil_df = pd.DataFrame(coil_rows, columns=COIL_COLUMNS).sort_values(
        ["objective", "configuration", "instance", "period_number", "processed", "coil_id"]
    )
    instance_df = aggregate_groups(period_df, ["instance"])
    instance_df = add_baseline_differences(instance_df)
    overall_df = aggregate_groups(period_df, [])
    ranking_df = overall_df.copy()
    for metric in KEY_COMPARISON_METRICS:
        ascending = metric not in {"new_production_rate", "processed_recovery_rate"}
        ranking_df[f"rank_{metric}"] = ranking_df[metric].rank(
            method="min", ascending=ascending
        ).astype(int)

    scenario_df = pd.DataFrame(scenarios)
    status_df = pd.DataFrame(status_rows).sort_values(["scenario", "instance", "period"])
    return {
        "scenario_catalog.csv": scenario_df,
        "validation_status.csv": status_df,
        "comparison_by_instance_period.csv": period_df,
        "comparison_by_instance.csv": instance_df,
        "comparison_overall.csv": overall_df,
        "comparison_rankings.csv": ranking_df,
        "all_coil_level_summary.csv": coil_df,
    }, warnings


def write_results(project_root: Path, tables: dict[str, pd.DataFrame]) -> None:
    comparison_dir = project_root / "results" / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in tables.items():
        frame.to_csv(comparison_dir / filename, index=False)

    period_df = tables["comparison_by_instance_period.csv"]
    coil_df = tables["all_coil_level_summary.csv"]
    for (objective, configuration), scenario_period in period_df.groupby(
        ["objective", "configuration"], dropna=False
    ):
        scenario_coils = coil_df[
            (coil_df["objective"] == objective)
            & (coil_df["configuration"] == configuration)
        ]
        destination = project_root / "results" / "by_configuration" / str(objective) / str(configuration)
        destination.mkdir(parents=True, exist_ok=True)
        for filename, frame in original_style_tables(scenario_period, scenario_coils).items():
            frame.to_csv(destination / filename, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate per-configuration and comparative slitting result tables."
    )
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(),
        help="Project root containing output/ (default: current directory)."
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Stop if any expected instance/scenario/period file is missing."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    output_root = project_root / "output"
    if not output_root.is_dir():
        raise FileNotFoundError(f"output/ folder not found at: {project_root}")

    tables, warnings = build(project_root, strict=args.strict)
    write_results(project_root, tables)
    print(f"Project root: {project_root}")
    print(f"Results: {project_root / 'results'}")
    print(f"Scenarios: {len(tables['scenario_catalog.csv'])}")
    print(f"Instance-period rows: {len(tables['comparison_by_instance_period.csv'])}")
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"WARNING: {warning}")


if __name__ == "__main__":
    main()
