import json
import math
import os
import re
import urllib.request
import urllib.parse
import socket
import threading
import time
import urllib.error
import urllib.request

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Line, Triangle, Rectangle
from aviation_features import AirspaceStore, SRTMElevation, CabinCrewEngine, OSMTileCache, AirportData, region_voice_locale


APP_VERSION = "1.4.0"
TELEMETRY_PORTS = (49002, 58585)
GROQ_MODEL = "openai/gpt-oss-20b"


def load_env_file(filepath=".env"):
    # Desktop convenience only. .env is intentionally not packaged into Android.
    if not os.path.exists(filepath):
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ[key.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass


load_env_file()


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalise_telemetry(obj):
    """Accept common JSON and key=value telemetry naming conventions."""
    if not isinstance(obj, dict):
        return None

    # Flatten one common nested vehicle/state object.
    flat = dict(obj)
    for parent in ("telemetry", "state", "aircraft", "flight"):
        child = obj.get(parent)
        if isinstance(child, dict):
            flat.update(child)

    aliases = {
        "altitude": ("altitude", "alt", "altitude_ft", "alt_ft", "indicated_altitude"),
        "speed": ("speed", "airspeed", "ias", "ias_kt", "speed_kt", "airspeed_kt"),
        "heading": ("heading", "hdg", "heading_deg", "track"),
        "lat": ("lat", "latitude"),
        "lon": ("lon", "lng", "longitude"),
        "callsign": ("callsign", "call_sign", "flight_id", "aircraft_id"),
        "vertical_speed": ("vertical_speed", "vs", "vs_fpm", "vertical_speed_fpm"),
        "on_ground": ("on_ground", "onground", "grounded"),
    }

    result = {}
    for target, keys in aliases.items():
        for key in keys:
            if key in flat and flat[key] not in (None, ""):
                result[target] = flat[key]
                break

    if not result:
        return None

    result["altitude"] = safe_float(result.get("altitude"), 0)
    result["speed"] = safe_float(result.get("speed"), 0)
    result["heading"] = safe_float(result.get("heading"), 0) % 360
    result["lat"] = safe_float(result.get("lat"), 0)
    result["lon"] = safe_float(result.get("lon"), 0)
    result["vertical_speed"] = safe_float(result.get("vertical_speed"), 0)
    result["on_ground"] = bool(result.get("on_ground", False))
    result["callsign"] = str(result.get("callsign", "")).strip()
    return result


def parse_telemetry_packet(data):
    """Parse JSON or simple key=value / key:value UDP/TCP packets.

    This deliberately does not claim that either port is an Aerofly-native
    protocol. It accepts structured telemetry if an external bridge sends it.
    """
    try:
        text = data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None

    if not text:
        return None

    if text.startswith("XGPS"):
        try:
            p = text[4:].split(",")
            sim = p[0].strip()
            return {"callsign": sim, "sim_name": sim, "lon": float(p[1]), "lat": float(p[2]), "altitude": float(p[3]) * 3.280839895, "heading": float(p[4]) % 360, "speed": float(p[5]) * 1.94384449}
        except (ValueError, IndexError):
            pass
    if text.startswith("XATT"):
        try:
            p = text[4:].split(",")
            return {"sim_name": p[0].strip(), "heading": float(p[1]) % 360, "pitch": float(p[2]), "roll": float(p[3])}
        except (ValueError, IndexError):
            pass

    try:
        parsed = json.loads(text)
        result = normalise_telemetry(parsed)
        if result:
            return result
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    pairs = {}
    for key, value in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*([^\s,;|]+)", text):
        pairs[key.lower()] = value

    if pairs:
        return normalise_telemetry(pairs)

    return None


class TelemetryReceiver:
    def __init__(self, ports=TELEMETRY_PORTS):
        self.ports = tuple(ports)
        self.running = False
        self.lock = threading.Lock()
        self.latest_data = {
            "connected": False,
            "port": None,
            "protocol": None,
            "altitude": 0.0,
            "speed": 0.0,
            "heading": 0.0,
            "lat": 0.0,
            "lon": 0.0,
            "vertical_speed": 0.0,
            "on_ground": False,
            "callsign": "",
            "last_packet": 0.0,
            "packet_count": 0,
            "raw_packets": 0,
        }
        self.sockets = []

    def start(self):
        if self.running:
            return
        self.running = True
        for port in self.ports:
            threading.Thread(target=self._udp_listener, args=(port,), daemon=True).start()
            threading.Thread(target=self._tcp_listener, args=(port,), daemon=True).start()

    def _record_packet(self, data, port, protocol):
        now = time.time()
        parsed = parse_telemetry_packet(data)
        with self.lock:
            self.latest_data["raw_packets"] += 1
            self.latest_data["last_packet"] = now
            self.latest_data["port"] = port
            self.latest_data["protocol"] = protocol
            self.latest_data["connected"] = True
            if parsed:
                self.latest_data.update(parsed)
                self.latest_data["packet_count"] += 1

    def _udp_listener(self, port):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", port))
            sock.settimeout(1.0)
            self.sockets.append(sock)
            while self.running:
                try:
                    data, _ = sock.recvfrom(8192)
                    if data:
                        self._record_packet(data, port, "UDP")
                except socket.timeout:
                    continue
                except OSError:
                    break
        except OSError as exc:
            print(f"UDP {port} unavailable: {exc}")
        finally:
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def _tcp_listener(self, port):
        server = None
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("", port))
            server.listen(3)
            server.settimeout(1.0)
            self.sockets.append(server)
            while self.running:
                try:
                    conn, _ = server.accept()
                    conn.settimeout(1.0)
                    threading.Thread(
                        target=self._tcp_client,
                        args=(conn, port),
                        daemon=True,
                    ).start()
                except socket.timeout:
                    continue
                except OSError:
                    break
        except OSError as exc:
            print(f"TCP {port} unavailable: {exc}")
        finally:
            if server:
                try:
                    server.close()
                except OSError:
                    pass

    def _tcp_client(self, conn, port):
        try:
            buffer = b""
            while self.running:
                chunk = conn.recv(8192)
                if not chunk:
                    break
                buffer += chunk
                # Handle newline-delimited JSON/key=value packets.
                while b"\n" in buffer:
                    packet, buffer = buffer.split(b"\n", 1)
                    if packet.strip():
                        self._record_packet(packet, port, "TCP")
                # Also accept a complete JSON object without newline.
                stripped = buffer.strip()
                if stripped.startswith(b"{") and stripped.endswith(b"}"):
                    self._record_packet(stripped, port, "TCP")
                    buffer = b""
        except (OSError, socket.timeout):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def snapshot(self):
        with self.lock:
            data = dict(self.latest_data)
        if data["last_packet"] and time.time() - data["last_packet"] > 4:
            data["connected"] = False
        return data

    def stop(self):
        self.running = False
        for sock in list(self.sockets):
            try:
                sock.close()
            except OSError:
                pass
        self.sockets.clear()






