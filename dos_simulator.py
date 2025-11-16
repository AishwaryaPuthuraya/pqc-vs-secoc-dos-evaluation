#!/usr/bin/env python3
"""
Run example:
python3 dos_simulator.py --port 65432 --mode churn --concurrency 200 --total 2000 --outdir results/pqc_run
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime
from statistics import mean
from typing import Optional

import numpy as np
import psutil
import pandas as pd


# ------------------------
# Helpers
# ------------------------

#returns current UTC time in ISO8601 format with trailing Z. Used for human-readable timestamps.
def iso_now():
    return datetime.utcnow().isoformat() + "Z"

def safe_mkdir(d):
    os.makedirs(d, exist_ok=True)
    
'''recursively converts bytes into base64-encoded strings so JSON dumps won't fail. Also recurses for dict/list.'''
def clean_for_json(obj):
    """Convert bytes -> base64 strings for safe JSON dump"""
    import base64
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")
    elif isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(x) for x in obj]
    else:
        return obj


# --------------------------------------------------------------------------
# System Sampler - collects system and optionally process-specific metrics.
# --------------------------------------------------------------------------
class SystemSampler:
    def __init__(self, sample_interval=0.5, server_pid: Optional[int] = None, target_port: Optional[int] = None):
        self.sample_interval = sample_interval #Controls sampling frequency
        self.server_pid = server_pid    #Points process to a sample
        self.target_port = target_port   #used to count connections to a given TCP port
        self.rows = []
        self._running = False

    async def run(self):  #Asynchronous and enters sampling loop
        self._running = True
        proc = None
        if self.server_pid:   #If provided with server_pid, attempt to get a psutil.Process object for per-process stats; ignore failures.
            try:
                proc = psutil.Process(self.server_pid)
            except Exception:
                proc = None

        while self._running:
            ts = time.time()
            cpu = psutil.cpu_percent(interval=None) #instantaneous CPU percent since last call
            vm = psutil.virtual_memory()
            swap = psutil.swap_memory()
            tcp_count = 0 #Count TCP connections to target_port
            states = {} #dictionary of TCP connections states count
            '''Iterates all TCP connections on the machine and counts those where local or remote port matches target_port. Collects counts per TCP state (e.g., ESTABLISHED, TIME_WAIT).'''
            try:
                for c in psutil.net_connections(kind='tcp'):
                    if self.target_port:
                        if (c.laddr and c.laddr.port == self.target_port) or (c.raddr and c.raddr.port == self.target_port):
                            tcp_count += 1
                            states[c.status] = states.get(c.status, 0) + 1
            except Exception:
                pass
	    '''If a psutil.Process is available, sample its CPU percent and memory info; attempt to read number of file descriptors'''
            proc_cpu = proc_mem = fds = None
            if proc:
                try:
                    proc_cpu = proc.cpu_percent(interval=None)
                    meminfo = proc.memory_info()
                    proc_mem = {"rss": meminfo.rss, "vms": meminfo.vms}
                    try:
                        fds = proc.num_fds()
                    except Exception:
                        fds = None
                except Exception:
                    pass

            row = {
                "ts": iso_now(),
                "epoch": ts,
                "cpu_percent": cpu,
                "mem_total": vm.total,
                "mem_available": vm.available,
                "mem_used": vm.used,
                "mem_percent": vm.percent,
                "swap_percent": swap.percent,
                "tcp_conn_count_to_target": tcp_count,
                "tcp_states_json": json.dumps(states),
                "proc_cpu_percent": proc_cpu,
                "proc_mem_json": json.dumps(proc_mem) if proc_mem else None,
                "proc_num_fds": fds,
            }
            self.rows.append(row)
            await asyncio.sleep(self.sample_interval)

    def stop(self):
        self._running = False


# -------------------------------------------------------
# Load Generator - Builds different modes of load
#Churn - many short lived connections
#steady - repeated batches of concurrency
#Long - hold persistent connections and send repeatedly
# ---------------------------------------------------------
class LoadGen:
    def __init__(self, host, port, concurrency, total, mode="churn", payload=b"ping", timeout=5.0):
        self.host = host
        self.port = port
        self.concurrency = concurrency
        self.total = total
        self.mode = mode
        self.payload = payload
        self.timeout = timeout
        self.results = []
        self._sem = asyncio.Semaphore(concurrency)
        self._stop = False
   '''Single request coroutine. uses self._sem to limit concurrent tasks. opens an async TCP connection with async.open_connection. Sends payload +and waits for a line in response.'''
    async def _one(self, idx):
        async with self._sem:
            start = time.perf_counter()
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=self.timeout)
                writer.write(self.payload + b"\n")
                await writer.drain()
                try:
                    data = await asyncio.wait_for(reader.readline(), timeout=self.timeout) # Measures latency
                except asyncio.TimeoutError:
                    data = b""
                end = time.perf_counter()
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
                # On success, appends a result entry with success=True, latency_ms, response length, etc.
                self.results.append({
                    "idx": idx, "ts": iso_now(), "success": True,
                    "latency_ms": (end - start) * 1000.0, "resp_len": len(data), "err": None
                })
            except Exception as e:
                end = time.perf_counter()
                self.results.append({
                    "idx": idx, "ts": iso_now(), "success": False,
                    "latency_ms": (end - start) * 1000.0, "resp_len": 0, "err": str(e)
                })
   '''schedules total concurrent tasks (bounded by semaphore) and awaits them. This results in many short-lived connections.'''
    async def run_churn(self):
        tasks = []
        for i in range(self.total):
            if self._stop:
                break
            tasks.append(asyncio.create_task(self._one(i)))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    '''repeatedly launches concurrency tasks per iteration, waits for them to finish, then sleeps a short interval. Produces steady periodic bursts.'''
    async def run_steady(self, iterations=100):
        idx = 0
        for _ in range(iterations):
            if self._stop:
                break
            tasks = [asyncio.create_task(self._one(idx + j)) for j in range(self.concurrency)]
            idx += self.concurrency
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.sleep(0.01)

    '''opens concurrency persistent connections up front, then repeatedly sends on each of those connections at interval until hold_time expires.'''
    async def run_long(self, hold_time=30.0, interval=0.2):
        readers = []
        writers = []
        for i in range(self.concurrency):
            try:
                r, w = await asyncio.open_connection(self.host, self.port)
                readers.append(r); writers.append(w)
            except Exception as e:
                self.results.append({"idx": i, "ts": iso_now(), "success": False, "latency_ms": 0, "resp_len": 0, "err": str(e)})
        start = time.perf_counter()
        iter_no = 0
        while (time.perf_counter() - start) < hold_time and not self._stop:
            tasks = []
            for i, (r, w) in enumerate(zip(readers, writers)):
                tasks.append(self._send_persistent(i, r, w, iter_no))
            await asyncio.gather(*tasks, return_exceptions=True)
            iter_no += 1
            await asyncio.sleep(interval)
        for w in writers:
            try: w.close()
            except: pass
	
   '''Helper for persistent connections: send payload, optionally read response line, record metrics per iteration.'''	
    async def _send_persistent(self, idx, reader, writer, iteration):
        start = time.perf_counter()
        try:
            writer.write(self.payload + b"\n")
            await writer.drain()
            try:
                data = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
            except asyncio.TimeoutError:
                data = b""
            end = time.perf_counter()
            self.results.append({
                "idx": idx, "iteration": iteration, "ts": iso_now(),
                "success": True, "latency_ms": (end - start)*1000.0, "resp_len": len(data), "err": None
            })
        except Exception as e:
            end = time.perf_counter()
            self.results.append({
                "idx": idx, "iteration": iteration, "ts": iso_now(),
                "success": False, "latency_ms": (end - start)*1000.0, "resp_len": 0, "err": str(e)
            })

    async def run(self):
        if self.mode == "churn":
            await self.run_churn()
        elif self.mode == "steady":
            await self.run_steady()
        elif self.mode == "long":
            await self.run_long()
        else:
            raise ValueError("Unknown mode")

    def stop(self):
        self._stop = True


# ------------------------
# Reporting helpers
# ------------------------
def summarize(results):
    lat = [r["latency_ms"] for r in results if r["success"] and r.get("latency_ms") is not None]
    total = len(results)
    succ = sum(1 for r in results if r["success"])
    fail = total - succ
    return {
        "total": total,
        "successes": succ,
        "failures": fail,
        "success_rate_pct": (succ / total * 100.0) if total > 0 else None,
        "lat_p50_ms": float(np.percentile(lat, 50)) if lat else None,
        "lat_p90_ms": float(np.percentile(lat, 90)) if lat else None,
        "lat_p99_ms": float(np.percentile(lat, 99)) if lat else None,
        "lat_mean_ms": float(mean(lat)) if lat else None
    }

def write_csv_requests(path, results):
    keys = ["idx","ts","success","latency_ms","resp_len","err","iteration"]
    with open(path,"w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in results:
            row = {k: r.get(k) for k in keys}
            w.writerow(row)

def write_csv_system(path, rows):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path,"w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ------------------------
# Run one scenario
# ------------------------
async def run_scenario(args):
    if args.host not in ("127.0.0.1","localhost") and not args.allow_remote:
        print("Target restricted to localhost by default. Use --allow-remote to override.")
        return 1

    sampler = SystemSampler(sample_interval=args.sample_interval, server_pid=args.server_pid, target_port=args.port)
    load = LoadGen(args.host, args.port, args.concurrency, args.total, mode=args.mode, payload=args.payload.encode(), timeout=args.timeout)

    sampler_task = asyncio.create_task(sampler.run())
    t0 = time.time()
    try:
        await load.run()
    finally:
        load.stop()
        sampler.stop()
        await asyncio.sleep(0.05)

    t1 = time.time()
    safe_mkdir(args.outdir)
    req_csv = os.path.join(args.outdir, "requests.csv")
    sys_csv = os.path.join(args.outdir, "system.csv")
    summary_json = os.path.join(args.outdir, "summary.json")

    write_csv_requests(req_csv, load.results)
    write_csv_system(sys_csv, sampler.rows)
    s = summarize(load.results)
    s.update({
        "start_time": datetime.utcfromtimestamp(t0).isoformat() + "Z",
        "end_time": datetime.utcfromtimestamp(t1).isoformat() + "Z",
        "duration_s": t1 - t0,
        "sample_count": len(sampler.rows),
        "args": vars(args)
    })
    s = clean_for_json(s)
    with open(summary_json, "w") as f:
        json.dump(s, f, indent=2)
    print(f"\n[DONE] Test complete. Results written to {args.outdir}")
    print(json.dumps(s, indent=2))
    return 0


# ------------------------
# Compare two runs
# ------------------------
def compare_dirs(dir_a, dir_b, out_csv=None):
    sa = {}; sb = {}
    for f in ("summary.json",):
        pa = os.path.join(dir_a, f)
        pb = os.path.join(dir_b, f)
        if os.path.exists(pa):
            sa = json.load(open(pa))
        if os.path.exists(pb):
            sb = json.load(open(pb))
    rows = []
    metrics = ["total","successes","failures","success_rate_pct","lat_p50_ms","lat_p90_ms","lat_p99_ms","lat_mean_ms","duration_s","sample_count"]
    for m in metrics:
        rows.append({"metric": m, "run_a": sa.get(m), "run_b": sb.get(m)})
    df = pd.DataFrame(rows)
    print("\n=== Comparison ===")
    print(df.to_string(index=False))
    if out_csv:
        df.to_csv(out_csv, index=False)
        print("Saved comparison CSV to", out_csv)
    return df


# ------------------------
# CLI
# ------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Local load simulator + compare tool (lab-only).")
    p.add_argument("--host", default="127.0.0.1", help="Target host (default localhost)")
    p.add_argument("--port", type=int, default=9000, help="Target port")
    p.add_argument("--mode", choices=["churn","steady","long"], default="churn", help="Load mode")
    p.add_argument("--concurrency", type=int, default=200, help="Concurrency")
    p.add_argument("--total", type=int, default=2000, help="Total requests (for churn mode)")
    p.add_argument("--payload", default="ping", help="Payload to send")
    p.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout (seconds)")
    p.add_argument("--sample-interval", type=float, default=0.5, help="System sampling interval (s)")
    p.add_argument("--server-pid", type=int, default=None, help="Optional server PID to sample")
    p.add_argument("--outdir", default="dos_results", help="Output directory")
    p.add_argument("--allow-remote", action="store_true", help="Allow non-localhost targets")
    p.add_argument("--compare", nargs=2, help="Compare two result directories")
    p.add_argument("--report", help="If comparing, path to save CSV report")
    return p.parse_args()


# ------------------------
# Main
# ------------------------
def main():
    args = parse_args()
    if args.compare:
        a, b = args.compare
        compare_dirs(a, b, out_csv=args.report)
        sys.exit(0)
    loop = asyncio.get_event_loop()
    try:
        res = loop.run_until_complete(run_scenario(args))
        sys.exit(res if res is not None else 0)
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(1)


if __name__ == "__main__":
    main()

