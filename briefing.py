"""Flight briefing export: SimBrief-style PDF, ICAO flight-plan text and VATSIM prefile fields.

Pure Python, no third-party packages, so it runs unchanged on Android (Buildozer) and
Windows (PyInstaller). Simulator use only, not for real-world navigation.
"""
import math

VATSIM_PREFILE_URL = "https://my.vatsim.net/pilots/flightplan"

# ICAO type -> (wake category, equipment/transponder). Sim defaults, adjust per aircraft.
_WAKE = {"C172": "L", "BE58": "L", "DH8D": "M", "LJ45": "L", "CRJ9": "M", "A320": "M",
         "B738": "M", "A359": "H", "A35K": "H", "B789": "H", "B77W": "H", "A388": "J"}


def _hhmm(minutes):
    m = max(0, int(round(minutes)))
    return "%02d%02d" % (m // 60, m % 60)


def prefile_fields(plan, callsign="", rules="I", dep_time_utc="1200", remarks=""):
    """Individual fields as the VATSIM prefile form asks for them."""
    typ = plan.get("aircraft", "A320")
    jet = typ not in ("C172", "BE58", "DH8D")
    return {
        "callsign": (callsign or "").upper(), "rules": rules, "aircraft": typ,
        "wake": _WAKE.get(typ, "M"), "equipment": "SDE3FGHIRWY/LB1" if jet else "S/C",
        "departure": plan.get("origin", ""), "arrival": plan.get("destination", ""),
        "alternate": plan.get("alternate") or "", "dep_time_utc": dep_time_utc,
        "cruise_tas_kt": int(round(plan.get("tas_kt", 0))),
        "cruise_alt": "F%03d" % int(plan.get("cruise_fl", 0)),
        "route": plan.get("route") or "DCT", "eet": _hhmm(plan.get("ete_min", 0)),
        "endurance": _hhmm(plan.get("ete_min", 0) + 45 + 15), "remarks": remarks or "/V/ SIM FLIGHT",
    }


def icao_fpl(plan, callsign="", rules="I", dep_time_utc="1200", remarks=""):
    """ICAO-format flight plan text (items 7-19 simplified)."""
    f = prefile_fields(plan, callsign, rules, dep_time_utc, remarks)
    alt = (" " + f["alternate"]) if f["alternate"] else ""
    return ("(FPL-%s-%sS\n-%s/%s-%s\n-%s%s\n-N%04d%s %s\n-%s%s%s\n-%s)" % (
        f["callsign"] or "XXXX", f["rules"], f["aircraft"], f["wake"], f["equipment"],
        f["departure"], f["dep_time_utc"], f["cruise_tas_kt"], f["cruise_alt"], f["route"],
        f["arrival"], f["eet"], alt, "RMK/" + f["remarks"].strip("/ ")))


# ---------------------------------------------------------------- PDF writer
class MiniPDF:
    """Tiny multi-page PDF writer (built-in Helvetica/Courier, vector lines)."""
    W, H = 595, 842

    def __init__(self):
        self.pages = []
        self.new_page()

    def new_page(self):
        self.pages.append([])
        return self

    def _add(self, s):
        self.pages[-1].append(s)

    @staticmethod
    def _esc(t):
        t = str(t).encode("latin-1", "replace").decode("latin-1")
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def text(self, x, y, s, size=10, mono=False, bold=False):
        font = "F3" if mono else ("F2" if bold else "F1")
        self._add("BT /%s %.1f Tf %.1f %.1f Td (%s) Tj ET" % (font, size, x, self.H - y, self._esc(s)))

    def line(self, x1, y1, x2, y2, width=0.8, rgb=(0, 0, 0)):
        self._add("%.2f %.2f %.2f RG %.2f w %.1f %.1f m %.1f %.1f l S" % (
            rgb + (width, x1, self.H - y1, x2, self.H - y2)))

    def polyline(self, pts, width=1.0, rgb=(0, 0, 0)):
        for a, b in zip(pts, pts[1:]):
            self.line(a[0], a[1], b[0], b[1], width, rgb)

    def rect(self, x, y, w, h, rgb=(0.6, 0.6, 0.6)):
        self._add("%.2f %.2f %.2f RG 0.6 w %.1f %.1f %.1f %.1f re S" % (rgb + (x, self.H - y - h, w, h)))

    def to_bytes(self):
        objs = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
        kids = []
        for content in self.pages:
            data = "\n".join(content).encode("latin-1", "replace")
            objs.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
            cid = len(objs)
            objs.append(("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                         "/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> >>"
                         % (self.W, self.H, cid)).encode())
            kids.append("%d 0 R" % len(objs))
        objs[1] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join(kids), len(kids))).encode()
        out, offsets = bytearray(b"%PDF-1.4\n"), []
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        return bytes(out)

    def save(self, path):
        with open(path, "wb") as fh:
            fh.write(self.to_bytes())
        return path


