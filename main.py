import os
import math
import socket
import threading
import time
import urllib.request
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, Ellipse, Triangle, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
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


class MovingMap(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lat, self.lon, self.heading = 0.3476, 32.5825, 0.0
        self.zoom = 11
        self.follow = True
        self.tiles = {}
        self.loading = set()
        self.bind(pos=lambda *_: self.redraw(), size=lambda *_: self.redraw())
        Clock.schedule_once(lambda *_: self.load_tiles(), 0.5)

    def set_position(self, lat, lon, heading):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return
        moved = abs(self.lat-lat) > 0.001 or abs(self.lon-lon) > 0.001
        self.lat, self.lon, self.heading = lat, lon, heading
        if self.follow and moved:
            self.load_tiles()
        self.redraw()

    def pan(self, dx, dy):
        self.follow = False
        scale = 360.0 / (256 * (2 ** self.zoom))
        self.lon -= dx * scale
        self.lat += dy * scale * max(0.15, math.cos(math.radians(self.lat)))
        self.load_tiles()
        self.redraw()

    def zoom_by(self, amount):
        self.zoom = max(3, min(17, self.zoom + amount))
        self.load_tiles()
        self.redraw()

    def center_plane(self):
        self.follow = True
        self.load_tiles()
        self.redraw()

    def load_tiles(self):
        if self.width <= 1 or self.height <= 1:
            return
        cx, cy = tile_xy(self.lat, self.lon, self.zoom)
        cols = max(2, int(self.width / 256) + 3)
        rows = max(2, int(self.height / 256) + 3)
        ix, iy = int(cx), int(cy)
        wanted = []
        for tx in range(ix-cols//2, ix+cols//2+1):
            for ty in range(iy-rows//2, iy+rows//2+1):
                n = 2 ** self.zoom
                if 0 <= ty < n:
                    key = (self.zoom, tx % n, ty)
                    if key not in self.tiles and key not in self.loading:
                        wanted.append(key)
        for key in wanted[:16]:
            self.loading.add(key)
            threading.Thread(target=self._fetch_tile, args=(key,), daemon=True).start()
        self.redraw()

    def _fetch_tile(self, key):
        z, x, y = key
        try:
            req = urllib.request.Request(
                f"https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                headers={"User-Agent": "AeroflyTelemetryMap/1.0 (Android)"})
            with urllib.request.urlopen(req, timeout=8) as response:
                raw = response.read()
            texture = CoreImage(BytesIO(raw), ext="png").texture
            Clock.schedule_once(lambda dt, k=key, t=texture: self._tile_ready(k, t), 0)
        except Exception:
            Clock.schedule_once(lambda dt, k=key: self.loading.discard(k), 0)

    def _tile_ready(self, key, texture):
        self.loading.discard(key)
        self.tiles[key] = texture
        if len(self.tiles) > 180:
            self.tiles = dict(list(self.tiles.items())[-120:])
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        if self.width <= 1 or self.height <= 1:
            return
        with self.canvas:
            Color(0.86, 0.88, 0.84, 1)
            Rectangle(pos=self.pos, size=self.size)
            cx, cy = tile_xy(self.lat, self.lon, self.zoom)
            center_px_x, center_px_y = cx*256, cy*256
            left = self.x + self.width/2 - center_px_x
            bottom = self.y + self.height/2 - (256-center_px_y % 256) - (int(cy)*256-center_px_y)
            n = 2 ** self.zoom
            cols = int(self.width/256)+3
            rows = int(self.height/256)+3
            for tx in range(int(cx)-cols//2, int(cx)+cols//2+1):
                for ty in range(int(cy)-rows//2, int(cy)+rows//2+1):
                    if not (0 <= ty < n):
                        continue
                    key=(self.zoom, tx % n, ty)
                    px=self.x+self.width/2 + (tx-cx)*256
                    py=self.y+self.height/2 - (ty-cy)*256 - 256
                    texture=self.tiles.get(key)
                    if texture is not None:
                        Color(1,1,1,1)
                        Rectangle(texture=texture, pos=(px,py), size=(256,256))
                    else:
                        Color(0.80,0.83,0.79,1)
                        Rectangle(pos=(px,py),size=(256,256))
            Color(0.1,0.2,0.2,0.25)
            Line(rectangle=(self.x,self.y,self.width,self.height),width=1)
            # Aircraft stays at map centre in follow mode; heading rotates the nose.
            px, py = self.x+self.width/2, self.y+self.height/2
            angle=math.radians(self.heading)
            forward=(math.sin(angle), math.cos(angle))
            right=(math.cos(angle), -math.sin(angle))
            tip=(px+forward[0]*dp(18),py+forward[1]*dp(18))
            tail=(px-forward[0]*dp(12),py-forward[1]*dp(12))
            leftp=(px+right[0]*dp(8),py+right[1]*dp(8))
            rightp=(px-right[0]*dp(8),py-right[1]*dp(8))
            Color(0.02,0.12,0.22,1)
            Triangle(points=[tip[0],tip[1],leftp[0],leftp[1],tail[0],tail[1]])
            Triangle(points=[tip[0],tip[1],rightp[0],rightp[1],tail[0],tail[1]])
            Color(0.1,0.72,1,1)
            Line(points=[tip[0],tip[1],leftp[0],leftp[1],tail[0],tail[1],rightp[0],rightp[1],tip[0],tip[1]],width=1.4)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._drag_last = touch.pos
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if getattr(self, "_drag_last", None) and self.collide_point(*touch.pos):
            oldx, oldy = self._drag_last
            self.pan(touch.x-oldx, touch.y-oldy)
            self._drag_last = touch.pos
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._drag_last = None
        return super().on_touch_up(touch)


class Telemetry:
    TCP_PORT = 58585
    UDP_PORTS = (49002, 40092)

    def __init__(self):
        self.host = "127.0.0.1"
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
        for line in text.replace("\r", "").split("\n"):
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
            try:
                host=self.host
                with self.lock: self.data["message"]=f"Connecting to {host}:{self.TCP_PORT}..."
                s=socket.create_connection((host,self.TCP_PORT),timeout=4)
                s.settimeout(2)
                self.tcp=s
                s.sendall(b"GET / HTTP/1.1\r\nHost: aerofly\r\nConnection: keep-alive\r\n\r\n")
                with self.lock: self.data["message"]="TCP connected; waiting for XGPS/XATT telemetry"
                buf=b""
                while self.running and host==self.host:
                    try:
                        chunk=s.recv(8192)
                        if not chunk: break
                        buf+=chunk
                        while b"\n" in buf:
                            line,buf=buf.split(b"\n",1)
                            self._parse(line,"TCP 58585",host)
                    except socket.timeout:
                        if time.time()-self.data["last_packet"]>5:
                            with self.lock:self.data["connected"]=False
            except OSError as e:
                with self.lock:
                    self.data["connected"]=False
                    self.data["message"]=f"TCP {self.TCP_PORT}: {e}"
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


class TelemetryApp(App):
    title = "Aerofly Telemetry Map"

    def build(self):
        self.telemetry=Telemetry()
        root=BoxLayout(orientation="vertical", spacing=dp(5), padding=dp(6))
        root.canvas.before.add(Color(*BG))
        root.canvas.before.add(Rectangle(pos=root.pos,size=root.size))
        root.bind(pos=lambda w,_:setattr(w.canvas.before.children[0],"rgba",BG))
        head=BoxLayout(size_hint_y=None,height=dp(42),spacing=dp(5))
        head.add_widget(Label(text="AEROFLY TELEMETRY",bold=True,color=TEXT,font_size="17sp",halign="left"))
        self.state=Label(text="WAITING",color=MUTED,size_hint_x=None,width=dp(110),font_size="12sp")
        head.add_widget(self.state);root.add_widget(head)
        conn=BoxLayout(size_hint_y=None,height=dp(46),spacing=dp(4))
        self.ip=TextInput(text="127.0.0.1",hint_text="Aerofly device IPv4",multiline=False,
                          size_hint_x=0.62,background_color=PANEL,foreground_color=TEXT,
                          cursor_color=TEXT)
        conn.add_widget(self.ip)
        b=Button(text="CONNECT / RETRY",size_hint_x=0.38,background_normal="",background_color=BLUE,color=TEXT)
        b.bind(on_press=self.connect);conn.add_widget(b);root.add_widget(conn)
        self.map=MovingMap(size_hint_y=0.72)
        root.add_widget(self.map)
        controls=BoxLayout(size_hint_y=None,height=dp(42),spacing=dp(4))
        for label,fn in (("−",lambda *_:self.map.zoom_by(-1)),("+",lambda *_:self.map.zoom_by(1)),
                         ("FOLLOW",lambda *_:self.map.center_plane())):
            b=Button(text=label,background_normal="",background_color=PANEL,color=TEXT)
            b.bind(on_press=fn);controls.add_widget(b)
        root.add_widget(controls)
        self.status=Label(text="Starting listeners: TCP 58585 • UDP 49002 / 40092",
                          color=MUTED,size_hint_y=None,height=dp(30),font_size="10sp")
        root.add_widget(self.status)
        self.metrics=Label(text="LAT --  LON --  ALT -- ft  GS -- kt  HDG ---°",
                           color=TEXT,size_hint_y=None,height=dp(28),font_size="11sp")
        root.add_widget(self.metrics)
        Clock.schedule_once(lambda *_:self.telemetry.start(),.3)
        Clock.schedule_interval(self.refresh,.5)
        return root

    def connect(self,*_):
        self.telemetry.set_host(self.ip.text)
        with self.telemetry.lock:
            self.telemetry.data["message"]=f"Trying TCP {self.ip.text.strip()}:{self.telemetry.TCP_PORT}; UDP listeners active"
        if not self.telemetry.running:self.telemetry.start()

    def refresh(self,*_):
        d=self.telemetry.snapshot()
        self.state.text="CONNECTED" if d["connected"] else "WAITING"
        self.state.color=GREEN if d["connected"] else MUTED
        self.status.text=d["message"]+"  |  "+d["transport"]+"  |  packets "+str(d["packets"])
        if d["lat"] is not None and d["lon"] is not None:
            self.map.set_position(d["lat"],d["lon"],d["heading"])
            self.metrics.text=f'LAT {d["lat"]:.5f}  LON {d["lon"]:.5f}  ALT {d["alt_ft"]:.0f} ft  GS {d["speed_kt"]:.0f} kt  HDG {d["heading"]:03.0f}°'
        else:
            self.metrics.text="LAT --  LON --  ALT -- ft  GS -- kt  HDG ---°"

    def on_stop(self):
        if hasattr(self,"telemetry"):self.telemetry.stop()


if __name__ == "__main__":
    TelemetryApp().run()
