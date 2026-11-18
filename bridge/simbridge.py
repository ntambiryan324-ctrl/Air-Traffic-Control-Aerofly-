"""SimBridge: relays simulator position to the Aerofly ATC app as XGPS/XATT over UDP 49002.

  python simbridge.py msfs   --target 192.168.1.50      (needs: pip install SimConnect, Windows)
  python simbridge.py geofs  --target 192.168.1.50      (browser bookmarklet, printed on start)
  python simbridge.py xplane --target 192.168.1.50      (announces this PC so X-Plane sends data)

--target is the device running the app (default 127.0.0.1 for the Windows build on the same PC).
Aerofly FS needs no bridge: it connects directly (UDP 49002 / TCP 58585).
Simulation use only.
"""
import argparse
import json
import math
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 49002
FT_PER_M = 3.280839895
KT_PER_MS = 1.943844492


def xgps_packet(name, lat, lon, alt_ft, track_deg, gs_kt):
    """ForeFlight-style XGPS record: lon, lat, altitude m, track deg, ground speed m/s."""
    return ("XGPS%s,%.5f,%.5f,%.1f,%.1f,%.1f" % (
        name, lon, lat, alt_ft / FT_PER_M, track_deg % 360, gs_kt / KT_PER_MS)).encode()


def xatt_packet(name, heading, pitch=0.0, roll=0.0):
    return ("XATT%s,%.1f,%.1f,%.1f" % (name, heading % 360, pitch, roll)).encode()


class Sender:
    def __init__(self, target, port=PORT):
        self.addr = (target, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def send(self, name, lat, lon, alt_ft, hdg, gs_kt, pitch=0.0, roll=0.0):
        self.sock.sendto(xgps_packet(name, lat, lon, alt_ft, hdg, gs_kt), self.addr)
        self.sock.sendto(xatt_packet(name, hdg, pitch, roll), self.addr)


# ---------------------------------------------------------------- MSFS
def run_msfs(sender, hz=4):
    from SimConnect import SimConnect, AircraftRequests  # pip install SimConnect
    sm = SimConnect()
    aq = AircraftRequests(sm, _time=200)
    print("MSFS connected via SimConnect")
    while True:
        lat, lon = aq.get("PLANE_LATITUDE"), aq.get("PLANE_LONGITUDE")
        if lat is None or lon is None:
            time.sleep(1)
            continue
        hdg = aq.get("PLANE_HEADING_DEGREES_TRUE") or 0.0
        if abs(hdg) <= 6.3:  # some library versions return radians
            hdg = math.degrees(hdg)
        sender.send("MSFS", lat, lon, aq.get("PLANE_ALTITUDE") or 0.0, hdg,
                    aq.get("GROUND_VELOCITY") or 0.0)
        time.sleep(1.0 / hz)


# ---------------------------------------------------------------- GeoFS
GEOFS_BOOKMARKLET = (
    "javascript:(function(){if(window.__sb)return;window.__sb=setInterval(function(){try{"
    "var a=geofs.aircraft.instance,l=a.llaLocation,v=geofs.animation.values;"
    "new Image().src='http://127.0.0.1:8765/geofs?lat='+l[0]+'&lon='+l[1]+'&alt_m='+l[2]"
    "+'&hdg='+v.heading360+'&kts='+(v.kias||0)}catch(e){}},500)})();")


def run_geofs(sender, port=8765):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            try:
                sender.send("GeoFS", float(q["lat"][0]), float(q["lon"][0]),
                            float(q["alt_m"][0]) * FT_PER_M, float(q["hdg"][0]), float(q["kts"][0]))
            except (KeyError, ValueError):
                pass
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_):
            pass
    print("GeoFS: open GeoFS, then run this bookmarklet on the page:\n" + GEOFS_BOOKMARKLET)
    HTTPServer(("127.0.0.1", port), H).serve_forever()


# ---------------------------------------------------------------- X-Plane
def run_xplane():
    """X-Plane streams XGPS/XATT to apps that announce themselves like ForeFlight does."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    beacon = json.dumps({"App": "ForeFlight", "GDL90": {"port": 4000}}).encode()
    print("Announcing to X-Plane on UDP 63093; data arrives on UDP %d." % PORT)
    while True:
        s.sendto(beacon, ("255.255.255.255", 63093))
        time.sleep(5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("sim", choices=["msfs", "geofs", "xplane"])
    ap.add_argument("--target", default="127.0.0.1")
    ap.add_argument("--hz", type=float, default=4)
    a = ap.parse_args()
    sender = Sender(a.target)
    if a.sim == "msfs":
        run_msfs(sender, a.hz)
    elif a.sim == "geofs":
        run_geofs(sender)
    else:
        threading.Thread(target=run_xplane, daemon=True).start()
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