def _route_map(pdf, points, x, y, w, h):
    pdf.rect(x, y, w, h)
    if len(points) < 2:
        return
    lats, lons = [p[0] for p in points], [p[1] for p in points]
    lat0, lat1, lon0, lon1 = min(lats), max(lats), min(lons), max(lons)
    k = max(math.cos(math.radians((lat0 + lat1) / 2)), 0.2)
    sx = (w - 20) / max((lon1 - lon0) * k, 0.01)
    sy = (h - 20) / max(lat1 - lat0, 0.01)
    s = min(sx, sy)
    ox = x + (w - (lon1 - lon0) * k * s) / 2
    oy = y + (h + (lat1 - lat0) * s) / 2
    pdf.polyline([(ox + (lo - lon0) * k * s, oy - (la - lat0) * s) for la, lo in points],
                 1.4, (0.1, 0.35, 0.8))


def _profile(pdf, profile, x, y, w, h):
    pdf.rect(x, y, w, h)
    if len(profile) < 2:
        return
    dmax = max(p[0] for p in profile) or 1
    amax = max(p[1] for p in profile) or 1
    pdf.polyline([(x + 6 + p[0] / dmax * (w - 12), y + h - 6 - p[1] / amax * (h - 16))
                  for p in profile], 1.4, (0.8, 0.3, 0.1))


def build_briefing_pdf(path, plan, route_points=None, profile=None, metar_origin="",
                       metar_dest="", callsign="", dep_time_utc="1200", notes=""):
    """Write a 1-2 page briefing PDF and return its path."""
    plan = dict(plan)
    pdf = MiniPDF()
    o, d = plan.get("origin", "----"), plan.get("destination", "----")
    pdf.text(40, 50, "FLIGHT BRIEFING  %s - %s" % (o, d), 18, bold=True)
    pdf.text(40, 68, "%s %s   Simulation use only, not for real-world navigation." % (
        plan.get("origin_name", ""), "-> " + plan.get("destination_name", "")), 8)
    pdf.line(40, 76, 555, 76)
    h, m = divmod(int(round(plan.get("ete_min", 0))), 60)
    rows = [
        ("Callsign", callsign or "-"), ("Aircraft", plan.get("aircraft_name") or plan.get("aircraft", "")),
        ("Distance", "%.0f NM" % plan.get("distance_nm", 0)), ("Cruise", "FL%03d  TAS %d kt" % (
            plan.get("cruise_fl", 0), plan.get("tas_kt", 0))),
        ("ETE", "%d:%02d" % (h, m)), ("TOC / TOD", "%.0f NM / %.0f NM" % (
            plan.get("toc_nm", 0), plan.get("tod_nm", 0))),
        ("Fuel trip", "%.0f kg" % plan.get("fuel_trip_kg", 0)),
        ("Fuel reserve", "%.0f kg" % plan.get("fuel_reserve_kg", 0)),
        ("Fuel contingency", "%.0f kg" % plan.get("fuel_contingency_kg", 0)),
        ("Fuel total", "%.0f kg" % plan.get("fuel_total_kg", 0)),
        ("Alternate", plan.get("alternate") or "-"),
        ("SID / STAR", "%s / %s" % (plan.get("sid", "-"), plan.get("star", "-"))),
        ("Runways", "%s / %s" % (plan.get("departure_runway", "-"), plan.get("arrival_runway", "-"))),
        ("Dep time (UTC)", dep_time_utc),
    ]
    y = 98
    for i, (k, v) in enumerate(rows):
        col = 40 if i % 2 == 0 else 300
        pdf.text(col, y, k, 9, bold=True)
        pdf.text(col + 90, y, v, 9)
        if i % 2:
            y += 15
    y += 20
    pdf.text(40, y, "ROUTE", 10, bold=True)
    route = plan.get("route", "DCT")
    for i in range(0, min(len(route), 360), 88):
        y += 13
        pdf.text(40, y, route[i:i + 88], 8, mono=True)
    y += 18
    _route_map(pdf, route_points or plan.get("points") or [], 40, y, 250, 170)
    _profile(pdf, profile or [], 305, y, 250, 170)
    pdf.text(40, y + 182, "Route map", 7)
    pdf.text(305, y + 182, "Vertical profile", 7)
    y += 205
    pdf.text(40, y, "ICAO FPL", 10, bold=True)
    for line in icao_fpl(plan, callsign, "I", dep_time_utc).split("\n"):
        y += 12
        pdf.text(40, y, line[:100], 8, mono=True)
    for title, raw in (("METAR " + o, metar_origin), ("METAR " + d, metar_dest)):
        if raw:
            y += 20
            pdf.text(40, y, title, 9, bold=True)
            for i in range(0, len(raw), 95):
                y += 11
                pdf.text(40, y, raw[i:i + 95], 7, mono=True)
    if notes:
        pdf.new_page()
        pdf.text(40, 50, "SCRATCHPAD / NOTES", 14, bold=True)
        y = 76
        for para in str(notes).splitlines()[:60]:
            for i in range(0, max(len(para), 1), 95):
                pdf.text(40, y, para[i:i + 95], 9, mono=True)
                y += 12
    return pdf.save(path)
