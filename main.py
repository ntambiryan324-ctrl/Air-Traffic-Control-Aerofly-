import os
import math
import re
import socket
import ssl
import threading
import time
import urllib.request

import certifi
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Line, Ellipse, Triangle, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.stencilview import StencilView
from kivy.uix.widget import Widget

BG = (0.035, 0.055, 0.075, 1)
PANEL = (0.075, 0.10, 0.13, 1)
TEXT = (0.92, 0.95, 0.98, 1)
MUTED = (0.62, 0.70, 0.77, 1)
GREEN = (0.16, 0.85, 0.48, 1)
BLUE = (0.18, 0.58, 0.95, 1)


def tile_xy(lat, lon, zoom):
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat = max(-85.0511, min(85.0511, lat))
    rad = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(rad)) / math.pi) / 2.0 * n
    return x, y


class MovingMap(StencilView):
    """OpenStreetMap tile map with cached tiles and a real aircraft overlay."""
    TILE_SIZE = 256
    OSM_TEMPLATE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"

    def __init__(self, cache_dir=None, **kwargs):
        super().__init__(**kwargs)
        app = App.get_running_app()
        self.cache_dir = cache_dir or os.path.join(getattr(app, "user_data_dir", "."), "osm_tiles")
        os.makedirs(self.cache_dir, exist_ok=True)
        # Use a bundled Mozilla CA store on Android; keep certificate and hostname
        # verification enabled instead of bypassing TLS checks.
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.center_lat = 0.3476
        self.center_lon = 32.5825
        self.zoom = 7
        self.follow = True
        self.aircraft_lat = None
        self.aircraft_lon = None
        self.heading = 0.0
        self.tiles = {}
        self.tile_errors = 0
        self.last_tile_error = ""
        self._inflight = set()
        self._failed_until = {}
        self._tile_lock = threading.RLock()
        self._workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="osm-tile")
        self._drag_last = None
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())

    @staticmethod
    def _latlon_to_world(lat, lon, zoom):
        n = 2 ** zoom
        lat = max(-85.05112878, min(85.05112878, float(lat)))
        lon = ((float(lon) + 180.0) % 360.0) - 180.0
        x = (lon + 180.0) / 360.0 * n * 256.0
        lat_rad = math.radians(lat)
        y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n * 256.0
        return x, y

    @staticmethod
    def _world_to_latlon(x, y, zoom):
        world = (2 ** zoom) * 256.0
        x %= world
        y = max(0.0, min(world - 1.0, y))
        lon = x / world * 360.0 - 180.0
        n = math.pi - 2.0 * math.pi * y / world
        lat = math.degrees(math.atan(math.sinh(n)))
        return lat, lon

    def set_position(self, lat, lon, heading):
        try:
            lat, lon, heading = float(lat), float(lon), float(heading)
        except (TypeError, ValueError):
            return
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return
        heading = heading % 360.0
        position_changed = (
            self.aircraft_lat is None
            or abs(lat - self.aircraft_lat) > 1e-5
            or abs(lon - self.aircraft_lon) > 1e-5
            or abs((heading - self.heading + 180.0) % 360.0 - 180.0) > 0.5
        )
        self.aircraft_lat, self.aircraft_lon, self.heading = lat, lon, heading
        center_changed = False
        if self.follow:
            center_changed = (abs(lat - self.center_lat) > 1e-6 or
                              abs(lon - self.center_lon) > 1e-6)
            if center_changed:
                self.center_lat, self.center_lon = lat, lon
        # Avoid clearing and redrawing the full tile canvas for identical telemetry.
        if position_changed or center_changed:
            self.redraw()

    def center_plane(self):
        self.follow = True
        if self.aircraft_lat is not None:
            self.center_lat, self.center_lon = self.aircraft_lat, self.aircraft_lon
        self.redraw()

    def pan(self, dx, dy):
        self.follow = False
        cx, cy = self._latlon_to_world(self.center_lat, self.center_lon, self.zoom)
        self.center_lat, self.center_lon = self._world_to_latlon(cx - dx, cy + dy, self.zoom)
        self.redraw()

    def zoom_by(self, amount):
        new_zoom = max(3, min(18, self.zoom + int(amount)))
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom
        if self.follow and self.aircraft_lat is not None:
            self.center_lat, self.center_lon = self.aircraft_lat, self.aircraft_lon
        self.redraw()

    def _tile_path(self, z, x, y):
        return os.path.join(self.cache_dir, str(z), str(x), str(y) + ".png")

    def _request_tile(self, key):
        z, x, y = key
        now = time.time()
        with self._tile_lock:
            if key in self.tiles or key in self._inflight:
                return
            if self._failed_until.get(key, 0) > now:
                return
            self._inflight.add(key)
        self._workers.submit(self._load_tile, key)

    def _load_tile(self, key):
        z, x, y = key
        path = self._tile_path(z, x, y)
        try:
            data = None
            if os.path.isfile(path):
                with open(path, "rb") as handle:
                    data = handle.read()
            else:
                url = self.OSM_TEMPLATE.format(z=z, x=x, y=y)
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "AeroflyATC/3.0 (Android telemetry map; https://github.com/ntambiryan324-ctrl/Air-Traffic-Control-Aerofly-)",
                        "Accept": "image/png,image/*;q=0.8,*/*;q=0.5",
                    },
                )
                with urllib.request.urlopen(request, timeout=12, context=self._ssl_context) as response:
                    if response.status != 200:
                        raise OSError("HTTP " + str(response.status))
                    data = response.read()
                if not data:
                    raise OSError("Empty OSM tile response")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                temp_path = path + ".tmp"
                with open(temp_path, "wb") as handle:
                    handle.write(data)
                os.replace(temp_path, path)
            Clock.schedule_once(lambda dt, k=key, d=data: self._tile_loaded(k, d, None), 0)
        except Exception as exc:
            Clock.schedule_once(lambda dt, k=key, e=str(exc): self._tile_loaded(k, None, e), 0)

    def _tile_loaded(self, key, data, error):
        with self._tile_lock:
            self._inflight.discard(key)
            if error:
                self.tile_errors += 1
                self.last_tile_error = error
                self._failed_until[key] = time.time() + 20.0
            else:
                try:
                    texture = CoreImage(BytesIO(data), ext="png").texture
                    self.tiles[key] = texture
                    self._failed_until.pop(key, None)
                except Exception as exc:
                    # A truncated/corrupt cache entry would otherwise fail forever.
                    try:
                        os.remove(self._tile_path(*key))
                    except OSError:
                        pass
                    self.tile_errors += 1
                    self.last_tile_error = "Tile decode: " + str(exc)
                    self._failed_until[key] = time.time() + 30.0
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        if self.width < 2 or self.height < 2:
            return
        z = self.zoom
        world_size = (2 ** z) * self.TILE_SIZE
        center_x, center_y = self._latlon_to_world(self.center_lat, self.center_lon, z)
        left_world = center_x - self.width / 2.0
        right_world = center_x + self.width / 2.0
        top_world = center_y + self.height / 2.0
        bottom_world = center_y - self.height / 2.0
        min_tx = math.floor(left_world / self.TILE_SIZE)
        max_tx = math.floor(right_world / self.TILE_SIZE)
        min_ty = math.floor((center_y - self.height / 2.0) / self.TILE_SIZE)
        max_ty = math.floor((center_y + self.height / 2.0) / self.TILE_SIZE)
        n = 2 ** z

        with self.canvas:
            Color(0.86, 0.88, 0.85, 1)
            Rectangle(pos=self.pos, size=self.size)
            for ty in range(min_ty, max_ty + 1):
                if ty < 0 or ty >= n:
                    continue
                for tx in range(min_tx, max_tx + 1):
                    tile_x = tx % n
                    key = (z, tile_x, ty)
                    sx = self.center_x + tx * self.TILE_SIZE - center_x
                    sy = self.center_y + center_y - (ty + 1) * self.TILE_SIZE
                    with self._tile_lock:
                        texture = self.tiles.get(key)
                    if texture is not None:
                        Color(1, 1, 1, 1)
                        Rectangle(texture=texture, pos=(sx, sy),
                                  size=(self.TILE_SIZE, self.TILE_SIZE))
                    else:
                        Color(0.78, 0.81, 0.77, 1)
                        Rectangle(pos=(sx, sy), size=(self.TILE_SIZE, self.TILE_SIZE))
                        self._request_tile(key)

            # Show a stationary test marker before telemetry arrives; switch to green on live data.
            if self.aircraft_lat is None:
                px, py = self.center_x, self.center_y
                Color(1.0, 0.65, 0.05, 0.22)
                Ellipse(pos=(px-dp(14), py-dp(14)), size=(dp(28), dp(28)))
                Color(0.95, 0.55, 0.05, 1)
            else:
                aircraft_x, aircraft_y = self._latlon_to_world(self.aircraft_lat, self.aircraft_lon, z)
                delta_x = aircraft_x - center_x
                if delta_x > world_size / 2:
                    delta_x -= world_size
                elif delta_x < -world_size / 2:
                    delta_x += world_size
                px = self.center_x + delta_x
                py = self.center_y + center_y - aircraft_y
                Color(0.08, 0.95, 0.58, 0.22)
                Ellipse(pos=(px-dp(15), py-dp(15)), size=(dp(30), dp(30)))
                Color(0.05, 0.82, 0.42, 1)

            # Nose points along the current heading; its position is tied to geographic coordinates.
            angle = math.radians(self.heading)
            fx, fy = math.sin(angle), math.cos(angle)
            side_x, side_y = fy, -fx
            p1 = (px + fx*dp(13), py + fy*dp(13))
            p2 = (px - fx*dp(8) + side_x*dp(7), py - fy*dp(8) + side_y*dp(7))
            p3 = (px - fx*dp(8) - side_x*dp(7), py - fy*dp(8) - side_y*dp(7))
            Triangle(points=[p1[0],p1[1],p2[0],p2[1],p3[0],p3[1]])
            Color(0.06, 0.10, 0.13, 1)
            Line(points=[p1[0],p1[1],p2[0],p2[1],p3[0],p3[1],p1[0],p1[1]], width=1)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._drag_last = touch.pos
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self and self._drag_last is not None:
            old_x, old_y = self._drag_last
            self.pan(touch.x-old_x, touch.y-old_y)
            self._drag_last = touch.pos
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._drag_last = None
            return True
        return super().on_touch_up(touch)

    def retry_tiles(self):
        """Clear retry backoff after connectivity/certificate settings are corrected."""
        with self._tile_lock:
            self._failed_until.clear()
        self.redraw()

    def close(self):
        try:
            self._workers.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._workers.shutdown(wait=False)


