#!/usr/bin/env python3
"""
normalize_results.py

Usage:
  # Normalize a PQC run folder (copy files into normalized outdir)
  python3 normalize_results.py --pqc-run /path/to/pqc_run --outdir normalized/pqc_run

  # Normalize a SECOC (CAN) CSV produced by secoc_dos_sim_metrics.py
  python3 normalize_results.py --can-csv dos_can_results.csv --frames 2000 --outdir normalized/secoc_run

Notes:
 - For CAN CSV we assume the last 'frame_id' value is the total frames sent.
 - For CAN CSV we assume frames are successful unless you supply a receiver-side success count (see --successes).
 - Outputs: outdir/{summary.json, requests.csv, system.csv}
"""
import argparse
import csv
import json
import os
import math
from datetime import datetime
import pandas as pd
import numpy as np

def normalize_pqc(run_dir, outdir):
    # expect summary.json, requests.csv, system.csv optionally
    os.makedirs(outdir, exist_ok=True)
    for name in ("summary.json","requests.csv","system.csv"):
        src = os.path.join(run_dir, name)
        dst = os.path.join(outdir, name)
        if os.path.exists(src):
            print(f"Copying {src} -> {dst}")
            with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
                fdst.write(fsrc.read())
    print("PQC normalization done.")

def normalize_can(csv_path, total_frames=None, successes=None, outdir="normalized_can"):
    os.makedirs(outdir, exist_ok=True)
    df = pd.read_csv(csv_path)
    # CSV expected columns: timestamp, frame_id, cpu_percent, mem_mb, fps
    # make system.csv from the CAN CSV (rename timestamp->ts)
    sys_df = df.rename(columns={"timestamp":"ts"})
    sys_csv = os.path.join(outdir, "system.csv")
    sys_df.to_csv(sys_csv, index=False)
    # summary.json: use last frame_id as total, estimate successes if not provided
    last_frame = int(df['frame_id'].iloc[-1])
    total = total_frames if total_frames is not None else last_frame
    if successes is None:
        # assume success == total (best-case), but warn user
        successes = total
        assumed = True
    else:
        assumed = False
    failures = total - successes
    success_rate = (successes/total*100.0) if total>0 else None

    # No latency values for CAN; set lat_* to null (or 0) — we'll use fps/time series instead
    summary = {
        "total": int(total),
        "successes": int(successes),
        "failures": int(failures),
        "success_rate_pct": float(success_rate) if success_rate is not None else None,
        "lat_p50_ms": None,
        "lat_p90_ms": None,
        "lat_p99_ms": None,
        "lat_mean_ms": None,
        "start_time": None,
        "end_time": None,
        "duration_s": None,
        "sample_count": int(len(df)),
        "args": {
            "source_csv": os.path.basename(csv_path),
            "assumed_all_success": bool(assumed)
        }
    }
    # if timestamps present, set times/duration
    try:
        ts0 = float(df['timestamp'].iloc[0])
        ts1 = float(df['timestamp'].iloc[-1])
        summary['start_time'] = datetime.utcfromtimestamp(ts0).isoformat() + "Z"
        summary['end_time'] = datetime.utcfromtimestamp(ts1).isoformat() + "Z"
        summary['duration_s'] = ts1 - ts0
    except Exception:
        pass

    with open(os.path.join(outdir,"summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # Create an aggregated requests.csv: one row per sample (frame_id)
    req_csv = os.path.join(outdir,"requests.csv")
    with open(req_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["idx","ts","success","latency_ms","resp_len","err"])
        w.writeheader()
        for i,row in df.iterrows():
            ts = row['timestamp']
            idx = int(row['frame_id'])
            w.writerow({
                "idx": idx,
                "ts": datetime.utcfromtimestamp(float(ts)).isoformat() + "Z" if not math.isnan(float(ts)) else "",
                "success": True,
                "latency_ms": "",
                "resp_len": "",
                "err": ""
            })
    print(f"CAN normalization done -> {outdir} (assumed_all_success={assumed})")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pqc-run", help="Directory containing PQC run (summary.json, requests.csv, system.csv)")
    p.add_argument("--can-csv", help="Path to CAN csv (dos_can_results.csv)")
    p.add_argument("--frames", type=int, default=None, help="Total frames sent (optional override)")
    p.add_argument("--successes", type=int, default=None, help="Receiver-observed successes (optional override)")
    p.add_argument("--outdir", default="normalized_run", help="Output normalized directory")
    args = p.parse_args()

    if args.pqc_run:
        normalize_pqc(args.pqc_run, args.outdir)
    elif args.can_csv:
        normalize_can(args.can_csv, total_frames=args.frames, successes=args.successes, outdir=args.outdir)
    else:
        print("Provide --pqc-run or --can-csv")
        return

if __name__ == "__main__":
    main()

