#!/bin/bash
set -e

# ==========================================
# CONFIGURATION
# ==========================================
HOST="127.0.0.1"
PORT_SECOC=65432
PORT_PQC=65433
CONCURRENCY=200
TOTAL=5000
REPEATS=5

# Paths to your Python files (adjust if needed)
DOS_SIM="./dos_simulator.py"
SECOC_RX="./secoc_receiver_tcp.py"
PQC_RX="./receiver_pqc.py"
NORMALIZE="./normalize_results.py"
ANALYZE="./analyze_runs.py"

# PQC workload (controls cryptographic cost)
export PQC_WORKLOAD=500000   # You can tune this: 5000 (light), 500000 (heavy)

# ==========================================
# PREPARE OUTPUT FOLDERS
# ==========================================
mkdir -p results normalized analysis

echo "=========================================="
echo "Running Automated SECOC vs PQC DoS Experiments"
echo "=========================================="
echo "Repeats=${REPEATS} | Concurrency=${CONCURRENCY} | Total=${TOTAL}"
echo "SECOC port=${PORT_SECOC} | PQC port=${PORT_PQC}"
echo "PQC workload=${PQC_WORKLOAD}"
echo

for ((i=1; i<=REPEATS; i++)); do
  TS=$(date +"%Y%m%dT%H%M%S")
  echo "=== RUN ${i} (${TS}) ==="

  # ------------------------------
  # SECOC RUN
  # ------------------------------
  echo "[SECOC] Starting receiver on port ${PORT_SECOC}..."
  python3 $SECOC_RX > results/secoc_rx_${TS}.log 2>&1 &
  RX_PID=$!
  sleep 2

  echo "[SECOC] Running DoS simulation..."
  python3 $DOS_SIM --host $HOST --port $PORT_SECOC \
      --mode churn --concurrency $CONCURRENCY --total $TOTAL \
      --outdir results/secoc_tcp_${TS} > results/secoc_dos_${TS}.log 2>&1 || true

  echo "[SECOC] Cleaning up receiver..."
  kill $RX_PID >/dev/null 2>&1 || true
  sleep 3

  # ------------------------------
  # PQC RUN
  # ------------------------------
  echo "[PQC] Starting receiver on port ${PORT_PQC}..."
  PQC_WORKLOAD=$PQC_WORKLOAD python3 $PQC_RX > results/pqc_rx_${TS}.log 2>&1 &
  RX_PID=$!
  sleep 2

  echo "[PQC] Running DoS simulation..."
  python3 $DOS_SIM --host $HOST --port $PORT_PQC \
      --mode churn --concurrency $CONCURRENCY --total $TOTAL \
      --outdir results/pqc_tcp_${TS} > results/pqc_dos_${TS}.log 2>&1 || true

  echo "[PQC] Cleaning up receiver..."
  kill $RX_PID >/dev/null 2>&1 || true
  sleep 3

  echo "[DONE] Finished run ${i} (${TS})"
  echo "Cooling down CPU for 10s..."
  sleep 10
  echo
done

# ==========================================
# NORMALIZATION AND ANALYSIS
# ==========================================
echo "=========================================="
echo "Normalizing all result JSONs into CSVs..."
echo "=========================================="

# Normalize latest SECOC
SECJSON=$(ls -td results/*secoc_tcp* | head -n 1)
python3 $NORMALIZE --pqc-run "$SECJSON" --outdir normalized/$(basename $SECJSON)

# Normalize latest PQC
PQCJSON=$(ls -td results/*pqc_tcp* | head -n 1)
python3 $NORMALIZE --pqc-run "$PQCJSON" --outdir normalized/$(basename $PQCJSON)

echo "=========================================="
echo "Comparing PQC vs SECOC performance..."
echo "=========================================="

# Find latest normalized subfolders
PQC_DIR=$(ls -td normalized/*pqc* | head -n 1)
SECOC_DIR=$(ls -td normalized/*secoc* | head -n 1)

python3 $ANALYZE "$PQC_DIR" "$SECOC_DIR"

# Move results to analysis folder
mv compare_summary.csv analysis/compare_summary_$(date +"%Y%m%dT%H%M%S").csv 2>/dev/null || true
mv compare_*.png analysis/ 2>/dev/null || true

echo
echo "[DONE] All experiments complete!"
echo "Results saved under: results/"
echo "Normalized data in: normalized/"
echo "Analysis and graphs in: analysis/"

