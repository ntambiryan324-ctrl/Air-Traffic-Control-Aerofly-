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
from kivy.graphics import Color, Line, Triangle


APP_VERSION = "1.1.0"
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
        if on_ground and speed < 35:
            self.phase = "GROUND"
        elif on_ground and speed >= 35:
            self.phase = "TAKEOFF"
        elif not on_ground and vs > 300:
            self.phase = "DEPARTURE"
        elif not on_ground and vs < -300:
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



def speak_atc(text):
    try:
        from jnius import autoclass
        Activity = autoclass("org.kivy.android.PythonActivity")
        TTS = autoclass("android.speech.tts.TextToSpeech")
        Locale = autoclass("java.util.Locale")
        tts = TTS(Activity.mActivity, None)
        tts.setLanguage(Locale.US)
        tts.speak(str(text), TTS.QUEUE_FLUSH, None, "atc")
    except Exception as exc:
        print("TTS unavailable:", exc)



def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/1.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def weather_snapshot(icao):
    """METAR/airport lookup via public aviationweather.gov API when network is available."""
    icao = (icao or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", icao):
        raise ValueError("ICAO must be four characters")
    metar = fetch_json("https://aviationweather.gov/api/data/metar?ids=%s&format=json" % urllib.parse.quote(icao))
    taf = fetch_json("https://aviationweather.gov/api/data/taf?ids=%s&format=json" % urllib.parse.quote(icao))
    return {"icao": icao, "metar": metar, "taf": taf}

class AudioEngine:
def fetch_json(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "AeroflyATC/1.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def weather_snapshot(icao):
    """METAR/airport lookup via public aviationweather.gov API when network is available."""
    icao = (icao or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4}", icao):
        raise ValueError("ICAO must be four characters")
    metar = fetch_json("https://aviationweather.gov/api/data/metar?ids=%s&format=json" % urllib.parse.quote(icao))
    taf = fetch_json("https://aviationweather.gov/api/data/taf?ids=%s&format=json" % urllib.parse.quote(icao))
    return {"icao": icao, "metar": metar, "taf": taf}


    """Generates radio/cabin ambience without shipping copyrighted recordings."""
    def __init__(self):
        self.enabled = True
        self.radio = True
        self.cabin = True

    def toggle(self):
        self.enabled = not self.enabled

    def radio_effect_text(self, message):
        if not self.enabled or not self.radio:
            return message
        return "KRRR... " + str(message) + " ...KSH"

class MovingMapScreen(BoxLayout):
    def __init__(self, receiver, **kwargs):
        super().__init__(orientation="vertical", padding=6, spacing=4, **kwargs)
        self.receiver = receiver
        self.trail = []
        self.add_widget(Label(text="LIVE MOVING MAP / RADAR", size_hint_y=None, height=32))
        self.status = Label(text="Waiting for Aerofly telemetry...", size_hint_y=None, height=28)
        self.add_widget(self.status)
        self.map_box = BoxLayout()
        self.add_widget(self.map_box)
        with self.map_box.canvas:
            Color(0.06, 0.07, 0.09, 1)
            self.grid = [Line(points=[0,0,0,0], width=1) for _ in range(13)]
            Color(0.95, 0.72, 0.08, 1)
            self.plane = Triangle(points=[0,0,0,0,0,0])
            Color(0.15, 0.75, 1, 1)
            self.track = Line(points=[], width=2)
        self.map_box.bind(size=lambda *_: self.redraw())
        self.map_box.bind(pos=lambda *_: self.redraw())

    def update(self, data):
        if data["lat"] or data["lon"]:
            p = (data["lat"], data["lon"])
            if not self.trail or p != self.trail[-1]: self.trail.append(p)
            self.trail = self.trail[-400:]
        if data["connected"]:
            self.status.text = "CONNECTED  %.5f, %.5f | %.0f ft | %.0f kt | %03.0f°" % (data["lat"], data["lon"], data["altitude"], data["speed"], data["heading"])
        else:
            self.status.text = "Waiting for Aerofly — enable Send flight data to FSWidgets Apps"
        self.redraw()

    def redraw(self):
        w, h = self.map_box.size
        cx, cy = self.map_box.x + w/2, self.map_box.y + h/2
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
    def __init__(self, telemetry_receiver, **kwargs):
        super().__init__(orientation="vertical", padding=12, spacing=8, **kwargs)
        self.telemetry_receiver = telemetry_receiver

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

    def toggle_tts(self, button):
        self.tts_enabled = not self.tts_enabled
        button.text = "ATC TTS: ON" if self.tts_enabled else "ATC TTS: OFF"

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

        self.atc_log.text += f"PILOT: {text}\nATC: [Processing...]\n\n"
        self.pilot_input.text = ""
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
        marker = "ATC: [Processing...]\n\n"
        if marker in self.atc_log.text:
            self.atc_log.text = self.atc_log.text.replace(marker, "", 1)
        self.atc_log.text += f"ATC: {response}\n\n"
        if getattr(self, "tts_enabled", True):
            threading.Thread(target=speak_atc, args=(response,), daemon=True).start()


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
        self.aerofly = AeroflyTCPConnector(self.receiver)
        self.aerofly.start("127.0.0.1")

        panel = TabbedPanel(do_default_tab=False)

        self.flight_screen = MyFlightScreen()
        flight_tab = TabbedPanelItem(text="My Flight")
        flight_tab.add_widget(self.flight_screen)
        panel.add_widget(flight_tab)

        map_tab = TabbedPanelItem(text="Map")
        self.map_screen = MovingMapScreen(self.receiver)
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
        atis_btn = Button(text="GENERATE ATIS", size_hint_y=None, height=48)
        atis_btn.bind(on_press=self.generate_atis)
        ops.add_widget(atis_btn)
        export_btn = Button(text="EXPORT FLIGHT LOG", size_hint_y=None, height=48)
        export_btn.bind(on_press=self.export_flight_log)
        ops.add_widget(export_btn)
        ops_tab.add_widget(ops)
        panel.add_widget(ops_tab)

        comms_tab = TabbedPanelItem(text="Comms")
        comms_tab.add_widget(CommsScreen(self.receiver))
        panel.add_widget(comms_tab)

        scratch_tab = TabbedPanelItem(text="Scratchpad")
        scratch_tab.add_widget(ScratchpadScreen())
        panel.add_widget(scratch_tab)

        Clock.schedule_interval(self.update_ui, 0.5)
        return panel

    def update_ui(self, _dt):
        data = self.flight_state.update(self.receiver.snapshot())
        self.flight_screen.update(data)
        if hasattr(self, "map_screen"):
            self.map_screen.update(data)
        if hasattr(self, "ops_status"):
            self.ops_status.text = "PHASE: %s\\nCALLSIGN: %s\\nALT: %.0f ft\\nGS: %.0f kt\\nVS: %.0f fpm\\nHDG: %03.0f°\\nSQUAWK: %s\\n\\nEvents: %d" % (data.get("phase", "UNKNOWN"), data.get("callsign", "N/A"), data.get("altitude", 0), data.get("speed", 0), data.get("vertical_speed", 0), data.get("heading", 0), data.get("squawk", "2000"), len(self.flight_state.events))
        if hasattr(self, "map_screen"):
            self.map_screen.update(data)

    def on_pause(self):
        return True


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
