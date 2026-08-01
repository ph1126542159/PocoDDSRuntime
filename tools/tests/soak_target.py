import time


payload = bytearray(1024 * 1024)
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    payload[0] = (payload[0] + 1) % 255
    time.sleep(0.05)