class Telemetry:
    TCP_PORT = 58585
    UDP_PORTS = (49002, 40092)

    @staticmethod
    def detect_local_ip():
        probe = None
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
        except OSError:
            return ""
        finally:
            if probe:
                probe.close()

    def __init__(self):
        self.host = self.detect_local_ip() or "127.0.0.1"
        self.running = False
        self.lock = threading.RLock()
        self.tcp = None
        self.data = {"connected": False, "transport": "WAITING", "lat": None, "lon": None,
                     "alt_ft": 0.0, "speed_kt": 0.0, "heading": 0.0, "pitch": 0.0,
                     "bank": 0.0, "sim": "", "packets": 0, "last_packet": 0.0,
                     "message": "Enter simulator IP, then tap CONNECT"}

    def start(self):
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._udp_loop, daemon=True).start()
        threading.Thread(target=self._tcp_loop, daemon=True).start()

    def set_host(self, host):
        host = host.strip() or "127.0.0.1"
        if host == self.host:
            return
        self.host = host
        s = self.tcp
        if s:
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: s.close()
            except OSError: pass

    def _parse(self, raw, transport, source):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        # Aerofly/FSWidgets streams may delimit records with CR, LF, or CRLF.
        for line in re.split(r"[\r\n]+", text):
            line=line.strip()
            try:
                if line.startswith("XGPS"):
                    p=line[4:].strip().split(",")
                    if len(p)<6: continue
                    with self.lock:
                        self.data.update({"sim":p[0].strip(),"lon":float(p[1]),"lat":float(p[2]),
                            "alt_ft":float(p[3])*3.280839895,"heading":float(p[4])%360,
                            "speed_kt":float(p[5])*1.943844492,"connected":True,
                            "transport":transport,"message":"Telemetry received from "+source,
                            "last_packet":time.time(),"packets":self.data["packets"]+1})
                elif line.startswith("XATT"):
                    p=line[4:].strip().split(",")
                    if len(p)<4: continue
                    with self.lock:
                        self.data.update({"sim":p[0].strip(),"heading":float(p[1])%360,
                            "pitch":float(p[2]),"bank":float(p[3]),"connected":True,
                            "transport":transport,"message":"Telemetry received from "+source,
                            "last_packet":time.time(),"packets":self.data["packets"]+1})
            except (ValueError, IndexError):
                continue

    def _udp_loop(self):
        while self.running:
            opened=[]
            try:
                # Bind each UDP port independently so a port conflict does not disable the other.
                for port in self.UDP_PORTS:
                    try:
                        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                        s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                        s.bind(("0.0.0.0",port));s.settimeout(1)
                        opened.append((port,s))
                    except OSError:
                        try:s.close()
                        except Exception:pass
                if not opened:
                    with self.lock: self.data["message"]="UDP 49002/40092 unavailable (port already in use?)"
                    time.sleep(2);continue
                while self.running:
                    for port,s in opened:
                        try:
                            raw,addr=s.recvfrom(65535)
                            self._parse(raw,"UDP "+str(port),addr[0])
                        except socket.timeout: pass
                        except OSError: break
            finally:
                for _,s in opened:
                    try:s.close()
                    except OSError:pass
            time.sleep(.5)

    def _tcp_loop(self):
        while self.running:
            s=None
            requested_host=self.host
            connected_host=requested_host
            try:
                # On the same Android device, Aerofly may expose the service on loopback
                # or only on the device's active IPv4 interface. Try both automatically.
                # The official FSWidgets setup specifies the simulator device's local IP,
                # not 127.0.0.1. Try the active interface first, loopback second.
                candidates=[]
                detected=self.detect_local_ip()
                for candidate in (requested_host, detected, "127.0.0.1"):
                    if candidate and candidate not in candidates:
                        candidates.append(candidate)
                last_error=None
                for candidate in candidates:
                    with self.lock:
                        self.data["message"]=f"Connecting to {candidate}:{self.TCP_PORT}..."
                    try:
                        s=socket.create_connection((candidate,self.TCP_PORT),timeout=4)
                        connected_host=candidate
                        break
                    except OSError as e:
                        last_error=e
                if s is None:
                    raise last_error or OSError("No simulator address could be reached")
                s.settimeout(2)
                self.tcp=s
                s.sendall(b"GET / HTTP/1.1\r\n\r\n")
                with self.lock:
                    self.data["message"]=f"TCP connected at {connected_host}:{self.TCP_PORT}; waiting for telemetry"
                buf=b""
                while self.running and requested_host==self.host:
                    try:
                        chunk=s.recv(8192)
                        if not chunk:
                            break
                        buf+=chunk
                        # Accept CR, LF, or CRLF record separators. A CR-only stream
                        # must not sit forever in the buffer waiting for a newline.
                        buf=buf.replace(b"\r", b"\n")
                        while b"\n" in buf:
                            line,buf=buf.split(b"\n",1)
                            self._parse(line,"TCP 58585",connected_host)
                        # Some implementations send one complete XGPS/XATT record without
                        # a trailing newline. Parse it once enough fields are present.
                        if buf.startswith((b"XGPS", b"XATT")):
                            fields=buf.count(b",")
                            if (buf.startswith(b"XGPS") and fields >= 5) or (buf.startswith(b"XATT") and fields >= 3):
                                self._parse(buf,"TCP 58585",connected_host)
                                buf=b""
                    except socket.timeout:
                        if time.time()-self.data["last_packet"]>5:
                            with self.lock:
                                self.data["connected"]=False
                                self.data["message"]=f"TCP reachable at {connected_host}:{self.TCP_PORT}, but no telemetry received. Enable Send flight data to FSWidgets Apps in Aerofly."
            except OSError as e:
                with self.lock:
                    self.data["connected"]=False
                    self.data["message"]=f"TCP {self.TCP_PORT} failed: {e}. Check Aerofly FSWidgets setting and target IP."
                time.sleep(2)
            finally:
                if s:
                    try:s.close()
                    except OSError:pass
                self.tcp=None
            time.sleep(1)

    def snapshot(self):
        with self.lock:
            d=dict(self.data)
        if time.time()-d["last_packet"]>5:
            d["connected"]=False
        return d

    def stop(self):
        self.running=False
        if self.tcp:
            try:self.tcp.close()
            except OSError:pass


