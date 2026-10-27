"""Record what Aerofly FS Global actually sends, so the protocol can be studied from real data.

Run on any device that can reach the simulator (a PC, or Termux on Android):
    python protocol_probe.py 192.168.1.50            # TCP 58585 for 20 s
    python protocol_probe.py 192.168.1.50 --udp 40   # also listen on UDP 49002/40092 for 40 s
Writes probe_log.txt (readable text plus hex). Only talks to your own simulator.
"""
import argparse, socket, threading, time

LOG = "probe_log.txt"
lock = threading.Lock()

def log(tag, data):
    with lock, open(LOG, "ab") as f:
        f.write(("[%s %.2f] " % (tag, time.time() - T0)).encode() + data + b"\nHEX " + data.hex().encode() + b"\n---\n")

def tcp(host, port, secs):
    s = socket.create_connection((host, port), timeout=5)
    s.settimeout(1)
    req = b"GET / HTTP/1.1\r\n\r\n"
    s.sendall(req); log("TCP SENT", req)
    end = time.time() + secs
    while time.time() < end:
        try:
            chunk = s.recv(8192)
            if not chunk:
                log("TCP", b"<closed by peer>"); break
            log("TCP RECV", chunk)
        except socket.timeout:
            pass
    s.close()

def udp(port, secs):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port)); s.settimeout(1)
    end = time.time() + secs
    while time.time() < end:
        try:
            raw, addr = s.recvfrom(65535); log("UDP %d from %s" % (port, addr[0]), raw)
        except socket.timeout:
            pass
    s.close()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("host"); ap.add_argument("--port", type=int, default=58585)
    ap.add_argument("--secs", type=int, default=20); ap.add_argument("--udp", type=int, default=0)
    a = ap.parse_args(); T0 = time.time(); open(LOG, "wb").close()
    threads = []
    if a.udp:
        for p in (49002, 40092):
            t = threading.Thread(target=udp, args=(p, a.udp), daemon=True); t.start(); threads.append(t)
    try:
        tcp(a.host, a.port, a.secs)
    except OSError as e:
        log("TCP ERROR", str(e).encode())
    for t in threads: t.join()
    print("Done. See", LOG)
