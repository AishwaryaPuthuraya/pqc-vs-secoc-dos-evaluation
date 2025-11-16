#!/usr/bin/env python3
"""
secoc_sender_tcp.py

SECOC sender over TCP using the same structured payload as PQC:
  structured_payload (48 bytes, format ">H I h h B H ff 27x")
  + freshness (8 bytes, >Q)
  -> message
  + truncated HMAC tag (8 bytes)
Sends framed as:
  2B msg_len | message | 2B tag_len | tag
Auto-generates payload values.
"""
import socket
import struct
import time
import random
import hmac
import hashlib

HOST = "127.0.0.1"
PORT = 65432
SECRET_KEY = b"my_shared_secret"
PAYLOAD_FMT = ">H I h h B H ff 27x"  # 48 bytes structured
TAG_LEN = 8

def make_structured_payload():
    speed = random.randint(0, 250)
    rpm = random.randint(600, 8000)
    temperature = random.randint(-40, 125)
    steering_angle = random.randint(-540, 540)
    fuel_level = random.randint(0, 100)
    brake_pressure = random.randint(0, 200)
    gps_lat = random.uniform(-90.0, 90.0)
    gps_lon = random.uniform(-180.0, 180.0)
    payload = struct.pack(PAYLOAD_FMT,
                          speed, rpm, temperature, steering_angle,
                          fuel_level, brake_pressure, gps_lat, gps_lon)
    fields = {
        "speed": speed, "rpm": rpm, "temp": temperature,
        "steer": steering_angle, "fuel": fuel_level, "brake": brake_pressure,
        "lat": gps_lat, "lon": gps_lon
    }
    return payload, fields

def main():
    payload, fields = make_structured_payload()
    freshness = struct.pack(">Q", int(time.time()))
    message = payload + freshness  # 56 bytes
    full_tag = hmac.new(SECRET_KEY, message, hashlib.sha256).digest()
    tag = full_tag[:TAG_LEN]

    try:
        with socket.create_connection((HOST, PORT), timeout=5) as s:
            s.sendall(len(message).to_bytes(2, "big") + message)
            s.sendall(len(tag).to_bytes(2, "big") + tag)
        print("Sent SECOC-TCP message")
        print(f" lengths -> msg:{len(message)} tag:{len(tag)}")
        print(" fields ->", fields)
        print(" tag (tx):", tag.hex())
    except Exception as e:
        print("Send failed:", e)

if __name__ == "__main__":
    main()

