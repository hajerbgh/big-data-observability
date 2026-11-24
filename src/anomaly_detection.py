from datetime import datetime

import numpy as np
import pandas as pd


ALERT_COLUMNS = [
    "Timestamp",
    "Batch_ID",
    "Anomaly_Type",
    "Target_Variable",
    "Metric_Value",
    "Threshold_Reference",
    "Severity_Level",
    "Message",
]
DRIFT_COLUMNS = ("Severity", "Temperature(F)", "Distance(mi)")
OUTLIER_COLUMNS = ("Temperature(F)", "Distance(mi)")
DRIFT_THRESHOLD = 0.2
OUTLIER_RATE_THRESHOLD = 0.01


def _numeric_values(frame: pd.DataFrame, column: str) -> np.ndarray:
    if column not in frame.columns:
        return np.array([], dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
    return values[np.isfinite(values)]


def _population_stability_index(
    historical: np.ndarray, current: np.ndarray, column: str
) -> float | None:
    historical = historical[np.isfinite(historical)]
    current = current[np.isfinite(current)]
    if historical.size == 0 or current.size == 0:
        return None

    if column == "Severity":
        edges = np.array([-np.inf, 0.5, 1.5, 2.5, 3.5, 4.5, np.inf])
    else:
        quantiles = np.quantile(historical, np.linspace(0, 1, 11))
        inner_edges = np.unique(quantiles)
        edges = np.concatenate(([-np.inf], inner_edges, [np.inf]))

    expected = np.histogram(historical, bins=edges)[0].astype(float)
    actual = np.histogram(current, bins=edges)[0].astype(float)
    expected = (expected + 1e-6) / (expected.sum() + 1e-6 * len(expected))
    actual = (actual + 1e-6) / (actual.sum() + 1e-6 * len(actual))
    return float(np.sum((actual - expected) * np.log(actual / expected)))


def detect_volume_and_drift_anomalies(
    df_historical: pd.DataFrame,
    df_current_batch: pd.DataFrame,
    batch_id: str,
    *,
    complete_days_only: bool = False,
) -> pd.DataFrame:
    """Compare daily volumes and feature distributions against a historical baseline."""
    alerts: list[dict] = []
    timestamp = datetime.now().isoformat(timespec="seconds")

    if "Start_Time" in df_historical and "Start_Time" in df_current_batch:
        historical_dates = pd.to_datetime(
            df_historical["Start_Time"],
            errors="coerce",
            utc=True,
            format="mixed",
        ).dropna()
        current_dates = pd.to_datetime(
            df_current_batch["Start_Time"],
            errors="coerce",
            utc=True,
            format="mixed",
        ).dropna()

        if not historical_dates.empty and not current_dates.empty:
            historical_counts = historical_dates.dt.floor("D").value_counts()
            date_range = pd.date_range(
                historical_counts.index.min(),
                historical_counts.index.max(),
                freq="D",
                tz="UTC",
            )
            daily_baseline = historical_counts.reindex(date_range, fill_value=0)
            if len(daily_baseline) > 2:
                daily_baseline = daily_baseline.iloc[1:-1]

            if len(daily_baseline) >= 7:
                mean_volume = float(daily_baseline.mean())
                std_volume = float(daily_baseline.std(ddof=1))
                scale = max(std_volume, np.sqrt(mean_volume), 1.0)
                current_counts = current_dates.dt.floor("D").value_counts().sort_index()
                if len(current_counts) > 2:
                    current_counts = current_counts.iloc[1:-1]
                elif complete_days_only:
                    current_counts = current_counts.iloc[0:0]

                for day, current_volume in current_counts.items():
                    z_score = (float(current_volume) - mean_volume) / scale
                    if abs(z_score) >= 3:
                        anomaly_type = "Volume Drop" if z_score < 0 else "Volume Spike"
                        alerts.append(
                            {
                                "Timestamp": timestamp,
                                "Batch_ID": batch_id,
                                "Anomaly_Type": anomaly_type,
                                "Target_Variable": "Daily_Record_Count",
                                "Metric_Value": int(current_volume),
                                "Threshold_Reference": round(mean_volume, 2),
                                "Severity_Level": "HIGH" if abs(z_score) >= 4 else "MEDIUM",
                                "Message": (
                                    f"Volume anormal le {day.date()} : {current_volume} "
                                    f"enregistrements (moyenne historique quotidienne "
                                    f"{mean_volume:.2f}, z-score {z_score:.2f})."
                                ),
                            }
                        )

    for column in DRIFT_COLUMNS:
        historical = _numeric_values(df_historical, column)
        current = _numeric_values(df_current_batch, column)
        psi = _population_stability_index(historical, current, column)
        if psi is not None and psi >= DRIFT_THRESHOLD:
            alerts.append(
                {
                    "Timestamp": timestamp,
                    "Batch_ID": batch_id,
                    "Anomaly_Type": "Data Drift",
                    "Target_Variable": column,
                    "Metric_Value": round(psi, 4),
                    "Threshold_Reference": DRIFT_THRESHOLD,
                    "Severity_Level": "HIGH" if psi >= 0.5 else "MEDIUM",
                    "Message": (
                        f"Dérive de distribution détectée sur {column} "
                        f"(PSI={psi:.4f}, seuil={DRIFT_THRESHOLD})."
                    ),
                }
            )

    for column in OUTLIER_COLUMNS:
        historical = _numeric_values(df_historical, column)
        current = _numeric_values(df_current_batch, column)
        if historical.size < 4 or current.size == 0:
            continue

        first_quartile, third_quartile = np.quantile(historical, [0.25, 0.75])
        spread = third_quartile - first_quartile
        lower_bound = first_quartile - 1.5 * spread
        upper_bound = third_quartile + 1.5 * spread
        outlier_count = int(((current < lower_bound) | (current > upper_bound)).sum())
        outlier_rate = outlier_count / current.size
        if outlier_rate >= OUTLIER_RATE_THRESHOLD:
            alerts.append(
                {
                    "Timestamp": timestamp,
                    "Batch_ID": batch_id,
                    "Anomaly_Type": "Numeric Outlier",
                    "Target_Variable": column,
                    "Metric_Value": round(outlier_rate * 100, 4),
                    "Threshold_Reference": OUTLIER_RATE_THRESHOLD * 100,
                    "Severity_Level": "HIGH" if outlier_rate >= 0.05 else "MEDIUM",
                    "Message": (
                        f"{outlier_count} valeurs aberrantes sur {current.size} valeurs "
                        f"de {column} ({outlier_rate:.2%}); bornes IQR historiques "
                        f"[{lower_bound:.4g}, {upper_bound:.4g}]."
                    ),
                }
            )

    return pd.DataFrame(alerts, columns=ALERT_COLUMNS)
