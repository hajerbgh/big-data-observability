import pandas as pd


NUMERIC_COLUMNS = (
    "Start_Lat",
    "Start_Lng",
    "End_Lat",
    "End_Lng",
    "Severity",
    "Distance(mi)",
    "Temperature(F)",
    "Wind_Chill(F)",
    "Humidity(%)",
    "Pressure(in)",
    "Visibility(mi)",
    "Wind_Speed(mph)",
    "Precipitation(in)",
)
DATE_COLUMNS = ("Start_Time", "End_Time", "Weather_Timestamp")


def _add_metric(
    metrics: list[dict],
    category: str,
    attribute: str,
    error_mask: pd.Series,
    total_rows: int,
) -> None:
    error_count = int(error_mask.sum())
    conformity_rate = (
        round((1 - error_count / total_rows) * 100, 4) if total_rows else 100.0
    )
    metrics.append(
        {
            "Rule_Category": category,
            "Target_Attribute": attribute,
            "Error_Count": error_count,
            "Affected_Record_Count": error_count,
            "Total_Record_Count": total_rows,
            "Conformity_Rate_%": conformity_rate,
        }
    )


def run_data_quality_checks(df: pd.DataFrame) -> pd.DataFrame:
    """Measure completeness, uniqueness, validity, consistency and conformity."""
    total_rows = len(df)
    metrics: list[dict] = []

    for column in df.columns:
        _add_metric(
            metrics,
            "Completeness",
            column,
            df[column].isna(),
            total_rows,
        )

    if "ID" in df.columns:
        duplicate_ids = df["ID"].notna() & df["ID"].duplicated(keep="first")
        _add_metric(metrics, "Uniqueness", "ID", duplicate_ids, total_rows)

    for column in DATE_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column]
        parsed = pd.to_datetime(values, errors="coerce", utc=True, format="mixed")
        invalid_format = values.notna() & parsed.isna()
        _add_metric(metrics, "Conformity", column, invalid_format, total_rows)

    for column in NUMERIC_COLUMNS:
        if column not in df.columns:
            continue
        values = df[column]
        numeric_values = pd.to_numeric(values, errors="coerce")
        invalid_format = values.notna() & numeric_values.isna()
        _add_metric(metrics, "Conformity", column, invalid_format, total_rows)

    if {"Start_Lat", "Start_Lng"}.issubset(df.columns):
        lat = pd.to_numeric(df["Start_Lat"], errors="coerce")
        lng = pd.to_numeric(df["Start_Lng"], errors="coerce")
        has_both_coordinates = lat.notna() & lng.notna()
        invalid_coordinates = has_both_coordinates & (
            ~lat.between(-90, 90) | ~lng.between(-180, 180)
        )
        _add_metric(
            metrics,
            "Validity",
            "Coordinates (Lat/Lng)",
            invalid_coordinates,
            total_rows,
        )

    if "Severity" in df.columns:
        severity = pd.to_numeric(df["Severity"], errors="coerce")
        invalid_severity = severity.notna() & (
            ~severity.between(1, 4) | (severity % 1 != 0)
        )
        _add_metric(metrics, "Validity", "Severity", invalid_severity, total_rows)

    if "Temperature(F)" in df.columns:
        temperature = pd.to_numeric(df["Temperature(F)"], errors="coerce")
        invalid_temperature = temperature.notna() & ~temperature.between(-50, 130)
        _add_metric(
            metrics,
            "Validity",
            "Temperature(F)",
            invalid_temperature,
            total_rows,
        )

    if {"Start_Time", "End_Time"}.issubset(df.columns):
        start_time = pd.to_datetime(
            df["Start_Time"], errors="coerce", utc=True, format="mixed"
        )
        end_time = pd.to_datetime(
            df["End_Time"], errors="coerce", utc=True, format="mixed"
        )
        comparable_times = start_time.notna() & end_time.notna()
        inconsistent_time = comparable_times & (start_time >= end_time)
        _add_metric(
            metrics,
            "Consistency",
            "Start_Time < End_Time",
            inconsistent_time,
            total_rows,
        )

    return pd.DataFrame(
        metrics,
        columns=[
            "Rule_Category",
            "Target_Attribute",
            "Error_Count",
            "Affected_Record_Count",
            "Total_Record_Count",
            "Conformity_Rate_%",
        ],
    )