class AirportDatabase:
    """Small offline airport/airspace database; can be expanded without changing telemetry."""
    AIRPORTS = {
        "EBBR": {"name":"Brussels Airport","lat":50.9010,"lon":4.4844,"elev":184},
        "UGEE": {"name":"Entebbe International","lat":0.0424,"lon":32.4435,"elev":3782},
        "HCAA": {"name":"Cairo International","lat":30.1219,"lon":31.4056,"elev":382},
        "EHAM": {"name":"Amsterdam Schiphol","lat":52.3086,"lon":4.7639,"elev":-11},
    }

    @classmethod
    def nearest(cls, lat, lon):
        best=None
        best_d=10**99
        for ident,a in cls.AIRPORTS.items():
            d=((lat-a["lat"])*110540)**2+((lon-a["lon"])*111320)**2
            if d<best_d:
                best_d=d; best=(ident,a)
        return best

class TerrainWarningEngine:
    """Conservative terrain sanity checks using airport elevation when available."""
    def check(self, data, nearest):
        if not nearest: return []
        ident, airport = nearest
        alt = float(data.get("altitude",0) or 0)
        elev = airport["elev"]
        if alt < elev + 500 and not data.get("on_ground", False):
            return ["LOW ALTITUDE NEAR %s" % ident]
        return []

class FlightReplay:
    def __init__(self, state):
        self.state = state
        self.index = 0
        self.playing = False

    def reset(self):
        self.index = 0

    def step(self):
        log = self.state.log
        if not log: return None
        item = log[min(self.index, len(log)-1)]
        self.index += 1
        if self.index >= len(log): self.playing = False
        return item

class RouteTracker:
    def __init__(self):
        self.route = []
    def add(self, lat, lon, ident=None):
        self.route.append({"ident": ident, "lat": lat, "lon": lon})
        self.route = self.route[-200:]
    def clear(self):
        self.route = []

class TrafficEngine:
    """Local synthetic traffic for situational awareness; no external tracking required."""
    def __init__(self):
        self.traffic = []
    def update(self, own):
        return self.traffic
    def conflict(self, own, traffic):
        alerts=[]
        for ac in traffic:
            if abs(ac.get("altitude",0)-own.get("altitude",0)) < 1000:
                alerts.append("%s traffic: altitude proximity." % ac.get("callsign","TRAFFIC"))
        return alerts

class ATCController:
    """Deterministic controller logic; AI is an optional response layer, not required for safety."""
    def __init__(self):
        self.callsign = "UNKNOWN"
        self.frequency = "121.500"
        self.controller = "GROUND"
        self.last_instruction = ""
        self.last_emit = 0.0
        self.history = []

    def identify(self, data):
        cs = str(data.get("callsign") or data.get("sim_name") or "").strip()
        if cs: self.callsign = cs
        return self.callsign

    def controller_for_phase(self, phase):
        return {
            "PARKED": "GROUND",
            "GROUND": "GROUND",
            "TAKEOFF": "TOWER",
            "DEPARTURE": "DEPARTURE",
            "CENTER": "CENTER",
            "APPROACH": "APPROACH",
            "LANDING": "TOWER",
            "NO TELEMETRY": "GROUND",
        }.get(phase, "GROUND")

    def generate(self, data):
        self.callsign = self.identify(data)
        new_controller = self.controller_for_phase(data.get("phase"))
        if new_controller != self.controller:
            self.controller = new_controller
            self.frequency = {"GROUND":"121.900","TOWER":"118.100","DEPARTURE":"120.900","CENTER":"132.500","APPROACH":"119.100"}.get(new_controller,"121.500")
            msg = "%s, contact %s on %s." % (self.callsign, new_controller.lower(), self.frequency)
        elif data.get("phase") == "TAKEOFF":
            msg = "%s, runway heading, cleared for takeoff." % self.callsign
        elif data.get("vertical_speed", 0) < -2500:
            msg = "%s, check altitude and vertical speed." % self.callsign
        else:
            msg = ""
        if msg:
            if msg == self.last_instruction and time.time() - self.last_emit < 15:
                return ""
            self.last_instruction = msg
            self.last_emit = time.time()
            self.history.append({"time": time.time(), "controller": self.controller, "frequency": self.frequency, "message": msg})
            self.history = self.history[-100:]
        return msg

class FlightStateEngine:
    """Derives stable simulator state from telemetry without requiring cloud services."""
    def __init__(self):
        self.prev = None
        self.phase = "PARKED"
        self.last_phase_change = 0
        self.squawk = "2000"
        self.events = []
        self.route = []
        self.log = []

    def update(self, data):
        now = time.time()
        d = dict(data)
        prev = self.prev
        vs = 0.0
        if prev and now > prev["_t"]:
            vs = (d.get("altitude", 0) - prev.get("altitude", 0)) * 60 / (now - prev["_t"])
        d["vertical_speed"] = vs
        speed = float(d.get("speed", 0) or 0)
        alt = float(d.get("altitude", 0) or 0)
        on_ground = bool(d.get("on_ground", False))
        old = self.phase
        if not d.get("connected", False):
            self.phase = "NO TELEMETRY"
        elif on_ground and speed < 35:
            self.phase = "GROUND"
        elif on_ground and speed >= 35:
            self.phase = "TAKEOFF"
        elif prev and not prev.get("on_ground", False) and on_ground and speed < 80:
            self.phase = "LANDING"
        elif not on_ground and vs > 300 and alt < 12000:
            self.phase = "DEPARTURE"
        elif not on_ground and vs < -300 and alt < 12000:
            self.phase = "APPROACH"
        elif not on_ground:
            self.phase = "CENTER"
        if self.phase != old:
            self.events.append({"time": now, "event": old + " -> " + self.phase})
        if d.get("lat") or d.get("lon"):
            p = (d.get("lat"), d.get("lon"))
            if not self.route or p != self.route[-1]:
                self.route.append(p)
                self.route = self.route[-1000:]
        self.log.append({
            "time": now, "lat": d.get("lat"), "lon": d.get("lon"),
            "altitude": alt, "speed": speed, "heading": d.get("heading", 0),
            "vertical_speed": vs, "phase": self.phase
        })
        self.log = self.log[-10000:]
        d["phase"] = self.phase
        d["squawk"] = self.squawk
        d["_t"] = now
        self.prev = d
        return d

    def snapshot(self):
        return {
            "phase": self.phase, "squawk": self.squawk,
            "events": self.events[-50:], "route": self.route[-1000:],
            "log": self.log[-10000:]
        }

