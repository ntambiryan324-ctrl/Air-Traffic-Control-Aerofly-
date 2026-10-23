"""Aerofly ATC minimal telemetry + OSM test build. Kept deliberately dependency-light."""
import math
import os
import re
import socket
import threading
import time
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, Ellipse, RoundedRectangle, Rectangle
from kivy.metrics import dp
from kivy.network.urlrequest import UrlRequest
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.utils import platform

BG = (0.025, 0.045, 0.075, 1)
GLASS = (0.075, 0.12, 0.18, 0.82)
GLASS_EDGE = (0.55, 0.78, 0.95, 0.30)
INK = (0.92, 0.97, 1, 1)
MUTED = (0.60, 0.72, 0.82, 1)
CYAN = (0.18, 0.90, 0.94, 1)
GREEN = (0.25, 0.96, 0.64, 1)
AMBER = (1.0, 0.70, 0.24, 1)

class GlassPanel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*GLASS)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(18)])
            Color(*GLASS_EDGE)
            self._edge = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(18)), width=1)
        self.bind(pos=self._sync, size=self._sync)
    def _sync(self, *_):
        self._bg.pos, self._bg.size = self.pos, self.size
        self._edge.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(18))

class OSMMap(Widget):
    """Small draggable OSM tile map. Tile loading is asynchronous and cached in-memory."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lat, self.lon, self.heading = 0.0, 0.0, 0.0
        self.has_fix = False
        self.center_lat, self.center_lon = 0.0, 0.0
        self.zoom = 4
        self.tiles = {}
        self.pending = set()
        self._touch = None
        self._touch_start = None
        self._touch_prev = None
        self._touch_moved = False
        self.tap_callback = None
        self.pan_callback = None
        self.base_layer = "chart"
        self.bind(pos=self.redraw, size=self.redraw)
        Clock.schedule_once(lambda *_: self.load_tiles(), 0.5)
    def set_fix(self, lat, lon, heading, follow=True):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): return
        was_fixed = self.has_fix
        self.lat, self.lon, self.heading, self.has_fix = lat, lon, heading, True
        if (not was_fixed) or follow:
            moved = abs(self.center_lat - lat) > 0.008 or abs(self.center_lon - lon) > 0.008
            self.center_lat, self.center_lon = lat, lon
            if moved or not was_fixed:
                self.load_tiles()
        self.redraw()
    def set_layer(self, layer):
        layer = layer if layer in ("chart", "terrain", "satellite") else "chart"
        if layer == self.base_layer: return
        self.base_layer = layer
        self.tiles = {}
        self.pending = set()
        self.load_tiles()
        self.redraw()
    def world(self, lat, lon):
        n = 2 ** self.zoom
        lat = max(-85.0511, min(85.0511, lat))
        x = (lon + 180.0) / 360.0 * n
        rad = math.radians(lat)
        y = (1 - math.asinh(math.tan(rad)) / math.pi) / 2 * n
        return x, y
    def geo(self, x, y):
        n = 2 ** self.zoom
        lon = x / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2*y/n))))
        return lat, lon
    def load_tiles(self):
        if self.width < 10 or self.height < 10: return
        cx, cy = self.world(self.center_lat, self.center_lon)
        size = dp(256)
        nx, ny = int(self.width / size) + 3, int(self.height / size) + 3
        self.origin = (cx - nx/2, cy - ny/2)
        n = 2 ** self.zoom
        for ix in range(nx):
            for iy in range(ny):
                tx, ty = int(self.origin[0] + ix), int(self.origin[1] + iy)
                tx %= n
                if ty < 0 or ty >= n: continue
                key = (self.base_layer, self.zoom, tx, ty)
                if key in self.tiles or key in self.pending: continue
                self.pending.add(key)
                layer, z, x, y = key
                if layer == "satellite":
                    url = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/%d/%d/%d" % (z, y, x)
                elif layer == "terrain":
                    shard = ("a", "b", "c")[(x + y) % 3]
                    url = "https://%s.tile.opentopomap.org/%d/%d/%d.png" % (shard, z, x, y)
                else:
                    url = "https://tile.openstreetmap.org/%d/%d/%d.png" % (z, x, y)
                UrlRequest(url, on_success=lambda req, result, k=key: self.tile_ok(k, result),
                           on_failure=lambda req, err, k=key: self.tile_fail(k),
                           on_error=lambda req, err, k=key: self.tile_fail(k),
                           req_headers={"User-Agent":"AeroflyATC-Android/1.0 (map and flight planning)"}, timeout=12)
    def tile_ok(self, key, data):
        self.pending.discard(key)
        try: self.tiles[key] = CoreImage(BytesIO(data), ext="png").texture
        except Exception: pass
        self.redraw()
    def tile_fail(self, key):
        self.pending.discard(key)
        self.redraw()
    def redraw(self, *_):
        self.canvas.clear()
        if self.width < 2 or self.height < 2: return
        with self.canvas:
            Color(0.035, 0.055, 0.075, 1)
            Rectangle(pos=self.pos, size=self.size)
            size = dp(256)
            cx, cy = self.world(self.center_lat, self.center_lon)
            left, bottom = cx - self.width/(2*size), cy - self.height/(2*size)
            n = 2 ** self.zoom
            for key, tex in list(self.tiles.items()):
                layer, z, tx, ty = key
                if layer != self.base_layer or z != self.zoom: continue
                dx = (tx - cx + n/2) % n - n/2
                x = self.center_x + dx*size
                y = self.center_y + (cy - ty)*size
                if x+size < self.x or x > self.right or y+size < self.y or y > self.top: continue
                Color(1,1,1,1); Rectangle(texture=tex, pos=(x-size/2, y-size/2), size=(size,size))
            if self.has_fix:
                px, py = self.world(self.lat, self.lon)
                dx = (px-cx+n/2)%n-n/2
                x, y = self.center_x+dx*size, self.center_y+(cy-py)*size
                Color(0.02,0.16,0.18,0.8); Ellipse(pos=(x-dp(13),y-dp(13)),size=(dp(26),dp(26)))
                Color(*GREEN); Ellipse(pos=(x-dp(5),y-dp(5)),size=(dp(10),dp(10)))
                h=math.radians(self.heading)
                Line(points=[x,y,x+math.sin(h)*dp(24),y+math.cos(h)*dp(24)],width=dp(2))
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touch = touch.pos
            self._touch_start = touch.pos
            self._touch_prev = touch.pos
            self._touch_moved = False
            return True
        return super().on_touch_down(touch)
    def on_touch_move(self, touch):
        if self._touch is not None:
            px, py = self._touch_prev
            sx, sy = self._touch_start
            dx_total, dy_total = touch.x - sx, touch.y - sy
            if math.hypot(dx_total, dy_total) > dp(8) and not self._touch_moved:
                self._touch_moved = True
                if callable(self.pan_callback):
                    self.pan_callback()
            dx, dy = touch.x - px, touch.y - py
            size = dp(256)
            cx, cy = self.world(self.center_lat, self.center_lon)
            lat1, lon1 = self.geo(cx - dx / size, cy + dy / size)
            self.center_lat = max(-85, min(85, lat1))
            self.center_lon = ((lon1 + 180) % 360) - 180
            self._touch_prev = touch.pos
            self._touch = touch.pos
            self.load_tiles()
            self.redraw()
            return True
        return super().on_touch_move(touch)
    def on_touch_up(self, touch):
        if self._touch is not None:
            start = self._touch_start
            if not self._touch_moved and start is not None and callable(self.tap_callback):
                cx, cy = self.world(self.center_lat, self.center_lon)
                lat, lon = self.geo(cx + (touch.x - self.center_x) / dp(256),
                                    cy - (touch.y - self.center_y) / dp(256))
                self.tap_callback(lat, lon)
            self._touch = None
            self._touch_start = None
            self._touch_prev = None
            self._touch_moved = False
            return True
        return super().on_touch_up(touch)

class Telemetry:
    TCP_PORT=58585
    UDP_PORTS=(49002,40092)
    def __init__(self):
        self.host=""
        self.running=False
        self.lock=threading.RLock()
        self.sock=None
        self.data={"connected":False,"transport":"WAITING","lat":None,"lon":None,"alt":0.0,
                   "speed":0.0,"heading":0.0,"packets":0,"message":"Enter simulator IP and tap CONNECT","last":0}
    def start(self):
        if self.running: return
        self.running=True
        threading.Thread(target=self.udp_loop,daemon=True).start()
        threading.Thread(target=self.tcp_loop,daemon=True).start()
    def stop(self):
        self.running=False
        try:
            if self.sock: self.sock.close()
        except OSError: pass
    def parse(self, raw, transport, source):
        txt=raw.decode("utf-8","replace") if isinstance(raw,bytes) else str(raw)
        for line in re.split(r"[\r\n]+",txt):
            line=line.strip()
            try:
                if line.startswith("XGPS"):
                    p=line[4:].strip().split(",")
                    if len(p)<6: continue
                    update={"sim":p[0].strip(),"lon":float(p[1]),"lat":float(p[2]),
                            "alt":float(p[3])*3.280839895,"heading":float(p[4])%360,
                            "speed":float(p[5])*1.943844492}
                elif line.startswith("XATT"):
                    p=line[4:].strip().split(",")
                    if len(p)<4: continue
                    update={"sim":p[0].strip(),"heading":float(p[1])%360}
                else: continue
                with self.lock:
                    self.data.update(update,connected=True,transport=transport,
                        message="Telemetry received via %s from %s"%(transport,source),
                        packets=self.data["packets"]+1,last=time.time())
            except (ValueError,IndexError): pass
    def udp_loop(self):
        while self.running:
            sockets=[]
            for port in self.UDP_PORTS:
                try:
                    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
                    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    s.bind(("0.0.0.0",port)); s.settimeout(.5); sockets.append((port,s))
                except OSError:
                    try: s.close()
                    except Exception: pass
            if not sockets:
                with self.lock: self.data["message"]="Could not bind UDP 49002/40092; retrying"
                time.sleep(2); continue
            while self.running:
                for port,s in sockets:
                    try:
                        raw,addr=s.recvfrom(65535); self.parse(raw,"UDP "+str(port),addr[0])
                    except socket.timeout: pass
                    except OSError: break
            for _,s in sockets:
                try:s.close()
                except OSError:pass
    def tcp_loop(self):
        while self.running:
            host=self.host.strip()
            if not host:
                time.sleep(1); continue
            s=None
            try:
                s=socket.create_connection((host,self.TCP_PORT),timeout=4); s.settimeout(2); self.sock=s
                with self.lock:self.data["message"]="TCP connected to %s:%d; waiting for FSWidgets data"%(host,self.TCP_PORT)
                buf=b""
                while self.running and host==self.host:
                    try:
                        chunk=s.recv(8192)
                        if not chunk:break
                        buf+=chunk.replace(b"\r",b"\n")
                        while b"\n" in buf:
                            line,buf=buf.split(b"\n",1); self.parse(line,"TCP 58585",host)
                        if buf.startswith((b"XGPS",b"XATT")) and buf.count(b",")>=5:
                            self.parse(buf,"TCP 58585",host);buf=b""
                    except socket.timeout: pass
            except OSError as e:
                with self.lock:
                    if not self.data["connected"]: self.data["message"]="TCP 58585: %s; UDP listeners remain active"%e
            finally:
                try:
                    if s:s.close()
                except OSError:pass
                self.sock=None
            time.sleep(1)
    def snapshot(self):
        with self.lock:d=dict(self.data)
        if time.time()-d["last"]>5:d["connected"]=False
        return d

class AeroflyATCApp(App):
    title = "Aerofly ATC"

    def build(self):
        self.telemetry = Telemetry()
        self.follow_map = True
        self.map = OSMMap()
        from reference_ui import ReferenceUI
        self.reference_ui = ReferenceUI(self)
        self.telemetry.start()
        Clock.schedule_interval(self.refresh, 0.5)
        Clock.schedule_once(lambda *_: self.map.load_tiles(), 1.0)
        return self.reference_ui.root

    def refresh(self, *_):
        data = self.telemetry.snapshot()
        if data.get("lat") is not None and data.get("lon") is not None:
            self.map.set_fix(data["lat"], data["lon"], data.get("heading", 0),
                             follow=self.follow_map)
        if hasattr(self, "reference_ui"):
            self.reference_ui.refresh_telemetry(data)

    def on_stop(self):
        if hasattr(self, "telemetry"):
            self.telemetry.stop()


if __name__=="__main__":
    AeroflyATCApp().run()
