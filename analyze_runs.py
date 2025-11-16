import os
import json
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import sys

def load_run(folder):
    summary_path = os.path.join(folder, "summary.json")
    if not os.path.exists(summary_path):
        raise FileNotFoundError(f"No summary.json found in {folder}")
    with open(summary_path, "r") as f:
        summary = json.load(f)
    summary_flat = {k: v for k, v in summary.items() if not isinstance(v, dict)}

    system_csv = os.path.join(folder, "system.csv")
    requests_csv = os.path.join(folder, "requests.csv")
    sys_df = pd.read_csv(system_csv) if os.path.exists(system_csv) else None
    req_df = pd.read_csv(requests_csv) if os.path.exists(requests_csv) else None
    return summary_flat, sys_df, req_df

def safe_num(x):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return 0
        return float(x)
    except Exception:
        return 0

def plot_bars(summaryA, summaryB, labelA, labelB):
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    fig.suptitle("Run Comparison: Success Rate & Latency")

    sa, sb = summaryA, summaryB
    rateA = safe_num(sa.get("success_rate_pct"))
    rateB = safe_num(sb.get("success_rate_pct"))
    p99a = safe_num(sa.get("lat_p99_ms"))
    p99b = safe_num(sb.get("lat_p99_ms"))

    axes[0].bar([0, 1], [rateA, rateB], tick_label=[labelA, labelB], color=["#4CAF50", "#2196F3"])
    axes[0].set_ylabel("Success Rate (%)")

    axes[1].bar([0, 1], [p99a, p99b], tick_label=[labelA, labelB], color=["#FF9800", "#9C27B0"])
    axes[1].set_ylabel("p99 Latency (ms)")

    plt.tight_layout()
    plt.savefig("compare_bars.png", dpi=150)
    print("[DONE] Saved compare_bars.png")

def get_time_column(df):
    """Return the best available time-like column name or None."""
    for c in ["timestamp", "time", "frame_id"]:
        if c in df.columns:
            return c
    return None

def plot_timeseries(sysA, sysB, reqA, reqB, labelA, labelB):
    if sysA is None or sysB is None:
        print("---->Skipping time-series plot (missing system.csv)")
        return

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax2 = ax1.twinx()

    def get_best_x(df):
        for c in ["timestamp", "time", "frame_id"]:
            if c in df.columns:
                return df[c]
        return pd.Series(range(len(df)))  # fallback to index

    timeA = get_best_x(sysA)
    timeB = get_best_x(sysB)

    # Plot CPU
    ax1.plot(timeA, sysA.get("cpu_percent", pd.Series([0]*len(sysA))),
             label=f"{labelA} CPU%", color="tab:blue", alpha=0.6)
    ax1.plot(timeB, sysB.get("cpu_percent", pd.Series([0]*len(sysB))),
             label=f"{labelB} CPU%", color="tab:green", alpha=0.6)

    # Plot latency if available
    if reqA is not None and "latency_ms" in reqA.columns:
        ax2.plot(get_best_x(reqA), reqA["latency_ms"].rolling(10).median(),
                 label=f"{labelA} Lat(ms)", color="tab:red")
    if reqB is not None and "latency_ms" in reqB.columns:
        ax2.plot(get_best_x(reqB), reqB["latency_ms"].rolling(10).median(),
                 label=f"{labelB} Lat(ms)", color="tab:orange")

    ax1.set_xlabel("Frame / Time / Index")
    ax1.set_ylabel("CPU %")
    ax2.set_ylabel("Latency (ms)")
    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")

    plt.tight_layout()
    plt.savefig("compare_timeseries.png", dpi=150)
    print("[DONE] Saved compare_timeseries.png")


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 analyze_runs.py <pqc_folder> <secoc_folder>")
        sys.exit(1)

    pathA, pathB = sys.argv[1], sys.argv[2]
    labelA, labelB = os.path.basename(pathA.rstrip("/")), os.path.basename(pathB.rstrip("/"))

    sa, sysA, reqA = load_run(pathA)
    sb, sysB, reqB = load_run(pathB)

    df = pd.DataFrame([sa, sb], index=[labelA, labelB]).T
    print("\nComparison table:")
    print(df)
    df.to_csv("compare_summary.csv")
    print("[DONE] Saved compare_summary.csv")

    plot_bars(sa, sb, labelA, labelB)
    plot_timeseries(sysA, sysB, reqA, reqB, labelA, labelB)

if __name__ == "__main__":
    main()