class AeroflyTCPConnector:
    def __init__(self, receiver):
        self.receiver = receiver
        self.running = False
        self.ip = "127.0.0.1"

    def start(self, ip="127.0.0.1"):
        self.ip = ip.strip() or "127.0.0.1"
        if self.running: return
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def reconnect(self, ip):
        self.ip = ip.strip() or "127.0.0.1"
        if not self.running: self.start(self.ip)

    def _loop(self):
        while self.running:
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((self.ip, 58585))
                sock.sendall(b"GET / HTTP/1.1\\r\\nHost: aerofly\\r\\n\\r\\n")
                sock.settimeout(2)
                buf = b""
                while self.running:
                    try: chunk = sock.recv(16384)
                    except socket.timeout: continue
                    if not chunk: break
                    buf += chunk
                    while b"\\n" in buf:
                        line, buf = buf.split(b"\\n", 1)
                        if line.strip(): self.receiver._record_packet(line.strip(), 58585, "TCP")
                    txt = buf.decode("utf-8", errors="ignore")
                    hits = re.findall(r"(?:XGPS|XATT)[^\\r\\n]+", txt)
                    for line in hits: self.receiver._record_packet(line.encode(), 58585, "TCP")
                    if hits: buf = b""
            except Exception as exc:
                print("Aerofly TCP:", exc)
                with self.receiver.lock: self.receiver.latest_data["connected"] = False
            finally:
                if sock:
                    try: sock.close()
                    except OSError: pass
                time.sleep(2)

    def stop(self):
        self.running = False

def build_atc_prompt(user_text, telemetry):
    telemetry_text = json.dumps(
        {
            "connected": telemetry["connected"],
            "source": f'{telemetry["protocol"] or "none"}:{telemetry["port"] or "-"}',
            "callsign": telemetry["callsign"],
            "altitude_ft": round(telemetry["altitude"], 1),
            "airspeed_kt": round(telemetry["speed"], 1),
            "heading_deg": round(telemetry["heading"], 1),
            "latitude": round(telemetry["lat"], 6),
            "longitude": round(telemetry["lon"], 6),
            "vertical_speed_fpm": round(telemetry["vertical_speed"], 1),
            "on_ground": telemetry["on_ground"],
        }
    )
    return (
        "Pilot transmission: "
        + user_text
        + "\nCurrent simulator telemetry: "
        + telemetry_text
        + "\nRespond as a concise simulated ATC controller. "
        "Use standard aviation phraseology where practical. "
        "Do not invent runway, frequency, clearance, traffic, weather, or navigation "
        "data that is not supplied. If information is missing, ask for it. "
        "This is a flight-simulation aid, not real-world ATC."
    )


def call_groq_atc(prompt, api_key):
    if not api_key:
        return None, "No Groq API key configured."

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a realistic flight-simulation ATC controller. "
                    "Be concise, operational, and never pretend to have real-world "
                    "radar or airport data."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 180,
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"].strip(), None
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="ignore")[:300]
        except Exception:
            pass
        return None, f"Groq HTTP {exc.code}: {detail or exc.reason}"
    except Exception as exc:
        return None, f"Groq error: {exc}"


def offline_atc_response(text, telemetry):
    lower = text.lower()
    callsign = telemetry["callsign"] or "aircraft"
    if "taxi" in lower:
        return f"{callsign}, taxi request received. State your departure runway and current position."
    if "takeoff" in lower or "departure" in lower:
        return f"{callsign}, departure request received. State your runway and departure procedure."
    if "landing" in lower or "approach" in lower:
        return f"{callsign}, approach request received. State your runway or approach and current altitude."
    if "frequency" in lower:
        return f"{callsign}, frequency request received. State the airport or controlling facility."
    return f"{callsign}, transmission received. Simulated ATC is in offline mode; provide airport, position, altitude, and request."



def speak_atc(text, locale="en-GB"):
    try:
        from jnius import autoclass
        Activity = autoclass("org.kivy.android.PythonActivity")
        TTS = autoclass("android.speech.tts.TextToSpeech")
        Locale = autoclass("java.util.Locale")
        tts = TTS(Activity.mActivity, None)
        requested = Locale.forLanguageTag(locale)
        if tts.isLanguageAvailable(requested) >= TTS.LANG_AVAILABLE:
            tts.setLanguage(requested)
        else:
            tts.setLanguage(Locale.US)
        tts.setSpeechRate(0.94)
        tts.speak(str(text), TTS.QUEUE_FLUSH, None, "atc")
    except Exception as exc:
        print("TTS unavailable:", exc)


