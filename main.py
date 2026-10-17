import os
import math
import json
import csv
import shutil
import re
import socket
import ssl
import threading
import time
import urllib.request
from urllib.error import URLError

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
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
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
        # Android's Python/OpenSSL build may not expose the same default trust
        # paths as desktop Python. Try bundled Mozilla roots first, then platform
        # defaults and Android's system CA directory. All contexts keep hostname
        # checking and CERT_REQUIRED enabled.
        self._ssl_contexts = []
        try:
            self._ssl_contexts.append(
                ("Mozilla certifi bundle", ssl.create_default_context(cafile=certifi.where()))
            )
        except Exception:
            pass
        try:
            self._ssl_contexts.append(("Python platform trust", ssl.create_default_context()))
        except Exception:
            pass
        android_ca_dir = "/system/etc/security/cacerts"
        if os.path.isdir(android_ca_dir):
            try:
                android_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                android_ctx.check_hostname = True
                android_ctx.verify_mode = ssl.CERT_REQUIRED
                android_ctx.load_default_certs()
                android_ctx.load_verify_locations(capath=android_ca_dir)
                self._ssl_contexts.append(("Android system CA store", android_ctx))
            except Exception:
                pass
        if not self._ssl_contexts:
            raise RuntimeError("No TLS trust store could be initialized on this device.")
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
        self.route_waypoints = []
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

    def set_route(self, waypoints):
        self.route_waypoints = list(waypoints or [])
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
                last_verify_error = None
                data = None
                for trust_name, trust_context in self._ssl_contexts:
                    try:
                        with urllib.request.urlopen(
                            request, timeout=12, context=trust_context
                        ) as response:
                            if response.status != 200:
                                raise OSError("HTTP " + str(response.status))
                            data = response.read()
                        break
                    except ssl.SSLCertVerificationError as exc:
                        last_verify_error = exc
                    except URLError as exc:
                        # urllib wraps TLS failures in URLError on some Python
                        # builds, including Android's python-for-android runtime.
                        reason = getattr(exc, "reason", None)
                        if (isinstance(reason, ssl.SSLCertVerificationError)
                                or "CERTIFICATE_VERIFY_FAILED" in str(exc)):
                            last_verify_error = exc
                            continue
                        raise
                if data is None:
                    if last_verify_error is not None:
                        raise OSError(
                            "OSM TLS certificate verification failed with bundled, "
                            "platform and Android CA stores: " + str(last_verify_error)
                        )
                    raise OSError("OSM tile download returned no data")
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

            # Draw planned route and waypoint markers using the map tile projection.
            route_pixels = []
            for wp in self.route_waypoints:
                try:
                    wx, wy = self._latlon_to_world(float(wp["lat"]), float(wp["lon"]), z)
                    dx = wx - center_x
                    if dx > world_size / 2:
                        dx -= world_size
                    elif dx < -world_size / 2:
                        dx += world_size
                    route_pixels.append((self.center_x + dx, self.center_y + center_y - wy))
                except (KeyError, TypeError, ValueError):
                    continue
            if len(route_pixels) >= 2:
                Color(0.10, 0.72, 1.0, 0.95)
                Line(points=[v for p in route_pixels for v in p], width=dp(2.2))
            for wx, wy in route_pixels:
                Color(0.02, 0.08, 0.12, 1)
                Ellipse(pos=(wx-dp(8), wy-dp(8)), size=(dp(16), dp(16)))
                Color(0.18, 0.78, 1.0, 1)
                Line(circle=(wx, wy, dp(7)), width=dp(1.5))
                Ellipse(pos=(wx-dp(2), wy-dp(2)), size=(dp(4), dp(4)))

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
                     "rx_bytes": 0, "last_rx_preview": "", "last_rx_time": 0.0,
                     "last_rx_transport": "", "last_rx_source": "",
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

    def _record_rx(self, raw, transport, source):
        """Record the real incoming payload for diagnosis even when parsing fails."""
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        printable = "".join(ch if ch.isprintable() else " " for ch in text)
        preview = re.sub(r"\s+", " ", printable).strip()[:112]
        with self.lock:
            self.data["rx_bytes"] += len(raw)
            self.data["last_rx_preview"] = preview or repr(raw[:40])
            self.data["last_rx_time"] = time.time()
            self.data["last_rx_transport"] = transport
            self.data["last_rx_source"] = str(source)

    def _parse(self, raw, transport, source):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        # Strip NUL padding and tolerate a protocol token after a leading prefix.
        text = text.replace(chr(0), "").replace(chr(0xfeff), "")
        # Aerofly/FSWidgets streams may delimit records with CR, LF, or CRLF.
        for line in re.split(r"[\r\n]+", text):
            line=line.strip()
            if "XGPS" in line and not line.startswith("XGPS"):
                line = line[line.find("XGPS"):]
            elif "XATT" in line and not line.startswith("XATT"):
                line = line[line.find("XATT"):]
            try:
                if line.startswith("XGPS"):
                    p=line[4:].lstrip(" ,:" + chr(9)).split(",")
                    if len(p)<6: continue
                    with self.lock:
                        self.data.update({"sim":p[0].strip(),"lon":float(p[1]),"lat":float(p[2]),
                            "alt_ft":float(p[3])*3.280839895,"heading":float(p[4])%360,
                            "speed_kt":float(p[5])*1.943844492,"connected":True,
                            "transport":transport,"message":"Telemetry received from "+source,
                            "last_packet":time.time(),"packets":self.data["packets"]+1})
                elif line.startswith("XATT"):
                    p=line[4:].lstrip(" ,:" + chr(9)).split(",")
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
                            self._record_rx(raw, "UDP "+str(port), addr[0])
                            self._parse(raw,"UDP "+str(port),addr[0])
                        except socket.timeout: pass
                        except OSError: break
            finally:
                for _,s in opened:
                    try:s.close()
                    except OSError:pass
            time.sleep(.5)

    def _tcp_loop(self):
        """Connect to the simulator, trying alternate local endpoints if one is silent."""
        while self.running:
            requested_host = self.host
            detected = self.detect_local_ip()
            candidates = []
            # Try the configured address first, then loopback and the active interface.
            # A successful TCP handshake alone is not proof that the simulator stream is there.
            for candidate in (requested_host, "127.0.0.1", detected):
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
            connected = False
            errors = []
            for connected_host in candidates:
                if not self.running or requested_host != self.host:
                    break
                s = None
                received_this_attempt = 0
                try:
                    with self.lock:
                        self.data["message"] = f"Probing {connected_host}:{self.TCP_PORT}..."
                    s = socket.create_connection((connected_host, self.TCP_PORT), timeout=3)
                    s.settimeout(1.5)
                    self.tcp = s
                    # Aerofly's FSWidgets service expects the client to speak first.
                    # Keep this wake-up request minimal for compatibility with existing clients.
                    s.sendall(b"GET / HTTP/1.1\r\n\r\n")
                    started = time.time()
                    last_rx = started
                    buf = b""
                    with self.lock:
                        self.data["message"] = f"TCP connected to {connected_host}; waiting for FSWidgets telemetry"
                    while self.running and requested_host == self.host:
                        try:
                            chunk = s.recv(8192)
                            if not chunk:
                                errors.append(f"{connected_host}: server closed stream")
                                break
                            received_this_attempt += len(chunk)
                            last_rx = time.time()
                            self._record_rx(chunk, "TCP 58585", connected_host)
                            buf += chunk
                            # Tolerate CR, LF, and CRLF delimiters.
                            buf = buf.replace(b"\r", b"\n")
                            while b"\n" in buf:
                                line, buf = buf.split(b"\n", 1)
                                self._parse(line, "TCP 58585", connected_host)
                            # Some streams omit a final newline.
                            if buf.startswith((b"XGPS", b"XATT")):
                                fields = buf.count(b",")
                                if ((buf.startswith(b"XGPS") and fields >= 5) or
                                        (buf.startswith(b"XATT") and fields >= 3)):
                                    self._parse(buf, "TCP 58585", connected_host)
                                    buf = b""
                            with self.lock:
                                got_packet = self.data["last_packet"] >= started
                            if got_packet:
                                connected = True
                                # Once telemetry is flowing, keep this socket as the active stream.
                                continue
                            # A TCP handshake can reach the wrong interface/service.
                            # Move on if this endpoint stays silent during the probe window.
                        except socket.timeout:
                            now = time.time()
                            with self.lock:
                                got_packet = self.data["last_packet"] >= started
                                total_rx = self.data["rx_bytes"]
                                preview = self.data["last_rx_preview"]
                            if got_packet:
                                connected = True
                                continue
                            if received_this_attempt == 0 and now - started >= 4.5:
                                errors.append(f"{connected_host}: TCP connected but no bytes arrived")
                                break
                            if received_this_attempt > 0 and now - last_rx >= 4.5:
                                with self.lock:
                                    self.data["connected"] = False
                                    self.data["message"] = (
                                        f"Received {total_rx} bytes from {connected_host}, but no XGPS/XATT record parsed. "
                                        f"Last payload: {preview or '[non-text data]'}"
                                    )
                                # Keep the stream open when bytes arrive: diagnostics need the actual payload.
                    if connected:
                        # If telemetry had arrived, the inner loop remains alive until the socket closes.
                        pass
                except OSError as exc:
                    errors.append(f"{connected_host}: {exc}")
                finally:
                    if s:
                        try:
                            s.close()
                        except OSError:
                            pass
                    if self.tcp is s:
                        self.tcp = None
                if connected:
                    # A live endpoint disconnected; reconnect using the configured order.
                    break
            if not connected and self.running and requested_host == self.host:
                with self.lock:
                    if self.data["last_packet"] and time.time() - self.data["last_packet"] < 5:
                        self.data["connected"] = True
                    else:
                        self.data["connected"] = False
                        detail = "; ".join(errors[-3:]) or "no endpoint responded"
                        self.data["message"] = "No live telemetry stream. " + detail
                time.sleep(1.5)
            else:
                time.sleep(0.5)

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
        self.route_file = os.path.join(self.user_data_dir, "route_waypoints.json")
        self.airports_file = os.path.join(self.user_data_dir, "ourairports_airports.csv")
        self.route_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="airport-lookup")
        self.route_waypoints = self.load_route()
        root = BoxLayout(orientation="vertical", spacing=dp(0), padding=(dp(10), dp(8), dp(10), dp(8)))
        with root.canvas.before:
            Color(*BG)
            self._bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(pos=lambda w, *_: setattr(self._bg_rect, "pos", w.pos),
                  size=lambda w, *_: setattr(self._bg_rect, "size", w.size))

        def card(orientation="vertical", height=None, padding=8, spacing=4):
            panel = BoxLayout(orientation=orientation, padding=dp(padding), spacing=dp(spacing),
                              size_hint_y=None if height else 1,
                              height=dp(height) if height else None)
            with panel.canvas.before:
                Color(*PANEL)
                panel._panel_bg = Rectangle(pos=panel.pos, size=panel.size)
            panel.bind(pos=lambda w, *_: setattr(w._panel_bg, "pos", w.pos),
                       size=lambda w, *_: setattr(w._panel_bg, "size", w.size))
            return panel

        def make_button(title, action, color=PANEL, width=None):
            button = Button(text=title, size_hint_x=None if width else 1,
                            width=dp(width) if width else 1,
                            background_normal="", background_down="",
                            background_color=color, color=TEXT, bold=True, font_size="11sp")
            button.bind(on_press=action)
            return button

        header = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(8))
        brand = BoxLayout(orientation="vertical", spacing=dp(0))
        brand.add_widget(self._label("AEROFLY  /  FLIGHT DECK", "10sp", BLUE, True))
        brand.add_widget(self._label("Live map & flight planning", "16sp", TEXT, True))
        header.add_widget(brand)
        self.state = self._label("NO DATA", "10sp", MUTED, True, "right")
        self.state.size_hint_x = None
        self.state.width = dp(86)
        header.add_widget(self.state)
        root.add_widget(header)

        map_head = BoxLayout(size_hint_y=None, height=dp(30), padding=(dp(4), 0), spacing=dp(6))
        map_head.add_widget(self._label("MOVING MAP", "11sp", TEXT, True))
        map_head.add_widget(self._label("OPENSTREETMAP  •  LIVE POSITION", "9sp", MUTED, False, "right"))
        root.add_widget(map_head)

        self.map = MovingMap(cache_dir=os.path.join(self.user_data_dir, "osm_tiles"))
        self.map.set_route(self.route_waypoints)
        root.add_widget(self.map)

        map_tools = BoxLayout(size_hint_y=None, height=dp(42), padding=(dp(2), dp(4)), spacing=dp(6))
        map_tools.add_widget(make_button("−", lambda *_: self.map.zoom_by(-1), width=38))
        map_tools.add_widget(make_button("RECENTER", lambda *_: self.map.center_plane(), BLUE, width=88))
        map_tools.add_widget(make_button("PLAN ROUTE", self.open_route_planner, width=104))
        map_tools.add_widget(make_button("+", lambda *_: self.map.zoom_by(1), width=38))
        map_tools.add_widget(make_button("RETRY", lambda *_: self.map.retry_tiles(), width=66))
        root.add_widget(map_tools)

        stats = card(orientation="horizontal", height=72, padding=8, spacing=4)
        self.stat_values = {}
        for key, title, value in (
            ("alt", "ALTITUDE", "--- ft"),
            ("gs", "GROUND SPEED", "--- kt"),
            ("hdg", "TRACK / HDG", "---°"),
            ("pos", "POSITION", "Waiting"),
        ):
            item = BoxLayout(orientation="vertical", spacing=dp(2))
            item.add_widget(self._label(title, "8sp", MUTED, True))
            value_label = self._label(value, "12sp", TEXT, True)
            item.add_widget(value_label)
            self.stat_values[key] = value_label
            stats.add_widget(item)
        root.add_widget(stats)

        connection = card(orientation="vertical", height=90, padding=8, spacing=5)
        connection.add_widget(self._label("SIMULATOR CONNECTION", "9sp", BLUE, True))
        row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        self.ip = TextInput(text=self.telemetry.host, hint_text="Simulator device IP address",
                            multiline=False, size_hint_x=0.68,
                            background_normal="", background_active="",
                            background_color=(0.025, 0.04, 0.055, 1), foreground_color=TEXT,
                            cursor_color=BLUE, hint_text_color=MUTED,
                            padding=(dp(10), dp(9)))
        connect = make_button("CONNECT", self.connect, BLUE)
        row.add_widget(self.ip)
        row.add_widget(connect)
        connection.add_widget(row)
        root.add_widget(connection)

        self.status = self._label("TCP 58585  •  Enable “Send flight data to FSWidgets Apps” in Aerofly", "9sp", MUTED)
        self.status.size_hint_y = None
        self.status.height = dp(32)
        self.status.padding = (dp(4), 0)
        root.add_widget(self.status)

        self.rx_debug = self._label("NETWORK DIAGNOSTICS  •  waiting for first payload", "8sp", MUTED)
        self.rx_debug.size_hint_y = None
        self.rx_debug.height = dp(26)
        self.rx_debug.padding = (dp(4), 0)
        root.add_widget(self.rx_debug)

        self.map_note = self._label("Map tiles © OpenStreetMap contributors", "8sp", MUTED)
        self.map_note.size_hint_y = None
        self.map_note.height = dp(18)
        self.map_note.padding = (dp(4), 0)
        root.add_widget(self.map_note)

        Clock.schedule_once(lambda *_: self.telemetry.start(), 0.4)
        Clock.schedule_interval(self.refresh, 0.5)
        return root

    @staticmethod
    def distance_nm(a, b):
        radius_nm = 3440.065
        lat1, lon1 = math.radians(float(a["lat"])), math.radians(float(a["lon"]))
        lat2, lon2 = math.radians(float(b["lat"])), math.radians(float(b["lon"]))
        dlat, dlon = lat2-lat1, lon2-lon1
        h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        return 2 * radius_nm * math.asin(min(1.0, math.sqrt(max(0.0, h))))

    def load_route(self):
        try:
            with open(self.route_file, "r", encoding="utf-8") as handle:
                items = json.load(handle)
            clean = []
            for item in items if isinstance(items, list) else []:
                name = str(item.get("name", "WP"))[:24].strip() or "WP"
                lat, lon = float(item["lat"]), float(item["lon"])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    clean.append({"name": name, "lat": lat, "lon": lon})
            return clean[:40]
        except (OSError, ValueError, TypeError, KeyError):
            return []

    def save_route(self):
        try:
            with open(self.route_file, "w", encoding="utf-8") as handle:
                json.dump(self.route_waypoints, handle, indent=2)
        except OSError as exc:
            if hasattr(self, "route_message"):
                self.route_message.text = "Could not save route: " + str(exc)[:100]

    def route_distance(self):
        return sum(self.distance_nm(a, b) for a, b in zip(self.route_waypoints, self.route_waypoints[1:]))

    def open_route_planner(self, *_):
        body = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        title = self._label("ROUTE PLANNER  /  WAYPOINTS", "14sp", BLUE, True)
        title.size_hint_y = None
        title.height = dp(30)
        body.add_widget(title)
        body.add_widget(self._label("Enter coordinates in decimal degrees. Route lines and waypoint markers appear on the map.", "10sp", MUTED))
        name_input = TextInput(hint_text="Waypoint name (e.g. FIX01 or airport)", text="WP",
                               multiline=False, size_hint_y=None, height=dp(42))
        lat_input = TextInput(hint_text="Latitude (−90 to 90)", multiline=False,
                              input_filter="float", size_hint_y=None, height=dp(42))
        lon_input = TextInput(hint_text="Longitude (−180 to 180)", multiline=False,
                              input_filter="float", size_hint_y=None, height=dp(42))
        body.add_widget(name_input)
        airport_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        airport_input = TextInput(hint_text="Airport ICAO / IATA (e.g. HUEN, EBBR)", multiline=False,
                                  size_hint_x=0.68, padding=(dp(8), dp(9)))
        airport_row.add_widget(airport_input)
        coord_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        coord_row.add_widget(lat_input)
        coord_row.add_widget(lon_input)
        body.add_widget(coord_row)
        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        route_popup = Popup(title="Aerofly ATC • Flight planning", content=body,
                            size_hint=(0.96, 0.88), auto_dismiss=True)

        def refresh_route_view():
            self.map.set_route(self.route_waypoints)
            total = self.route_distance()
            speed = self.telemetry.snapshot().get("speed_kt", 0) or 0
            ete = (total / speed * 60.0) if speed > 1 else None
            summary.text = f"{len(self.route_waypoints)} WAYPOINTS  •  {total:.1f} NM" + (
                f"  •  ETE {int(ete)} min at current GS" if ete is not None else "  •  ETE unavailable until GS > 1 kt"
            )
            lines = []
            for i, wp in enumerate(self.route_waypoints):
                leg = self.distance_nm(self.route_waypoints[i-1], wp) if i else 0.0
                lines.append(f"{i+1:02d}  {wp['name']}   {wp['lat']:.5f}, {wp['lon']:.5f}" +
                             (f"   +{leg:.1f} NM" if i else "   START"))
            listing.text = "\n".join(lines) if lines else "No waypoints yet. Add the first point above."
            self.save_route()

        def lookup_airport(*_):
            code = airport_input.text.strip().upper()
            if not code:
                self.route_message.text = "Enter an airport ICAO or IATA code first."
                return
            self.route_message.text = "Looking up " + code + " in the public-domain OurAirports dataset…"

            def work():
                try:
                    if not os.path.isfile(self.airports_file):
                        request = urllib.request.Request(
                            "https://raw.githubusercontent.com/davidmegginson/ourairports-data/main/airports.csv",
                            headers={"User-Agent": "AeroflyATC/3.1 (+https://github.com/ntambiryan324-ctrl/Air-Traffic-Control-Aerofly-)"},
                        )
                        with urllib.request.urlopen(request, timeout=35) as response:
                            os.makedirs(os.path.dirname(self.airports_file), exist_ok=True)
                            temp = self.airports_file + ".tmp"
                            with open(temp, "wb") as output:
                                shutil.copyfileobj(response, output)
                            os.replace(temp, self.airports_file)
                    found = None
                    with open(self.airports_file, "r", encoding="utf-8-sig", newline="") as handle:
                        for row in csv.DictReader(handle):
                            codes = {
                                (row.get("ident") or "").strip().upper(),
                                (row.get("gps_code") or "").strip().upper(),
                                (row.get("iata_code") or "").strip().upper(),
                            }
                            if code in codes and row.get("latitude_deg") and row.get("longitude_deg"):
                                try:
                                    lat, lon = float(row["latitude_deg"]), float(row["longitude_deg"])
                                except (TypeError, ValueError):
                                    continue
                                if -90 <= lat <= 90 and -180 <= lon <= 180:
                                    found = {"name": (row.get("name") or code)[:24], "lat": lat, "lon": lon}
                                    break
                    def finish(_dt):
                        if found:
                            name_input.text = found["name"]
                            lat_input.text, lon_input.text = str(found["lat"]), str(found["lon"])
                            self.route_message.text = (
                                f'Found {code}: {found["name"]}. Review coordinates, then press ADD WAYPOINT. '
                                "Data: OurAirports (public domain; accuracy not guaranteed)."
                            )
                        else:
                            self.route_message.text = f"No airport found for {code}. Try its ICAO/IATA code or enter coordinates."
                    Clock.schedule_once(finish, 0)
                except Exception as exc:
                    message = str(exc)[:120]
                    Clock.schedule_once(lambda _dt, msg=message: setattr(
                        self.route_message, "text", "Airport lookup failed: " + msg
                    ), 0)
            self.route_workers.submit(work)

        def add_waypoint(*_):
            try:
                name = name_input.text.strip()[:24] or f"WP{len(self.route_waypoints)+1:02d}"
                lat, lon = float(lat_input.text), float(lon_input.text)
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("Coordinates are outside valid latitude/longitude ranges.")
                if len(self.route_waypoints) >= 40:
                    raise ValueError("Limit is 40 waypoints per route.")
                self.route_waypoints.append({"name": name, "lat": lat, "lon": lon})
                name_input.text, lat_input.text, lon_input.text = f"WP{len(self.route_waypoints)+1:02d}", "", ""
                refresh_route_view()
                self.route_message.text = "Waypoint added and saved locally."
            except ValueError as exc:
                self.route_message.text = str(exc)

        def add_aircraft_position(*_):
            d = self.telemetry.snapshot()
            if d.get("lat") is None or d.get("lon") is None:
                self.route_message.text = "No live aircraft coordinates yet; enter coordinates manually."
                return
            self.route_waypoints.append({"name": f"POS{len(self.route_waypoints)+1:02d}",
                                         "lat": float(d["lat"]), "lon": float(d["lon"])})
            refresh_route_view()
            self.route_message.text = "Current aircraft position added as a waypoint."

        def undo_waypoint(*_):
            if self.route_waypoints:
                self.route_waypoints.pop()
                refresh_route_view()
                self.route_message.text = "Last waypoint removed."

        def clear_route(*_):
            self.route_waypoints = []
            refresh_route_view()
            self.route_message.text = "Route cleared."

        def export_gpx(*_):
            try:
                path = os.path.join(self.user_data_dir, "aerofly_route.gpx")
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                    handle.write('<gpx version="1.1" creator="Aerofly ATC" xmlns="http://www.topografix.com/GPX/1/1">\n')
                    for wp in self.route_waypoints:
                        safe_name = wp["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        handle.write(f'  <wpt lat="{wp["lat"]:.7f}" lon="{wp["lon"]:.7f}"><name>{safe_name}</name></wpt>\n')
                    handle.write('</gpx>\n')
                self.route_message.text = "GPX exported to app storage: " + path
            except OSError as exc:
                self.route_message.text = "GPX export failed: " + str(exc)[:100]

        airport_row.add_widget(make_button("FIND AIRPORT", lookup_airport, BLUE))
        body.add_widget(airport_row)
        actions.add_widget(make_button("ADD WAYPOINT", add_waypoint, BLUE))
        actions.add_widget(make_button("ADD LIVE POS", add_aircraft_position))
        body.add_widget(actions)
        summary = self._label("", "10sp", GREEN, True)
        summary.size_hint_y = None
        summary.height = dp(30)
        body.add_widget(summary)
        scroll = ScrollView(size_hint=(1, 1))
        listing = self._label("", "10sp", TEXT)
        listing.halign = "left"
        listing.valign = "top"
        listing.shorten = False
        listing.size_hint_y = None
        listing.bind(width=lambda obj, width: setattr(obj, "text_size", (width, None)),
                     texture_size=lambda obj, size: setattr(obj, "height", size[1] + dp(16)))
        scroll.add_widget(listing)
        body.add_widget(scroll)
        self.route_message = self._label("Routes are saved on this device. GPX is a portable waypoint format, not an Aerofly mission file.", "9sp", MUTED)
        self.route_message.size_hint_y = None
        self.route_message.height = dp(38)
        body.add_widget(self.route_message)
        bottom = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        bottom.add_widget(make_button("UNDO LAST", undo_waypoint))
        bottom.add_widget(make_button("CLEAR ROUTE", clear_route))
        bottom.add_widget(make_button("EXPORT GPX", export_gpx, BLUE))
        body.add_widget(bottom)
        refresh_route_view()
        route_popup.open()

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
        live = d["connected"] and d["lat"] is not None
        self.state.text = "LIVE" if live else ("TCP LINK" if d["rx_bytes"] else "NO DATA")
        self.state.color = GREEN if live else (BLUE if d["rx_bytes"] else MUTED)
        self.status.text = d["message"] + "  |  " + d["transport"] + "  |  records " + str(d["packets"])
        preview = d["last_rx_preview"] or "no payload received yet"
        self.rx_debug.text = (
            f'RX {d["rx_bytes"]} bytes  •  {d["last_rx_transport"] or "no source"}  •  {preview}'
        )
        if self.map.tile_errors and not self.map.tiles:
            detail = (self.map.last_tile_error or "network unavailable").replace("\n", " ")[:90]
            self.map_note.text = "MAP ERROR  •  " + detail + "  •  © OpenStreetMap"
        elif not self.map.tiles:
            self.map_note.text = "Loading map tiles…  •  © OpenStreetMap contributors"
        elif d["lat"] is None:
            self.map_note.text = "MAP READY  •  Waiting for valid aircraft coordinates"
        else:
            self.map_note.text = "LIVE AIRCRAFT POSITION  •  © OpenStreetMap contributors"
        if d["lat"] is not None and d["lon"] is not None:
            self.map.set_position(d["lat"], d["lon"], d["heading"])
            self.stat_values["alt"].text = f'{d["alt_ft"]:.0f} ft'
            self.stat_values["gs"].text = f'{d["speed_kt"]:.0f} kt'
            self.stat_values["hdg"].text = f'{d["heading"]:03.0f}°'
            self.stat_values["pos"].text = f'{d["lat"]:.2f}, {d["lon"]:.2f}'
        else:
            self.stat_values["alt"].text = "--- ft"
            self.stat_values["gs"].text = "--- kt"
            self.stat_values["hdg"].text = "---°"
            self.stat_values["pos"].text = "Waiting"

    def on_stop(self):
        if hasattr(self, "telemetry"):
            self.telemetry.stop()
        if hasattr(self, "route_workers"):
            self.route_workers.shutdown(wait=False, cancel_futures=True)
        if hasattr(self, "map"):
            self.map.close()


if __name__ == "__main__":
    AeroflyATCApp().run()
