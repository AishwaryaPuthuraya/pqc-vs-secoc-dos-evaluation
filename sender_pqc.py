import socket
import time
import struct
import random
import oqs

HOST = '127.0.0.1'
PORT = 65433

# ---------------- Automated Payload (48 bytes structured) ----------------
# Fields similar to CAN example:
# speed(2), rpm(4), temp(2), steer(2), fuel(1), brake(2), lat(4f), lon(4f) + padding(27 bytes) to reach 48 bytes
payload_fmt = ">H I h h B H ff 27x"

speed          = random.randint(0, 250)
rpm            = random.randint(600, 8000)
temperature    = random.randint(-40, 125)
steering_angle = random.randint(-540, 540)
fuel_level     = random.randint(0, 100)
brake_pressure = random.randint(0, 200)
gps_lat        = random.uniform(-90.0, 90.0)
gps_lon        = random.uniform(-180.0, 180.0)

structured_payload = struct.pack(
    payload_fmt,
    speed, rpm, temperature, steering_angle, fuel_level, brake_pressure, gps_lat, gps_lon
)
assert len(structured_payload) == 48

# ---------------- Freshness + Message Construction ----------------
freshness = struct.pack(">Q", int(time.time()))  # 8-byte timestamp
message = structured_payload + freshness         # total = 56 bytes

# ---------------- Dilithium2 Signing ----------------
with oqs.Signature('Dilithium2') as signer:
    public_key = signer.generate_keypair()
    secret_key = signer.export_secret_key()

    signature = signer.sign(message)  #Signed with private key

    # ---------------- Send over TCP ----------------
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))

        # send message
        s.sendall(len(message).to_bytes(2, 'big') + message)
        s.sendall(len(signature).to_bytes(2, 'big') + signature)
        s.sendall(len(public_key).to_bytes(2, 'big') + public_key)

        print("Sent signed structured message")
        print(f" lengths -> msg:{len(message)} sig:{len(signature)} pub:{len(public_key)}")
        print(f" values  -> speed={speed} rpm={rpm} temp={temperature}C steer={steering_angle}° "
              f"fuel={fuel_level}% brake={brake_pressure}bar gps=({gps_lat:.5f},{gps_lon:.5f})")

