import argparse
import os
import subprocess
import sys
import time


parser = argparse.ArgumentParser()
parser.add_argument("--child", action="store_true")
parser.add_argument("--spawn-child", action="store_true")
parser.add_argument("--spawn-leaking-child", action="store_true")
parser.add_argument("--leak-handles", action="store_true")
args = parser.parse_args()

child = None
if args.spawn_child or args.spawn_leaking_child:
    child_args = [sys.executable, __file__, "--child"]
    if args.spawn_leaking_child:
        child_args.append("--leak-handles")
    child = subprocess.Popen(child_args)


payload = bytearray((16 if args.child else 1) * 1024 * 1024)
deadline = time.monotonic() + 10
leaked_handles = []
try:
    while time.monotonic() < deadline:
        payload[0] = (payload[0] + 1) % 255
        if args.leak_handles:
            leaked_handles.append(open(os.devnull, "rb"))
        time.sleep(0.05)
finally:
    for handle in leaked_handles:
        handle.close()
    if child is not None:
        child.terminate()
        child.wait(timeout=5)
