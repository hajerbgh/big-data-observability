"""
Benchmark comparatif : chunk_size = 100 000 lignes vs 1 000 000 lignes.
Lit le CSV source par chunks, applique les contrôles qualité et mesure les temps.
N'écrit PAS de fichiers batch afin de ne pas dupliquer les données.
Produit deux fichiers performance_log.csv dans data/benchmarks/<config>/.
"""
import sys
import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.anomaly_detection import ALERT_COLUMNS, detect_volume_and_drift_anomalies
from src.quality_rules import run_data_quality_checks

CSV_SOURCE = PROJECT_ROOT / "data" / "US_Accidents_March23.csv"
BENCHMARKS_DIR = PROJECT_ROOT / "data" / "benchmarks"
REFERENCE_COLS = ["Start_Time", "Severity", "Temperature(F)", "Distance(mi)"]

CONFIGS = [100_000, 1_000_000]


def run_benchmark(chunk_size: int) -> None:
    label = f"{chunk_size // 1000}k"
    out_dir = BENCHMARKS_DIR / label
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*55}")
    print(f"  Configuration : chunk_size = {chunk_size:,} lignes  ({label})")
    print(f"{'='*55}")

    performance_logs: list[dict] = []
    quality_logs: list[pd.DataFrame] = []
    anomaly_logs: list[pd.DataFrame] = []
    reference_data: pd.DataFrame | None = None

    reader = pd.read_csv(CSV_SOURCE, chunksize=chunk_size, low_memory=False)
    batch_id = 0

    for chunk in reader:
        batch_id += 1
        batch_name = f"batch_{batch_id:03d}"

        process_start = time.perf_counter()
        batch_quality = run_data_quality_checks(chunk)

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
        performance_logs.append(
            {
                "Batch_ID": batch_name,
                "Chunk_Size": chunk_size,
                "Record_Count": record_count,
                "Processing_Time_Seconds": round(process_seconds, 4),
                "Processing_Speed_Rows_Per_Sec": round(
                    record_count / max(process_seconds, 0.001), 2
                ),
                "Memory_Usage_MB": round(
                    chunk.memory_usage(index=True, deep=True).sum() / (1024**2), 2
                ),
            }
        )
        del chunk
        print(f"  {batch_name}: {record_count:,} lignes — {process_seconds:.3f}s")

    df_perf = pd.DataFrame(performance_logs)
    df_perf.to_csv(out_dir / "performance_log.csv", index=False)

    alerts = (
        pd.concat(anomaly_logs, ignore_index=True).reindex(columns=ALERT_COLUMNS)
        if anomaly_logs
        else pd.DataFrame(columns=ALERT_COLUMNS)
    )
    alerts.to_csv(out_dir / "alerts_log.csv", index=False)

    total_rows = df_perf["Record_Count"].sum()
    total_time = df_perf["Processing_Time_Seconds"].sum()
    avg_speed = total_rows / max(total_time, 0.001)
    print(f"\n  Résumé {label}:")
    print(f"    Lots traités       : {len(df_perf)}")
    print(f"    Lignes totales     : {total_rows:,}")
    print(f"    Temps total (s)    : {total_time:.2f}")
    print(f"    Débit moyen (rows/s): {avg_speed:,.0f}")
    print(f"    Logs écrits dans   : {out_dir}")


def compare_results() -> None:
    print(f"\n{'='*55}")
    print("  COMPARAISON DES DEUX CONFIGURATIONS")
    print(f"{'='*55}")
    rows = []
    for chunk_size in CONFIGS:
        label = f"{chunk_size // 1000}k"
        log_path = BENCHMARKS_DIR / label / "performance_log.csv"
        if not log_path.exists():
            print(f"  ⚠️  {log_path} introuvable, skip.")
            continue
        df = pd.read_csv(log_path)
        total_rows = df["Record_Count"].sum()
        total_time = df["Processing_Time_Seconds"].sum()
        rows.append(
            {
                "Config (chunk_size)": f"{chunk_size:,}",
                "Nb lots": len(df),
                "Lignes totales": f"{total_rows:,}",
                "Temps total (s)": f"{total_time:.2f}",
                "Débit moyen (rows/s)": f"{total_rows / max(total_time, 0.001):,.0f}",
                "RAM/lot moy. (MB)": f"{df['Memory_Usage_MB'].mean():.1f}",
            }
        )
    if rows:
        df_cmp = pd.DataFrame(rows)
        df_cmp.to_csv(BENCHMARKS_DIR / "comparison.csv", index=False)
        print(df_cmp.to_string(index=False))
        print(f"\n  ✅  Tableau de comparaison : {BENCHMARKS_DIR / 'comparison.csv'}")


def main() -> None:
    if not CSV_SOURCE.is_file():
        print(f"CSV source introuvable : {CSV_SOURCE}")
        sys.exit(1)
    for chunk_size in CONFIGS:
        run_benchmark(chunk_size)
    compare_results()


if __name__ == "__main__":
    main()