def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/1.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def weather_snapshot(icao):
    icao = (icao or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", icao):
        raise ValueError("ICAO must be four characters")
    metar = fetch_json("https://aviationweather.gov/api/data/metar?ids=%s&format=json" % urllib.parse.quote(icao))
    taf = fetch_json("https://aviationweather.gov/api/data/taf?ids=%s&format=json" % urllib.parse.quote(icao))
    return {"icao": icao, "metar": metar, "taf": taf}


class AudioEngine:
    def __init__(self):
        self.enabled = True
        self.radio = True
        self.cabin = True

    def toggle(self):
        self.enabled = not self.enabled

    def radio_effect_text(self, message):
        if not self.enabled or not self.radio:
            return str(message)
        return "KRRR... " + str(message) + " ...KSH"


class MovingMapScreen(BoxLayout):
    def __init__(self, receiver, tile_cache=None, **kwargs):
        super().__init__(orientation="vertical", padding=6, spacing=4, **kwargs)
        self.receiver = receiver
        self.tile_cache = tile_cache
        self.trail = []
        self.last_tile_key = None
        self.add_widget(Label(text="LIVE MOVING MAP / RADAR", size_hint_y=None, height=32))
        self.status = Label(text="Waiting for Aerofly telemetry...", size_hint_y=None, height=28)
        self.add_widget(self.status)
        self.map_box = BoxLayout()
        self.add_widget(self.map_box)
        with self.map_box.canvas:
            Color(1, 1, 1, 1)
            self.base_map = Rectangle(pos=self.map_box.pos, size=self.map_box.size)
            Color(0.06, 0.07, 0.09, 0.75)
            self.grid = [Line(points=[0,0,0,0], width=1) for _ in range(13)]
            Color(0.95, 0.72, 0.08, 1)
            self.plane = Triangle(points=[0,0,0,0,0,0])
            Color(0.15, 0.75, 1, 1)
            self.track = Line(points=[], width=2)
        self.map_box.bind(size=lambda *_: self.redraw())
        self.map_box.bind(pos=lambda *_: self.redraw())

    def _tile_loaded(self, path, key):
        try:
            self.base_map.texture = CoreImage(path).texture
            self.last_tile_key = key
        except Exception as exc:
            print("Map tile error:", exc)

    def update(self, data):
        if data["lat"] or data["lon"]:
            p = (data["lat"], data["lon"])
            if not self.trail or p != self.trail[-1]:
                self.trail.append(p)
                self.trail = self.trail[-400:]
        if data["connected"]:
            self.status.text = "CONNECTED  %.5f, %.5f | %.0f ft | %.0f kt | %03.0f° | © OpenStreetMap contributors" % (data["lat"], data["lon"], data["altitude"], data["speed"], data["heading"])
            if self.tile_cache:
                z = 9
                x, y = self.tile_cache.tile_xy(data["lat"], data["lon"], z)
                key = f"{z}_{x}_{y}"
                if key != self.last_tile_key:
                    self.tile_cache.request(data["lat"], data["lon"], z, self._tile_loaded)
        else:
            self.status.text = "Waiting for Aerofly — enable Send flight data to FSWidgets Apps"
        self.redraw()

    def redraw(self):
        w, h = self.map_box.size
        cx, cy = self.map_box.x + w/2, self.map_box.y + h/2
        self.base_map.pos = (cx - min(w,h)/2, cy - min(w,h)/2)
        self.base_map.size = (min(w,h), min(w,h))
        step = max(35, min(w,h)/7)
        for i, line in enumerate(self.grid):
            x = cx + (i-6)*step
            line.points = [x, self.map_box.y, x, self.map_box.y+h]
        data = self.receiver.snapshot()
        pts=[]
        scale=6000.0
        for lat, lon in self.trail:
            dx=(lon-data["lon"])*111320*math.cos(math.radians(data["lat"]))
            dy=(lat-data["lat"])*110540
            pts += [cx+dx/scale, cy+dy/scale]
        self.track.points=pts
        hdg=math.radians(data["heading"])
        fx,fy=cx+math.sin(hdg)*24,cy+math.cos(hdg)*24
        lx,ly=cx+math.sin(hdg+2.4)*9,cy+math.cos(hdg+2.4)*9
        rx,ry=cx+math.sin(hdg-2.4)*9,cy+math.cos(hdg-2.4)*9
        self.plane.points=[fx,fy,lx,ly,rx,ry]


class MyFlightScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=12, spacing=8, **kwargs)
        self.status_label = Label(text="Telemetry: scanning UDP/TCP 49002 + 58585", size_hint_y=None, height=36)
        self.add_widget(self.status_label)

        grid = GridLayout(cols=2, spacing=8)
        self.values = {}
        for label, key, default in (
            ("Source", "source", "None"),
            ("Calls­ign", "callsign", "—"),
            ("Altitude (ft)", "altitude", "0"),
            ("Airspeed (kt)", "speed", "0"),
            ("Heading", "heading", "000"),
            ("Vertical speed", "vertical_speed", "0"),
            ("Latitude", "lat", "0.000000"),
            ("Longitude", "lon", "0.000000"),
            ("Packets", "packet_count", "0"),
        ):
            grid.add_widget(Label(text=label, font_size="15sp"))
            value = Label(text=default, font_size="15sp")
            self.values[key] = value
            grid.add_widget(value)
        self.add_widget(grid)

    def update(self, data):
        connected = data["connected"]
        source = f'{data["protocol"]}:{data["port"]}' if connected else "No telemetry"
        self.status_label.text = (
            f"Telemetry CONNECTED — {source}"
            if connected
            else "Telemetry scanning UDP/TCP 49002 + 58585"
        )
        self.values["source"].text = source
        self.values["callsign"].text = data["callsign"] or "—"
        self.values["altitude"].text = f'{data["altitude"]:,.0f}'
        self.values["speed"].text = f'{data["speed"]:.0f}'
        self.values["heading"].text = f'{data["heading"]:03.0f}'
        self.values["vertical_speed"].text = f'{data["vertical_speed"]:.0f}'
        self.values["lat"].text = f'{data["lat"]:.6f}'
        self.values["lon"].text = f'{data["lon"]:.6f}'
        self.values["packet_count"].text = str(data["packet_count"])