class AeroflyATCApp(App):
    title = "Aerofly Telemetry Map"

    def _label(self, text, size="12sp", color=TEXT, bold=False, halign="left"):
        w = Label(text=text, font_size=size, color=color, bold=bold,
                  halign=halign, valign="middle", shorten=True, shorten_from="right")
        w.bind(size=lambda obj, *_: setattr(obj, "text_size", obj.size))
        return w

    def build(self):
        self.telemetry = Telemetry()
        root = BoxLayout(orientation="vertical", spacing=dp(0), padding=dp(0))
        with root.canvas.before:
            Color(*BG)
            self._bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda w, *_: setattr(self._bg_rect, "pos", w.pos),
                  size=lambda w, *_: setattr(self._bg_rect, "size", w.size))

        header = BoxLayout(size_hint_y=None, height=dp(44), padding=(dp(12),0,dp(10),0), spacing=dp(8))
        header.add_widget(self._label("AEROFLY  /  TELEMETRY TEST", "14sp", TEXT, True))
        self.state = self._label("WAITING", "11sp", MUTED, True, "right")
        self.state.size_hint_x = None
        self.state.width = dp(94)
        header.add_widget(self.state)
        root.add_widget(header)

        map_head = BoxLayout(size_hint_y=None, height=dp(28), padding=(dp(12),0), spacing=dp(6))
        map_head.add_widget(self._label("OPENSTREETMAP", "10sp", BLUE, True))
        map_head.add_widget(self._label("DRAG TO PAN  •  +/- TO ZOOM", "9sp", MUTED, False, "right"))
        root.add_widget(map_head)

        self.map = MovingMap(cache_dir=os.path.join(self.user_data_dir, "osm_tiles"))
        root.add_widget(self.map)

        map_tools = BoxLayout(size_hint_y=None, height=dp(42), padding=(dp(8),dp(3)), spacing=dp(6))
        for title, action in (("−", lambda *_: self.map.zoom_by(-1)),
                              ("CENTER AIRCRAFT", lambda *_: self.map.center_plane()),
                              ("+", lambda *_: self.map.zoom_by(1)),
                              ("RETRY MAP", lambda *_: self.map.retry_tiles())):
            b = Button(text=title, background_normal="", background_color=PANEL,
                       color=TEXT, font_size="12sp")
            b.bind(on_press=action)
            map_tools.add_widget(b)
        root.add_widget(map_tools)

        self.metrics = self._label("LAT --   LON --   ALT -- ft   GS -- kt   HDG ---°", "11sp", TEXT, True)
        self.metrics.size_hint_y = None
        self.metrics.height = dp(32)
        self.metrics.padding = (dp(12),0)
        root.add_widget(self.metrics)

        connection = BoxLayout(size_hint_y=None, height=dp(48), padding=(dp(8),dp(4)), spacing=dp(6))
        self.ip = TextInput(text=self.telemetry.host, hint_text="Simulator device IPv4 address",
                            multiline=False, size_hint_x=0.68,
                            background_normal="", background_active="",
                            background_color=PANEL, foreground_color=TEXT,
                            cursor_color=TEXT, hint_text_color=MUTED,
                            padding=(dp(10),dp(10)))
        connect = Button(text="CONNECT", size_hint_x=0.32, background_normal="",
                         background_color=BLUE, color=TEXT, bold=True)
        connect.bind(on_press=self.connect)
        connection.add_widget(self.ip)
        connection.add_widget(connect)
        root.add_widget(connection)

        self.map_note = self._label("Loading OpenStreetMap tiles… • © OpenStreetMap contributors", "9sp", MUTED)
        self.map_note.size_hint_y = None
        self.map_note.height = dp(22)
        self.map_note.padding = (dp(12),0)
        root.add_widget(self.map_note)

        self.status = self._label("TCP 58585  •  UDP 49002 / 40092  •  Enable FSWidgets data in Aerofly", "10sp", MUTED)
        self.status.size_hint_y = None
        self.status.height = dp(36)
        self.status.padding = (dp(12),0)
        root.add_widget(self.status)

        Clock.schedule_once(lambda *_: self.telemetry.start(), 0.4)
        Clock.schedule_interval(self.refresh, 0.5)
        return root

    def connect(self, *_):
        self.telemetry.set_host(self.ip.text)
        with self.telemetry.lock:
            self.telemetry.data["message"] = (
                f"Trying TCP {self.ip.text.strip()}:{self.telemetry.TCP_PORT}; UDP listeners active"
            )
        if not self.telemetry.running:
            self.telemetry.start()

    def refresh(self, *_):
        d = self.telemetry.snapshot()
        self.state.text = "CONNECTED" if d["connected"] else "WAITING"
        self.state.color = GREEN if d["connected"] else MUTED
        self.status.text = (d["message"] + "  |  " + d["transport"] +
                            "  |  packets " + str(d["packets"]))
        if self.map.tile_errors and not self.map.tiles:
            detail = (self.map.last_tile_error or "network unavailable").replace("\n", " ")[:90]
            self.map_note.text = "OSM tile error: " + detail + " • © OpenStreetMap contributors"
        elif not self.map.tiles:
            self.map_note.text = "Loading OpenStreetMap tiles… • © OpenStreetMap contributors"
        elif d["lat"] is None:
            self.map_note.text = "Map ready; waiting for aircraft telemetry • © OpenStreetMap contributors"
        else:
            self.map_note.text = "LIVE AIRCRAFT POSITION • © OpenStreetMap contributors"
        if d["lat"] is not None and d["lon"] is not None:
            self.map.set_position(d["lat"], d["lon"], d["heading"])
            self.metrics.text = (
                f'LAT {d["lat"]:.5f}  LON {d["lon"]:.5f}  ALT {d["alt_ft"]:.0f} ft  '
                f'GS {d["speed_kt"]:.0f} kt  HDG {d["heading"]:03.0f}°'
            )
        else:
            self.metrics.text = "LAT --  LON --  ALT -- ft  GS -- kt  HDG ---°"

    def on_stop(self):
        if hasattr(self, "telemetry"):
            self.telemetry.stop()
        if hasattr(self, "map"):
            self.map.close()


if __name__ == "__main__":
    AeroflyATCApp().run()
