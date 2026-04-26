import socket
import numpy as np

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", 52001))

while True:
    data, _ = sock.recvfrom(4096)
    samples = np.frombuffer(data, dtype=np.uint8)  # or float32, etc.
    print(samples)