class CommsScreen(BoxLayout):
    def __init__(self, telemetry_receiver, cabin_callback=None, copilot=None, **kwargs):
        super().__init__(orientation="vertical", padding=12, spacing=8, **kwargs)
        self.telemetry_receiver = telemetry_receiver
        self.cabin_callback = cabin_callback
        self.copilot = copilot

        self.add_widget(Label(text="ATC Communications", size_hint_y=None, height=32, font_size="18sp"))

        key_row = BoxLayout(size_hint_y=None, height=48, spacing=6)
        key_row.add_widget(Label(text="Groq key:", size_hint_x=0.25))
        self.api_key = TextInput(
            hint_text="Paste your Groq API key (stored only in this running app)",
            password=True,
            multiline=False,
        )
        key_row.add_widget(self.api_key)
        self.add_widget(key_row)

        quick = BoxLayout(size_hint_y=None, height=44, spacing=6)
        for caption, phrase in (
            ("Taxi", "Request taxi clearance"),
            ("Departure", "Request departure clearance"),
            ("Approach", "Request approach clearance"),
            ("Cabin", "Please report cabin status"),
        ):
            btn = Button(text=caption)
            btn.bind(on_press=lambda _, p=phrase: self.set_phrase(p))
            quick.add_widget(btn)
        self.add_widget(quick)

        self.atc_log = TextInput(readonly=True, multiline=True, font_size="14sp")
        self.add_widget(self.atc_log)

        input_box = BoxLayout(size_hint_y=None, height=54, spacing=6)
        self.pilot_input = TextInput(
            hint_text="Type pilot transmission...",
            multiline=False,
        )
        mic_btn = Button(text="MIC / STT", size_hint_x=0.24)
        mic_btn.bind(on_press=self.start_stt)
        send_btn = Button(text="Transmit", size_hint_x=0.25)
        send_btn.bind(on_press=self.send_transmission)
        input_box.add_widget(self.pilot_input)
        input_box.add_widget(mic_btn)
        input_box.add_widget(send_btn)
        self.add_widget(input_box)
        self.tts_enabled = True
        tts_btn = Button(text="ATC TTS: ON", size_hint_y=None, height=42)
        tts_btn.bind(on_press=lambda *_: self.toggle_tts(tts_btn))
        self.add_widget(tts_btn)
        copilot_btn = Button(text="COPILOT AFK COMMS: OFF", size_hint_y=None, height=42)
        copilot_btn.bind(on_press=lambda *_: self.toggle_copilot(copilot_btn))
        self.add_widget(copilot_btn)

    def toggle_tts(self, button):
        self.tts_enabled = not self.tts_enabled
        button.text = "ATC TTS: ON" if self.tts_enabled else "ATC TTS: OFF"

    def toggle_copilot(self, button):
        if self.copilot:
            self.copilot.set_afk(not self.copilot.afk_mode)
            button.text = "COPILOT AFK COMMS: ON" if self.copilot.afk_mode else "COPILOT AFK COMMS: OFF"

    def append_conversation(self, speaker, message):
        self.atc_log.text += "%s: %s\n\n" % (speaker, message)

    def start_stt(self, _):
        try:
            from android import activity
            from jnius import autoclass, cast
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            RecognizerIntent = autoclass("android.speech.RecognizerIntent")
            Activity = autoclass("android.app.Activity")
            request_code = 48321
            def result_callback(code, result_code, intent):
                if code != request_code: return
                try: activity.unbind(on_activity_result=result_callback)
                except Exception: pass
                if result_code == Activity.RESULT_OK and intent:
                    results = intent.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                    if results and results.size() > 0: self.pilot_input.text = str(results.get(0))
            activity.bind(on_activity_result=result_callback)
            current = cast("android.app.Activity", PythonActivity.mActivity)
            intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak pilot transmission")
            current.startActivityForResult(intent, request_code)
        except Exception as exc:
            self.atc_log.text += "STT unavailable: " + str(exc) + "\n\n"
    def set_phrase(self, phrase):
        self.pilot_input.text = phrase
        self.pilot_input.focus = True

    def send_transmission(self, _):
        text = self.pilot_input.text.strip()
        if not text:
            return

        self.atc_log.text += f"PILOT: {text}\n[Processing...]\n\n"
        self.pilot_input.text = ""
        if self.cabin_callback and any(word in text.lower() for word in ("cabin", "flight attendant", "crew", "service")):
            self.atc_log.text = self.atc_log.text.replace("[Processing...]\n\n", "", 1)
            self.cabin_callback(text)
            return
        telemetry = self.telemetry_receiver.snapshot()
        api_key = self.api_key.text.strip() or os.getenv("GROQ_API_KEY", "")
        threading.Thread(
            target=self._process_atc,
            args=(text, telemetry, api_key),
            daemon=True,
        ).start()

    def _process_atc(self, text, telemetry, api_key):
        response, error = call_groq_atc(build_atc_prompt(text, telemetry), api_key)
        if not response:
            response = offline_atc_response(text, telemetry)
            if error:
                response += f"\n[AI unavailable: {error}]"
        Clock.schedule_once(lambda _dt: self._append_response(response))

    def _append_response(self, response):
        marker = "[Processing...]\n\n"
        if marker in self.atc_log.text:
            self.atc_log.text = self.atc_log.text.replace(marker, "", 1)
        self.atc_log.text += f"ATC: {response}\n\n"
        if getattr(self, "tts_enabled", True):
            threading.Thread(target=speak_atc, args=(response,), daemon=True).start()
        if self.copilot and self.copilot.afk_mode:
            self.copilot.handle_atc(response, self.telemetry_receiver.snapshot())


class Copilot:
    """Stateful local first officer for simulated ATC, monitoring and AFK comms."""
    def __init__(self, app):
        self.app = app
        self.afk_mode = False
        self.last_action = ""
        self.last_phase = None
        self.active_clearance = {}
        self.last_handoff = None
        self.last_tod_notice = 0.0

    def _log(self, speaker, message):
        self.app.comms_log_message(speaker, message)

    def set_afk(self, enabled):
        self.afk_mode = bool(enabled)
        self._log("COPILOT", "AFK COMMS " + ("ENABLED" if enabled else "DISABLED"))

    def _speak(self, message, data):
        nearest = self.app.navdata.nearest(data.get("lat", 0), data.get("lon", 0))
        country = nearest.get("iso_country") if nearest else None
        threading.Thread(target=speak_atc, args=(message, region_voice_locale(data.get("lat"), data.get("lon"), country)), daemon=True).start()

    def observe_atc(self, message, data):
        text = str(message)
        lower = text.lower()
        self.active_clearance = {"raw": text, "controller": self.app.atc_controller.controller, "frequency": self.app.atc_controller.frequency, "time": time.time()}
        m = re.search(r"\b([0-7]{4})\b", text) if "squawk" in lower else None
        if m: self.active_clearance["squawk"] = m.group(1)
        m = re.search(r"heading\s+(?:of\s+)?(\d{1,3})", lower)
        if m: self.active_clearance["heading"] = int(m.group(1)) % 360
        m = re.search(r"flight level\s+(\d{2,3})", lower)
        if m: self.active_clearance["altitude_ft"] = int(m.group(1)) * 100
        else:
            m = re.search(r"(?:climb|descend)(?: and maintain)?\s+(\d{3,5})", lower)
            if m: self.active_clearance["altitude_ft"] = int(m.group(1))

    def _reply_for(self, message, data):
        lower = str(message).lower()
        cs = data.get("callsign") or self.app.atc_controller.callsign or "aircraft"
        if "go around" in lower or "go-around" in lower: return "%s, going around." % cs
        if "cleared for takeoff" in lower: return "%s, cleared for takeoff." % cs
        if "contact " in lower or "switch" in lower: return "%s, switching." % cs
        if "hold position" in lower or "hold short" in lower: return "%s, holding position." % cs
        if any(x in lower for x in ("maintain", "climb", "descend", "heading", "taxi", "line up")): return "%s, wilco." % cs
        return "%s, copied." % cs

    def handle_atc(self, message, data):
        self.observe_atc(message, data)
        reply = self._reply_for(message, data)
        self._log("COPILOT", reply)
        self._speak(reply, data)

    def monitor(self, data):
        phase = data.get("phase")
        if phase != self.last_phase:
            self.last_phase = phase
            self._log("COPILOT", "Flight phase: %s." % phase)
        controller = self.app.atc_controller.controller
        freq = self.app.atc_controller.frequency
        if self.last_handoff != (controller, freq):
            self.last_handoff = (controller, freq)
            if phase not in ("PARKED", "NO TELEMETRY"): self._log("COPILOT", "Now with %s on %s." % (controller.title(), freq))
        target_alt = self.active_clearance.get("altitude_ft")
        if target_alt and data.get("connected") and abs(float(data.get("altitude", 0)) - target_alt) > 300:
            self._log("COPILOT", "Captain, altitude deviation from the last assigned altitude.")
        target_heading = self.active_clearance.get("heading")
        if target_heading is not None and data.get("connected"):
            delta = abs((float(data.get("heading", 0)) - target_heading + 180) % 360 - 180)
            if delta > 20: self._log("COPILOT", "Captain, heading deviation from the last assigned heading.")
        if phase == "CENTER" and target_alt and data.get("vertical_speed", 0) >= -100 and time.time() - self.last_tod_notice > 120:
            self.last_tod_notice = time.time()
            self._log("COPILOT", "Captain, prepare for descent toward the assigned altitude.")

    def update(self, data, atc_message=""):
        self.monitor(data)
        if self.afk_mode and atc_message and atc_message != self.last_action:
            self.last_action = atc_message
            self.handle_atc(atc_message, data)
