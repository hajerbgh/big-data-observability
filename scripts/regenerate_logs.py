"""
Régénère quality_metrics.csv, alerts_log.csv et performance_log.csv
à partir des fichiers batch déjà présents dans data/batches/.
Bien plus rapide que relire le CSV source de 3 Go.
"""
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.anomaly_detection import ALERT_COLUMNS, detect_volume_and_drift_anomalies
from src.quality_rules import run_data_quality_checks

BATCHES_DIR = PROJECT_ROOT / "data" / "batches"
LOGS_DIR = PROJECT_ROOT / "data"

REFERENCE_COLS = ["Start_Time", "Severity", "Temperature(F)", "Distance(mi)"]


def main() -> None:
    batch_files = sorted(BATCHES_DIR.glob("batch_*.csv"))
    if not batch_files:
        print("Aucun fichier batch trouvé dans", BATCHES_DIR)
        sys.exit(1)

    print(f"{len(batch_files)} fichiers batch trouvés.\n")

    performance_logs: list[dict] = []
    quality_logs: list[pd.DataFrame] = []
    anomaly_logs: list[pd.DataFrame] = []
    reference_data: pd.DataFrame | None = None

    for batch_file in batch_files:
        batch_name = batch_file.stem
        print(f"Traitement de {batch_name} ...", end=" ", flush=True)

        read_start = time.perf_counter()
        chunk = pd.read_csv(batch_file, low_memory=False)
        read_seconds = time.perf_counter() - read_start

        process_start = time.perf_counter()
        batch_quality = run_data_quality_checks(chunk)
        batch_quality.insert(0, "Batch_ID", batch_name)
        quality_logs.append(batch_quality)

        if reference_data is None:
            ref_cols = [c for c in REFERENCE_COLS if c in chunk.columns]
            reference_data = chunk[ref_cols].copy()
        else:
            anomaly_logs.append(
                detect_volume_and_drift_anomalies(
                    reference_data,
                    chunk,
                    batch_id=batch_name,
                    complete_days_only=True,
                )
            )
        process_seconds = time.perf_counter() - process_start

        record_count = len(chunk)
        execution_seconds = read_seconds + process_seconds
        performance_logs.append(
            {
                "Batch_ID": batch_name,
                "Chunk_Size": record_count,
                "Record_Count": record_count,
                "Read_Time_Seconds": round(read_seconds, 4),
                "Processing_Time_Seconds": round(process_seconds, 4),
                "Write_Time_Seconds": 0.0,
                "Execution_Time_Seconds": round(execution_seconds, 4),
                "Processing_Speed_Rows_Per_Sec": round(
                    record_count / max(execution_seconds, 0.001), 2
                ),
                "Memory_Usage_MB": round(
                    chunk.memory_usage(index=True, deep=True).sum() / (1024**2), 2
                ),
                "Missing_Start_Time": int(chunk["Start_Time"].isna().sum())
                if "Start_Time" in chunk.columns
                else 0,
            }
        )
        del chunk
        print(f"{record_count:,} lignes — {execution_seconds:.2f}s")

    # Écrire les fichiers
    pd.DataFrame(performance_logs).to_csv(LOGS_DIR / "performance_log.csv", index=False)
    print("\n✅  performance_log.csv mis à jour.")

    pd.concat(quality_logs, ignore_index=True).to_csv(
        LOGS_DIR / "quality_metrics.csv", index=False
    )
    print("✅  quality_metrics.csv mis à jour.")

    alerts = (
        pd.concat(anomaly_logs, ignore_index=True).reindex(columns=ALERT_COLUMNS)
        if anomaly_logs
        else pd.DataFrame(columns=ALERT_COLUMNS)
    )
    alerts.to_csv(LOGS_DIR / "alerts_log.csv", index=False)
    print(f"✅  alerts_log.csv mis à jour ({len(alerts)} alerte(s)).")


if __name__ == "__main__":
    main()
