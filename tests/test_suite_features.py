"""Run with: python tests/test_suite_features.py (from the repository root)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge"))
import planner_core as pc
import briefing
from simbridge import xgps_packet, xatt_packet
from telemetry import Telemetry


def sample_plan():
    pts = [(40.6398, -73.7789), (51.47, -0.4543)]
    p = pc.plan_flight(pts, "B77W", 370)
    p.update(origin="KJFK", destination="EGLL", route="KJFK DCT EGLL", points=pts,
             aircraft_name="B777", alternate="EGKK")
    return p


def test_pdf():
    p = sample_plan()
    with tempfile.TemporaryDirectory() as d:
        out = briefing.build_briefing_pdf(os.path.join(d, "b.pdf"), p, p["points"], pc.vertical_profile(p),
                                          "KJFK 181951Z 00000KT", "EGLL 182020Z 24008KT", "UAE201", notes="note")
        data = open(out, "rb").read()
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert data.count(b"/Type /Page ") == 2 and b"KJFK" in data


def test_fpl_and_fields():
    p = sample_plan()
    f = briefing.prefile_fields(p, "uae201")
    assert f["callsign"] == "UAE201" and f["cruise_alt"] == "F370" and f["wake"] == "H"
    t = briefing.icao_fpl(p, "UAE201")
    assert t.startswith("(FPL-UAE201-IS") and "-KJFK1200" in t and t.endswith(")") and "EGLL" in t


def test_bridge_roundtrip():
    tel = Telemetry()
    tel.parse(xgps_packet("MSFS", 40.6398, -73.7789, 1000, 90, 120), "UDP 49002", "test")
    tel.parse(xatt_packet("MSFS", 91.5), "UDP 49002", "test")
    d = tel.snapshot()
    assert abs(d["lat"] - 40.6398) < 1e-4 and abs(d["lon"] + 73.7789) < 1e-4
    assert abs(d["alt"] - 1000) < 1 and abs(d["speed"] - 120) < 0.5 and abs(d["heading"] - 91.5) < 0.1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