class FlightExperienceEngine:
    """Local, deterministic flight-ops features; no external API required."""
    def __init__(self):
        self.checklist = []
        self.events = []
        self.started = time.time()

    def tod(self, altitude_ft, target_ft, groundspeed_kt, descent_fpm=1500):
        altitude_delta = max(0.0, float(altitude_ft) - float(target_ft))
        if altitude_delta <= 0 or groundspeed_kt <= 20 or descent_fpm <= 100:
            return None
        minutes = altitude_delta / float(descent_fpm)
        return groundspeed_kt * minutes / 60.0

    def approach_assessment(self, data):
        if not data.get("connected") or data.get("on_ground"):
            return "NO APPROACH DATA"
        issues = []
        alt = data.get("altitude", 0)
        vs = data.get("vertical_speed", 0)
        speed = data.get("speed", 0)
        if vs < -1200:
            issues.append("HIGH SINK")
        if vs > 1000 and alt < 3000:
            issues.append("HIGH DESCENT PROFILE")
        if speed > 190 and alt < 3000:
            issues.append("FAST BELOW 3000")
        return "STABLE" if not issues else "UNSTABLE: " + ", ".join(issues)

    def score(self, events, deviation_count=0):
        penalties = min(100, len(events) * 2 + deviation_count * 10)
        return max(0, 100 - penalties)

    def briefing(self, data, airport="UNKNOWN"):
        return (
            "FLIGHT BRIEFING\n"
            "Airport: %s\n"
            "Callsign: %s\n"
            "Altitude: %.0f ft\n"
            "Speed: %.0f kt\n"
            "Heading: %03.0f°\n"
            "Phase: %s"
        ) % (airport, data.get("callsign") or "N/A", data.get("altitude", 0),
             data.get("speed", 0), data.get("heading", 0), data.get("phase", "UNKNOWN"))


class ExperienceScreen(BoxLayout):
    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=10, spacing=6, **kwargs)
        self.app = app
        self.engine = FlightExperienceEngine()
        self.status = Label(text="Flight Experience Suite", halign="left", valign="top")
        self.add_widget(self.status)

        row = BoxLayout(size_hint_y=None, height=44, spacing=5)
        for title, callback in (
            ("BRIEFING", self.briefing),
            ("TOD", self.tod),
            ("APPROACH", self.approach),
            ("SCORE", self.score),
        ):
            b = Button(text=title)
            b.bind(on_press=callback)
            row.add_widget(b)
        self.add_widget(row)

        checklist_row = BoxLayout(size_hint_y=None, height=44, spacing=5)
        for item in ("Before Start", "Taxi", "Takeoff", "Approach", "Shutdown"):
            b = Button(text=item)
            b.bind(on_press=lambda _, x=item: self.add_checklist(x))
            checklist_row.add_widget(b)
        self.add_widget(checklist_row)

        scenario = BoxLayout(size_hint_y=None, height=44, spacing=5)
        for name in ("Go-Around", "Diversion", "Radio Failure", "Weather"):
            b = Button(text=name)
            b.bind(on_press=lambda _, x=name: self.scenario(x))
            scenario.add_widget(b)
        self.add_widget(scenario)

        self.log = TextInput(readonly=True, multiline=True)
        self.add_widget(self.log)

    def write(self, text):
        self.log.text += str(text) + "\n\n"

    def briefing(self, _):
        data = self.app.receiver.snapshot()
        self.write(self.engine.briefing(data, self.app.icao_input.text if hasattr(self.app, "icao_input") else "UNKNOWN"))

    def tod(self, _):
        data = self.app.receiver.snapshot()
        value = self.engine.tod(data.get("altitude", 0), 3000, data.get("speed", 0))
        self.write("TOD: %.1f NM before a 3,000 ft target at 1,500 fpm." % value if value is not None else "TOD unavailable: insufficient telemetry or already below target.")

    def approach(self, _):
        self.write("APPROACH: " + self.engine.approach_assessment(self.app.receiver.snapshot()))

    def score(self, _):
        deviations = sum(1 for e in self.app.flight_state.events if "deviation" in str(e).lower())
        self.write("FLIGHT SCORE: %d/100" % self.engine.score(self.app.flight_state.events, deviations))

    def add_checklist(self, item):
        self.engine.checklist.append(item)
        self.write("CHECKLIST: %s started." % item)

    def scenario(self, name):
        self.engine.events.append({"scenario": name, "time": time.time()})
        self.write("SCENARIO ARMED: %s. Copilot will keep this in the session log." % name)


class ScratchpadScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=12, spacing=8, **kwargs)
        self.add_widget(Label(text="C.R.A.F.T. IFR Clearance Scratchpad", size_hint_y=None, height=34))
        grid = GridLayout(cols=2, spacing=8)
        self.fields = {}
        for label, key in (
            ("C — Clearance limit", "clearance"),
            ("R — Route", "route"),
            ("A — Altitude", "altitude"),
            ("F — Frequency", "frequency"),
            ("T — Squawk", "squawk"),
        ):
            grid.add_widget(Label(text=label))
            field = TextInput(multiline=False)
            self.fields[key] = field
            grid.add_widget(field)
        self.add_widget(grid)

        buttons = BoxLayout(size_hint_y=None, height=48, spacing=8)
        clear = Button(text="Clear")
        clear.bind(on_press=self.clear_fields)
        buttons.add_widget(clear)
        copy = Button(text="Build Clearance")
        copy.bind(on_press=self.build_clearance)
        buttons.add_widget(copy)
        self.add_widget(buttons)

        self.output = TextInput(readonly=True, multiline=True, size_hint_y=0.3)
        self.add_widget(self.output)

    def clear_fields(self, _):
        for field in self.fields.values():
            field.text = ""
        self.output.text = ""

    def build_clearance(self, _):
        parts = []
        for key in ("clearance", "route", "altitude", "frequency", "squawk"):
            value = self.fields[key].text.strip()
            if value:
                parts.append(value)
        self.output.text = " | ".join(parts) if parts else "Enter clearance items above."


