#!/usr/bin/env python3

import socket
import time
import struct
import oqs
import traceback
import hashlib
import os
import threading
import queue
import psutil
import random

HOST = "127.0.0.1"
PORT = 65433
MAX_CONN_QUEUE = 100 #Number of pending connections before refusal
RECV_TIMEOUT = 6.0 #in seconds
WORKLOAD = int(os.environ.get("PQC_WORKLOAD", "50000")) #computational load factor

# --- adaptive control ---
CPU_LIMIT = 85.0     # % threshold to start rejecting new clients - if CPU >85% new #messages are dropped
DROP_PROB_BASE = 0.1 # baseline random drop - even when CPU is low there is a 10% drop rate
MSG_QUEUE = queue.Queue(maxsize=500)

# --- replay cache --- to detect and reject replayed messages - prevents replay attack
SEEN_HASHES = set()
MAX_HASHES = 2048

''' Reads exactly length bytes from a tcp connection'''
def recv_exact(conn, length):
    data = b""
    while len(data) < length:
        chunk = conn.recv(length - len(data))
        if not chunk:
            raise ConnectionError("connection closed early")
        data += chunk
    return data


'''Splits the incoming messafe into structured oayload and freshness'''
def handle_message(message, signature, public_key, addr):
    """Actual verification + heavy math here."""
    structured_payload = message[:-8]
    freshness = message[-8:]

    try:
        ts = struct.unpack(">Q", freshness)[0]
    except Exception:
        print(f"[{time.strftime('%H:%M:%S')}] !!! Bad freshness from {addr}")
        return

    # reject stale messages early - if message's timestamp differs by more than 30 seconds #discard it 
    now = int(time.time())
    if abs(now - ts) > 30:
        return

    # replay protection - Prevents replay attacks by hashing message + signature.If already seen → drop. Maintains a rolling cache (up to 2048 entries).
    msg_hash = hashlib.sha256(message + signature).hexdigest()
    if msg_hash in SEEN_HASHES:
        return
    SEEN_HASHES.add(msg_hash)
    if len(SEEN_HASHES) > MAX_HASHES:
        SEEN_HASHES.pop()

    start = time.time()

    # verify authenticity PQC signature using dilithium2. If sgnature is invalid - drop
    try:
        with oqs.Signature("Dilithium2") as verifier:
            if not verifier.verify(message, signature, public_key):
                print(f"[{time.strftime('%H:%M:%S')}] [FAILURE] PQC signature failed from {addr}")
                return
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Verify error {addr}: {e}")
        return

    # simulate heavy cryptographic load for bench marking
    acc = b""
    for _ in range(WORKLOAD // 500):
        data = os.urandom(64)
        acc = hashlib.sha3_512(data + acc).digest()

    duration = (time.time() - start) * 1000
    print(f"[{time.strftime('%H:%M:%S')}] [DONE] PQC verified from {addr} ({duration:.2f} ms)")

''' Each worker continuously fetches messages from queue and processes them using handle_message.'''
def worker():
    while True:
        try:
            msg = MSG_QUEUE.get()
            if msg is None:
                break
            handle_message(*msg)
        except Exception as e:
            print("Worker error:", e)
        finally:
            MSG_QUEUE.task_done()


def handle_connection(conn, addr):
    try:
    	'''For each client connection, set timeout, ready 2 byte message length and message body'''
        conn.settimeout(RECV_TIMEOUT)
        raw = recv_exact(conn, 2)
        msg_len = int.from_bytes(raw, "big")
        message = recv_exact(conn, msg_len)
	'''Next 2 bytes → signature length, then actual signature.'''
        raw = recv_exact(conn, 2)
        sig_len = int.from_bytes(raw, "big")
        signature = recv_exact(conn, sig_len)
	'''Read public key'''
        raw = recv_exact(conn, 2)
        pk_len = int.from_bytes(raw, "big")
        public_key = recv_exact(conn, pk_len)
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Incomplete recv from {addr}: {e}")
        return
    finally:
        conn.close()

    # Adaptive overload control - Drops message if CPU is above 85%, or Random drop probability (10%) triggers.
    cpu = psutil.cpu_percent(interval=0.0)
    if cpu > CPU_LIMIT or random.random() < DROP_PROB_BASE:
        print(f"[{time.strftime('%H:%M:%S')}] [DONE] Drop (CPU={cpu:.1f}%) from {addr}")
        return

    try:
        MSG_QUEUE.put_nowait((message, signature, public_key, addr)) #Queueing message for background workers
    except queue.Full:
        print(f"[{time.strftime('%H:%M:%S')}] [DONE] Queue full, dropping from {addr}")


def main():
    print(f"Starting PQC receiver on {HOST}:{PORT} — adaptive threaded mode")
    # spawn worker threads - starts 4 background threads for parallell processing
    for _ in range(4): 
        threading.Thread(target=worker, daemon=True).start()
    # Create server socket 
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(MAX_CONN_QUEUE)
    #Accepts each client and spawns a new thread to handle it asynchronously.
        try:
            while True:
                conn, addr = s.accept()
                threading.Thread(target=handle_connection, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            print("\nPQC receiver shutting down.")
        finally:
            for _ in range(4):
                MSG_QUEUE.put(None)
            MSG_QUEUE.join()


if __name__ == "__main__":
    main()

