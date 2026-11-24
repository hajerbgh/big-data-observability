from pathlib import Path
import sqlite3
import tempfile
import time

import pandas as pd

from src.anomaly_detection import ALERT_COLUMNS, detect_volume_and_drift_anomalies
from src.quality_rules import run_data_quality_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def simulate_micro_batches(
    csv_path: str,
    chunk_size: int = 500_000,
    output_dir: str | None = None,
    log_dir: str | None = None,
) -> pd.DataFrame:
    """Process a CSV in bounded-memory chunks and persist quality and anomaly logs."""
    if chunk_size <= 0:
        raise ValueError("chunk_size doit être strictement positif.")

    input_path = Path(csv_path)
    if not input_path.is_file():
        raise FileNotFoundError(f"Fichier source introuvable : {input_path}")

    batches_path = Path(output_dir) if output_dir else PROJECT_ROOT / "data" / "batches"
    logs_path = Path(log_dir) if log_dir else PROJECT_ROOT / "data"
    batches_path.mkdir(parents=True, exist_ok=True)
    logs_path.mkdir(parents=True, exist_ok=True)

    performance_logs: list[dict] = []
    quality_logs: list[pd.DataFrame] = []
    anomaly_logs: list[pd.DataFrame] = []
    reference_data: pd.DataFrame | None = None

    print(f"Début du traitement par micro-lots de {chunk_size:,} lignes.")
    reader = pd.read_csv(input_path, chunksize=chunk_size, low_memory=False)
    batch_id = 0
    temporary_directory = tempfile.TemporaryDirectory(prefix="data-observability-ids-")
    id_connection = sqlite3.connect(
        Path(temporary_directory.name) / "seen_ids.sqlite"
    )
    try:
        id_connection.execute("PRAGMA journal_mode=OFF")
        id_connection.execute("PRAGMA synchronous=OFF")
        id_connection.execute("CREATE TABLE seen_ids (id TEXT PRIMARY KEY)")
        while True:
            read_started = time.perf_counter()
            try:
                chunk = next(reader)
            except StopIteration:
                break
            read_seconds = time.perf_counter() - read_started

            batch_id += 1
            batch_name = f"batch_{batch_id:03d}"
            batch_file = batches_path / f"{batch_name}.csv"
            process_started = time.perf_counter()

            batch_quality = run_data_quality_checks(chunk)
            if "ID" in chunk.columns:
                ids = chunk["ID"].dropna()
                previous_changes = id_connection.total_changes
                id_connection.executemany(
                    "INSERT OR IGNORE INTO seen_ids (id) VALUES (?)",
                    ((str(value),) for value in ids),
                )
                duplicate_ids = len(ids) - (
                    id_connection.total_changes - previous_changes
                )
                id_connection.commit()
                duplicate_rule = (
                    (batch_quality["Rule_Category"] == "Uniqueness")
                    & (batch_quality["Target_Attribute"] == "ID")
                )
                batch_quality.loc[duplicate_rule, "Error_Count"] = duplicate_ids
                batch_quality.loc[
                    duplicate_rule, "Affected_Record_Count"
                ] = duplicate_ids
                if len(chunk):
                    conformity_rate = round(
                        (1 - duplicate_ids / len(chunk)) * 100, 4
                    )
                    batch_quality.loc[
                        duplicate_rule, "Conformity_Rate_%"
                    ] = conformity_rate

            batch_quality.insert(0, "Batch_ID", batch_name)
            quality_logs.append(batch_quality)

            if reference_data is None:
                reference_columns = [
                    column
                    for column in (
                        "Start_Time",
                        "Severity",
                        "Temperature(F)",
                        "Distance(mi)",
                    )
                    if column in chunk.columns
                ]
                reference_data = chunk[reference_columns].copy()
            else:
                anomaly_logs.append(
                    detect_volume_and_drift_anomalies(
                        reference_data,
                        chunk,
                        batch_id=batch_name,
                        complete_days_only=True,
                    )
                )

            process_seconds = time.perf_counter() - process_started
            write_started = time.perf_counter()
            chunk.to_csv(batch_file, index=False)
            write_seconds = time.perf_counter() - write_started
            record_count = len(chunk)
            execution_seconds = read_seconds + process_seconds + write_seconds

            performance_logs.append(
                {
                    "Batch_ID": batch_name,
                    "Chunk_Size": chunk_size,
                    "Record_Count": record_count,
                    "Read_Time_Seconds": round(read_seconds, 4),
                    "Processing_Time_Seconds": round(process_seconds, 4),
                    "Write_Time_Seconds": round(write_seconds, 4),
                    "Execution_Time_Seconds": round(execution_seconds, 4),
                    "Processing_Speed_Rows_Per_Sec": round(
                        record_count / max(execution_seconds, 0.001), 2
                    ),
                    "Memory_Usage_MB": round(
                        chunk.memory_usage(index=True, deep=True).sum() / (1024**2),
                        2,
                    ),
                    "Missing_Start_Time": int(chunk["Start_Time"].isna().sum())
                    if "Start_Time" in chunk.columns
                    else 0,
                }
            )
            print(
                f"-> {batch_name}: {record_count:,} lignes, "
                f"{execution_seconds:.2f} s (lecture, contrôles et écriture)."
            )
            del chunk
    finally:
        id_connection.close()
        temporary_directory.cleanup()

    pd.DataFrame(performance_logs).to_csv(
        logs_path / "performance_log.csv", index=False
    )
    quality_metrics = (
        pd.concat(quality_logs, ignore_index=True)
        if quality_logs
        else pd.DataFrame()
    )
    quality_metrics.to_csv(logs_path / "quality_metrics.csv", index=False)

    alerts = (
        pd.concat(anomaly_logs, ignore_index=True).reindex(columns=ALERT_COLUMNS)
        if anomaly_logs
        else pd.DataFrame(columns=ALERT_COLUMNS)
    )
    alerts.to_csv(logs_path / "alerts_log.csv", index=False)

    print(f"Traitement terminé. Journaux écrits dans {logs_path}.")
    return pd.DataFrame(performance_logs)