class AeroflyATCApp(App):
    def build(self):
        self.title = f"AeroflyATC {APP_VERSION}"
        self.receiver = TelemetryReceiver()
        self.receiver.start()
        self.flight_state = FlightStateEngine()
        self.atc_controller = ATCController()
        self.audio_engine = AudioEngine()
        self.replay = FlightReplay(self.flight_state)
        self.route_tracker = RouteTracker()
        self.traffic_engine = TrafficEngine()
        self.airports = AirportDatabase()
        self.terrain = TerrainWarningEngine()
        self.airspace = AirspaceStore(self.user_data_dir)
        self.airspace.load()
        self.elevation = SRTMElevation(self.user_data_dir)
        self.cabin = CabinCrewEngine()
        self.copilot = Copilot(self)
        self.map_tiles = OSMTileCache(self.user_data_dir)
        self.navdata = AirportData(self.user_data_dir)
        self.navdata.load_local()
        self.aerofly = AeroflyTCPConnector(self.receiver)
        self.aerofly.start("127.0.0.1")

        panel = TabbedPanel(do_default_tab=False)

        self.flight_screen = MyFlightScreen()
        flight_tab = TabbedPanelItem(text="My Flight")
        flight_tab.add_widget(self.flight_screen)
        panel.add_widget(flight_tab)

        map_tab = TabbedPanelItem(text="Map")
        self.map_screen = MovingMapScreen(self.receiver, self.map_tiles)
        map_tab.add_widget(self.map_screen)
        panel.add_widget(map_tab)

        connect_tab = TabbedPanelItem(text="Connect")
        connect_box = BoxLayout(orientation="vertical", padding=12, spacing=8)
        connect_box.add_widget(Label(text="Enable Aerofly Settings > Miscellaneous > Send flight data to FSWidgets Apps.", size_hint_y=None, height=55))
        ip_row = BoxLayout(size_hint_y=None, height=50, spacing=6)
        ip_row.add_widget(Label(text="Simulator IPv4:", size_hint_x=0.35))
        self.sim_ip = TextInput(text="127.0.0.1", multiline=False)
        ip_row.add_widget(self.sim_ip)
        connect_box.add_widget(ip_row)
        cb = Button(text="CONNECT TO TCP 58585", size_hint_y=None, height=55)
        cb.bind(on_press=lambda *_: self.aerofly.reconnect(self.sim_ip.text))
        connect_box.add_widget(cb)
        connect_box.add_widget(Label(text="Same-device default: 127.0.0.1. Remote device: enter its LAN IPv4 address. UDP 49002 is also accepted.", size_hint_y=None, height=65))
        connect_tab.add_widget(connect_box)
        panel.add_widget(connect_tab)

        ops_tab = TabbedPanelItem(text="Flight Ops")
        ops = BoxLayout(orientation="vertical", padding=10, spacing=6)
        self.ops_status = Label(text="Flight state engine starting...", halign="left", valign="top")
        ops.add_widget(self.ops_status)
        self.squawk_input = TextInput(text="2000", multiline=False, size_hint_y=None, height=48)
        ops.add_widget(self.squawk_input)
        squawk_btn = Button(text="ASSIGN SQUAWK", size_hint_y=None, height=48)
        squawk_btn.bind(on_press=lambda *_: setattr(self.flight_state, "squawk", self.squawk_input.text.strip() or "2000"))
        ops.add_widget(squawk_btn)
        wx_row = BoxLayout(size_hint_y=None, height=48, spacing=5)
        self.icao_input = TextInput(text="EBBR", hint_text="ICAO", multiline=False)
        wx_btn = Button(text="METAR/TAF", size_hint_x=0.35)
        wx_btn.bind(on_press=self.load_weather)
        wx_row.add_widget(self.icao_input)
        wx_row.add_widget(wx_btn)
        ops.add_widget(wx_row)
        self.wx_status = Label(text="Weather: not loaded", size_hint_y=None, height=70)
        ops.add_widget(self.wx_status)
        airspace_btn = Button(text="LOAD LOCAL OPENAIR AIRSPACE", size_hint_y=None, height=48)
        airspace_btn.bind(on_press=lambda *_: self.load_airspace())
        ops.add_widget(airspace_btn)
        nav_btn = Button(text="UPDATE WORLD AIRPORT DATABASE", size_hint_y=None, height=48)
        nav_btn.bind(on_press=lambda *_: self.update_navdata())
        ops.add_widget(nav_btn)
        cabin_btn = Button(text="CALL CABIN CREW", size_hint_y=None, height=48)
        cabin_btn.bind(on_press=lambda *_: self.call_cabin_crew("Please report cabin status."))
        ops.add_widget(cabin_btn)
        atis_btn = Button(text="GENERATE ATIS", size_hint_y=None, height=48)
        atis_btn.bind(on_press=self.generate_atis)
        ops.add_widget(atis_btn)
        export_btn = Button(text="EXPORT FLIGHT LOG", size_hint_y=None, height=48)
        export_btn.bind(on_press=self.export_flight_log)
        ops.add_widget(export_btn)
        ops_tab.add_widget(ops)
        panel.add_widget(ops_tab)

        comms_tab = TabbedPanelItem(text="Comms")
        self.comms_screen = CommsScreen(self.receiver, self.call_cabin_crew, self.copilot)
        comms_tab.add_widget(self.comms_screen)
        panel.add_widget(comms_tab)

        exp_tab = TabbedPanelItem(text="Experience")
        self.experience_screen = ExperienceScreen(self)\n        exp_tab.add_widget(self.experience_screen)
        panel.add_widget(exp_tab)

                scratch_tab = TabbedPanelItem(text="Scratchpad")
        scratch_tab.add_widget(ScratchpadScreen())
        panel.add_widget(scratch_tab)

        Clock.schedule_interval(self.update_ui, 0.5)
        return panel

    def update_ui(self, _dt):
        data = self.flight_state.update(self.receiver.snapshot())
        self.flight_screen.update(data)
        self.route_tracker.add(data.get("lat", 0), data.get("lon", 0), data.get("callsign"))
        nearest_record = self.navdata.nearest(data.get("lat", 0), data.get("lon", 0))
        nearest = self.airports.nearest(data.get("lat", 0), data.get("lon", 0))
        if nearest_record:
            nearest = (nearest_record.get("ident") or nearest_record.get("gps_code") or nearest_record.get("iata_code") or "NEAR", nearest_record)
        if data.get("connected"):
            terrain_ft = self.elevation.elevation_ft(data.get("lat", 0), data.get("lon", 0))
            active_airspace = self.airspace.active_at(data.get("lat", 0), data.get("lon", 0), data.get("altitude", 0))
        else:
            terrain_ft, active_airspace = None, []
        traffic = self.traffic_engine.update(data)
        terrain_alerts = self.terrain.check(data, nearest)
        if terrain_ft is not None and data.get("altitude", 0) - terrain_ft < 1000 and not data.get("on_ground", False):
            terrain_alerts.append("TERRAIN CLEARANCE %.0f FT" % (data.get("altitude", 0) - terrain_ft))
        if terrain_alerts and hasattr(self, "ops_status"): self.ops_status.text += "\\nWARNING: " + " | ".join(terrain_alerts)
        if active_airspace and hasattr(self, "ops_status"):
            names = ", ".join(a.get("name") or a.get("type") or a.get("class") for a in active_airspace[:3])
            self.ops_status.text += "\\nAIRSPACE: " + names
        announcement = self.cabin.update(data.get("phase"))
        country = nearest.get("iso_country") if nearest else None
        if announcement:
            speak_atc(announcement, region_voice_locale(data.get("lat"), data.get("lon"), country))
        atc_msg = self.atc_controller.generate(data)
        if atc_msg and hasattr(self, "ops_status"):
            self.ops_status.text += "\\nATC: " + atc_msg
            speak_atc(self.audio_engine.radio_effect_text(atc_msg), region_voice_locale(data.get("lat"), data.get("lon"), country))
        self.copilot.update(data)
        if hasattr(self, "experience_screen"):
            pass
        if hasattr(self, "map_screen"):
            self.map_screen.update(data)
        if hasattr(self, "ops_status"):
            self.ops_status.text = "PHASE: %s\\nCALLSIGN: %s\\nALT: %.0f ft\\nGS: %.0f kt\\nVS: %.0f fpm\\nHDG: %03.0f°\\nSQUAWK: %s\\n\\nEvents: %d" % (data.get("phase", "UNKNOWN"), data.get("callsign", "N/A"), data.get("altitude", 0), data.get("speed", 0), data.get("vertical_speed", 0), data.get("heading", 0), data.get("squawk", "2000"), len(self.flight_state.events))
        if hasattr(self, "map_screen"):
            self.map_screen.update(data)

    def on_pause(self):
        return True


    def comms_log_message(self, speaker, message):
        if hasattr(self, "comms_screen"):
            self.comms_screen.append_conversation(speaker, message)

    def load_airspace(self):
        count = self.airspace.load()
        if hasattr(self, "ops_status"):
            self.ops_status.text = "Loaded %d OpenAir airspace definitions from %s" % (count, self.airspace.base_dir)

    def update_navdata(self):
        if hasattr(self, "ops_status"):
            self.ops_status.text = "Updating public-domain OurAirports database..."
        self.navdata.update(lambda count: setattr(self.ops_status, "text", "Airport database updated: %d records" % count))

    def call_cabin_crew(self, request):
        response = self.cabin.call_reply(request)
        data = self.receiver.snapshot()
        nearest = self.navdata.nearest(data.get("lat", 0), data.get("lon", 0))
        country = nearest.get("iso_country") if nearest else None
        speak_atc(response, region_voice_locale(data.get("lat"), data.get("lon"), country))
        if hasattr(self, "ops_status"):
            self.ops_status.text = "CABIN: " + response

    def load_weather(self, _=None):
        def worker():
            try:
                w = weather_snapshot(self.icao_input.text)
                met = w["metar"][0] if w["metar"] else {}
                taf = w["taf"][0] if w["taf"] else {}
                text = "METAR %s: %s\\nTAF: %s" % (w["icao"], met.get("rawOb", "No METAR"), taf.get("rawTAF", "No TAF"))
            except Exception as exc:
                text = "Weather unavailable: " + str(exc)
            Clock.schedule_once(lambda *_: setattr(self.wx_status, "text", text))
        threading.Thread(target=worker, daemon=True).start()

    def generate_atis(self, _=None):
        data = self.receiver.snapshot()
        wx = getattr(self, "wx_status", None)
        raw = wx.text if wx else "Weather not loaded"
        msg = "ATIS for %s. Information Alpha. Aircraft currently heading %03.0f degrees at %.0f knots. %s" % (self.icao_input.text.upper(), data.get("heading", 0), data.get("speed", 0), raw[:300])
        if hasattr(self, "ops_status"):
            self.ops_status.text += "\\n\\n" + msg
        speak_atc(msg)

    def export_flight_log(self, _=None):
        try:
            path = os.path.join(App.get_running_app().user_data_dir, "flight_log.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.flight_state.snapshot(), fh, indent=2)
            if hasattr(self, "ops_status"):
                self.ops_status.text += "\\nLog saved: " + path
        except Exception as exc:
            if hasattr(self, "ops_status"):
                self.ops_status.text += "\\nLog export failed: " + str(exc)

    def on_stop(self):
        self.aerofly.stop()
        self.receiver.stop()


if __name__ == "__main__":
    AeroflyATCApp().run()
