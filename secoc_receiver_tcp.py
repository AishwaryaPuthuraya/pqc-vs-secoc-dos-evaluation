#!/usr/bin/env python3
"""
secoc_receiver_tcp.py

SECOC receiver over TCP with same framing as PQC.
Reads:
  2B msg_len, message (48B struct + 8B freshness)
  2B tag_len, tag
Verifies HMAC (SHA256 truncated to 8B), unpacks payload and prints fields.
Robust to partial recv; logs and continues serving.
"""
import socket
import struct
import time
import hmac
import hashlib
import traceback
import psutil
import random
import collections
import os


HOST = "127.0.0.1"
PORT = 65432
SECRET_KEY = b"my_shared_secret"
PAYLOAD_FMT = ">H I h h B H ff 27x"
RECV_TIMEOUT = 6.0
MAX_CONN_QUEUE = 50
# --- Replay & overload realism ---
REPLAY_CACHE_SIZE = 1024      # Number of recent message hashes to remember
REPLAY_CACHE = collections.deque(maxlen=REPLAY_CACHE_SIZE)
REPLAY_SET = set()

FRESHNESS_MAX_AGE = 5         # Drop messages older than 5s
FRESHNESS_FUTURE_TOL = 5      # Drop messages from >5s in future

CPU_SCALE = 120.0             # Larger = less aggressive dropping
MAX_DROP_PROB = 0.85          # Cap on drop probability

# Deterministic randomness for reproducibility
RANDOM_SEED = int(os.environ.get("EXPERIMENT_SEED", "0"))
if RANDOM_SEED:
    random.seed(RANDOM_SEED)


def recv_exact(conn, length):
    data = b""
    while len(data) < length:
        try:
            chunk = conn.recv(length - len(data))
        except socket.timeout:
            raise ConnectionError("recv timeout")
        if not chunk:
            raise ConnectionError("connection closed early / incomplete")
        data += chunk
    return data

def record_replay(msg_hash):
    """Record message hash in replay cache and return True if new."""
    if msg_hash in REPLAY_SET:
        return False
    if len(REPLAY_SET) >= REPLAY_CACHE_SIZE:
        old = REPLAY_CACHE.popleft()
        REPLAY_SET.discard(old)
    REPLAY_CACHE.append(msg_hash)
    REPLAY_SET.add(msg_hash)
    return True


def compute_drop_prob():
    """Compute drop probability based on CPU load."""
    try:
        cpu = psutil.cpu_percent(interval=0.0)
    except Exception:
        cpu = 0.0
    prob = min(MAX_DROP_PROB, cpu / CPU_SCALE)
    return prob, cpu


def handle_connection(conn, addr):
    conn.settimeout(RECV_TIMEOUT)
    try:
        # Read framed message and tag
        raw = recv_exact(conn, 2)
        msg_len = int.from_bytes(raw, "big")
        message = recv_exact(conn, msg_len)

        raw = recv_exact(conn, 2)
        tag_len = int.from_bytes(raw, "big")
        tag = recv_exact(conn, tag_len)
    except ConnectionError as e:
        print(f"[{time.strftime('%H:%M:%S')}] Connection aborted by {addr}: {e}")
        return
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Error reading from {addr}: {e}")
        traceback.print_exc()
        return

    # Basic sanity check
    if len(message) < 56:
        print(f"[{time.strftime('%H:%M:%S')}] Message too short ({len(message)} bytes) from {addr}")
        return

    # Split message: payload + freshness timestamp
    structured_payload = message[:-8]
    freshness = message[-8:]
    try:
        ts = struct.unpack(">Q", freshness)[0]
    except Exception:
        print(f"[{time.strftime('%H:%M:%S')}] Failed to unpack freshness from {addr}")
        return

    # --- Freshness check ---
    now = int(time.time())
    age = now - ts
    if age > FRESHNESS_MAX_AGE:
        print(f"[{time.strftime('%H:%M:%S')}] !!!! Dropping stale msg from {addr} (age={age}s)")
        return
    if ts - now > FRESHNESS_FUTURE_TOL:
        print(f"[{time.strftime('%H:%M:%S')}] !!!! Dropping future msg from {addr} (delta={ts - now}s)")
        return

    # --- Verify HMAC ---
    try:
        calc_full = hmac.new(SECRET_KEY, structured_payload + freshness, hashlib.sha256).digest()
        calc_tag = calc_full[:tag_len]
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] HMAC compute error: {e}")
        return

    if calc_tag != tag:
        print(f"[{time.strftime('%H:%M:%S')}] [FAILURE] HMAC mismatch from {addr} (recv {tag.hex()} vs calc {calc_tag.hex()})")
        return

    # --- Replay detection ---
    msg_hash = hashlib.sha256(structured_payload + freshness + tag).hexdigest()[:32]
    if msg_hash in REPLAY_SET:
        print(f"[{time.strftime('%H:%M:%S')}] !!!! Replay detected from {addr}, dropping.")
        return
    record_replay(msg_hash)

    # --- Simulate overload-based drops ---
    drop_prob, cpu = compute_drop_prob()
    if random.random() < drop_prob:
        print(f"[{time.strftime('%H:%M:%S')}] !!!! Overload drop (CPU={cpu:.1f}%, p={drop_prob:.2f}) from {addr}")
        return

    # --- Unpack structured payload ---
    try:
        fields = struct.unpack(PAYLOAD_FMT, structured_payload)
        speed, rpm, temp, steer, fuel, brake, lat, lon = fields[:8]
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Unpack error from {addr}: {e}")
        return

    print(f"[{time.strftime('%H:%M:%S')}] [DONE] SECOC valid msg from {addr} — speed={speed} rpm={rpm} temp={temp}C fuel={fuel}% gps=({lat:.5f},{lon:.5f}) freshness_delta={age}s")


def main():
    print(f"SECOC (TCP) receiver listening on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(MAX_CONN_QUEUE)
        try:
            while True:
                conn, addr = s.accept()
                with conn:
                    print(f"[{time.strftime('%H:%M:%S')}] Connection from {addr}")
                    handle_connection(conn, addr)
        except KeyboardInterrupt:
            print("\nSECOC receiver shutting down (user interrupt).")
        except Exception as e:
            print("Fatal receiver error:", e)
            traceback.print_exc()

if __name__ == "__main__":
    main()

