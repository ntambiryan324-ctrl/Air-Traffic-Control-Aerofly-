"""Run with: python tests/test_core.py (from the repository root)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import planner_core as pc
from atc_engine import ATCEngine, normalize, contains_token
from telemetry import Telemetry

def test_distance():
    d = pc.distance_nm(40.6398, -73.7789, 51.4700, -0.4543)  # JFK-LHR
    assert 2990 < d < 3040, d

def test_plan_long_and_short():
    ap = lambda c: pc.lookup_airport(c)
    a, b = ap("KJFK"), ap("EGLL")
    p = pc.plan_flight([(a["lat"], a["lon"]), (b["lat"], b["lon"])], "B77W", 370)
    assert p["cruise_fl"] == 370 and p["toc_nm"] < p["tod_nm"]
    assert 340 < p["ete_min"] < 420, p["ete_min"]
    assert p["fuel_total_kg"] > p["fuel_trip_kg"] > 0
    # short hop: cruise level must shrink so climb+descent fit
    s = pc.plan_flight([(0.0, 0.0), (0.0, 2.0)], "A320", 380)   # ~120 NM hop
    assert s["cruise_fl"] < 380 and s["toc_nm"] <= s["tod_nm"] + 1e-6, s
    prof = pc.vertical_profile(s)
    assert prof[0][1] == 0 and prof[-1][1] == 0

def test_plan_speed_override():
    points = [(40.6413, -73.7781), (51.4700, -0.4543)]
    nominal = pc.plan_flight(points, "A320", 360)
    faster = pc.plan_flight(points, "A320", 360, speed_override_kt=500)
    assert nominal["tas_kt"] == pc.AIRCRAFT["A320"][0]
    assert faster["tas_kt"] == 500
    assert faster["ete_min"] < nominal["ete_min"]
    ignored = pc.plan_flight(points, "A320", 360, speed_override_kt=9999)
    assert ignored["tas_kt"] == nominal["tas_kt"]

def test_aircraft_alias():
    assert pc.resolve_aircraft("Airbus A350-1000 XWB") == "A35K"
    assert pc.resolve_aircraft("zzz") == "A320"

def test_tcp_stream_request_and_framing():
    class FakeSocket:
        def __init__(self): self.sent = b""
        def sendall(self, data): self.sent += data

    fake = FakeSocket()
    Telemetry._request_stream(fake)
    assert fake.sent == b"GET / HTTP/1.1\r\n\r\n"

    t = Telemetry()
    chunk = (b"XGPSAerofly FS Global,32.4435,0.0424,1000,90,50 "
             b"XATTAerofly FS Global,91,0,0 ")
    remaining = t._consume_tcp_buffer(b"", chunk, "192.168.1.10")
    d = t.snapshot()
    assert remaining == b"", remaining
    assert d["packets"] == 2, d
    assert abs(d["lon"] - 32.4435) < 1e-5, d
    assert abs(d["lat"] - 0.0424) < 1e-5, d
    assert d["heading"] == 91, d

def test_metar():
    m = pc.decode_metar("METAR KJFK 011251Z 24008G15KT 10SM FEW050 20/12 A3010")
    assert (m["wind_dir"], m["wind_kt"], m["gust_kt"]) == (240, 8, 15)
    assert m["vis"] == "10 SM" and m["temp_c"] == 20 and m["dew_c"] == 12
    assert m["altim_inhg"] == 30.10 and m["time_z"] == "1251Z"
    q = pc.decode_metar("EGLL 011250Z 27012KT 9999 M02/M05 Q1021")
    assert q["qnh_hpa"] == 1021 and q["temp_c"] == -2 and q["vis"] == "10 KM"

def test_taf_fetch():
    from unittest.mock import patch

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b"TAF HUEN 181100Z 1812/1912 12008KT 9999 SCT020"

    with patch("planner_core.urllib.request.urlopen", return_value=FakeResponse()) as opened:
        raw = pc.fetch_taf("HUEN")
    assert raw.startswith("TAF HUEN"), raw
    request = opened.call_args.args[0]
    assert "taf?ids=HUEN&format=raw" in request.full_url, request.full_url


def test_gpx():
    g = pc.export_gpx("T", [("KJFK", 40.6, -73.7), ("EGLL", 51.4, -0.4)])
    assert g.count("<rtept") == 2 and "KJFK" in g

def test_normalize():
    assert contains_token(normalize("runway two eight left"), "28L")
    assert contains_token(normalize("squawk four five two one"), "4521")
    assert contains_token(normalize("climb and maintain five thousand"), "5000")
    assert contains_token(normalize("expect flight level three six zero"), "FL360")
    assert not contains_token(normalize("squawk 14521"), "4521")

def test_atc_flow():
    e = ATCEngine(); e.set_callsign("UGA101"); e.set_plan("HUEN", "HKJK", 360)
    e.set_metar("HUEN", "HUEN 011251Z 12008KT 9999 24/18 Q1019")
    e.set_runways("HUEN", ["17", "35"]); e.set_runways("HKJK", ["06", "24"])
    r = e.handle("request IFR clearance")
    assert "cleared to HKJK" in r and "Squawk" in r, r
    sq = e.squawk
    assert all(c in "01234567" for c in sq)
    assert "negative" in e.handle("roger")                       # incomplete readback
    ok = e.handle("climb and maintain five thousand squawk " + " ".join(sq))
    assert "readback correct" in ok, ok
    r = e.handle("request taxi")
    assert "runway 17" in r and "QNH 1019" in r, r              # 120deg wind favours 17
    assert "readback correct" in e.handle("taxi runway one seven hold short")
    assert "cleared for takeoff" in e.handle("ready for departure")
    e.handle("inbound HKJK")
    far = {"lat": 0.04, "lon": 32.44}
    assert "continue approach" in e.handle("request landing", far)
    near = {"lat": -1.30, "lon": 36.90}
    assert "cleared to land" in e.handle("request landing", near)

def test_misc():
    e = ATCEngine()
    assert "Fetch weather" in e.atis()
    assert "unable direct" in e.handle("request direct ZZZZZ")
    assert "proceed direct HKJK" in e.handle("direct HKJK")
    assert "mayday" in e.handle("MAYDAY mayday")
    assert "not understood" in e.handle("blah blah")

class FakeLLM:
    def respond(self, message, aircraft=None, context=None): return "SIM ATC: via llm"
def test_llm_fallback():
    e = ATCEngine(llm=FakeLLM())
    assert e.handle("what is the meaning of life") == "SIM ATC: via llm"

def test_events_and_monitor_and_logbook():
    import tempfile, os
    from extras import FlightMonitor, Logbook, CHECKLISTS
    e = ATCEngine(); e.set_callsign("UGA101"); e.set_plan("HUEN", "HKJK", 360)
    assert "radar contact" in e.event("takeoff") and e.phase == "AIRBORNE"
    assert "descend at pilot" in e.event("top_of_descent")
    assert "welcome to HKJK" in e.event("landing") and e.phase == "PARKED"
    assert e.event("nonsense") == ""
    lb = Logbook(os.path.join(tempfile.mkdtemp(), "lb.json"))
    assert "No flights" in lb.summary()
    m = FlightMonitor(lb); m.set_plan("HUEN", "HKJK", (-1.3192, 36.9278), 120.0)
    def snap(lat, lon, gs, alt): return {"connected": True, "lat": lat, "lon": lon, "speed_kt": gs, "alt_ft": alt}
    assert m.update(snap(0.04, 32.44, 0, 3800), now=0) == []                 # parked, learns ground level
    assert m.update(snap(0.04, 32.44, 80, 3850), now=10) == []               # rolling, not airborne yet
    assert m.update(snap(0.05, 32.50, 150, 4200), now=20) == ["takeoff"]
    assert m.update(snap(-0.5, 34.5, 450, 36000), now=2000) == []            # cruise far from destination
    assert m.update(snap(-1.0, 35.8, 450, 36000), now=2600) == ["top_of_descent"]   # ~ 70 NM out <= 120
    assert m.update(snap(-1.28, 36.85, 250, 6000), now=3000) == ["approach"]
    assert m.update(snap(-1.3192, 36.9278, 20, 5400), now=3300) == ["landing"]
    rows = lb.entries(); assert len(rows) == 1 and rows[0]["origin"] == "HUEN" and rows[0]["nm"] > 100, rows
    assert "1 flights" in lb.summary()
    assert m.update(snap(-1.3192, 36.9278, 20, 5400), now=3400) == []        # no double logging
    assert len(CHECKLISTS) == 9

def test_voice_safe_off_android():
    from voice import Voice
    v = Voice()
    assert v.available is False and v.speak("hello") is False and v.listen(lambda t: None) is False
    v.shutdown()

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
    print("ALL PASSED")
