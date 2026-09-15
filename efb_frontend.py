import os, json, time, threading, urllib.request, urllib.parse
from kivymd.app import MDApp
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line, Ellipse, Triangle
from kivy.metrics import dp
from kivy.properties import StringProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.widget import Widget
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
import advanced_features as adv

try:
    from __main__ import Telemetry
except Exception:
    Telemetry = None

BG=(0.051,0.051,0.051,1); PANEL=(0.102,0.102,0.102,1); PANEL2=(0.145,0.145,0.145,1)
AMBER=(1,0.694,0,1); WHITE=(1,1,1,1); MUTED=(0.50,0.50,0.50,1)
GREEN=(0.30,0.90,0.52,1); BLUE=(0.20,0.65,1,1); RED=(1,0.25,0.25,1)

KV = r"""
<ThemedButton@Button>:
    background_normal: ""
    background_down: ""
    background_color: (1,0.694,0,1) if root.active else (0.145,0.145,0.145,1)
    color: (0.05,0.05,0.05,1) if root.active else (1,1,1,1)
    font_size: "10sp"
    bold: root.active
<ThemedInput@TextInput>:
    background_color: 0.102,0.102,0.102,1
    foreground_color: 1,1,1,1
    hint_text_color: 0.40,0.40,0.40,1
    cursor_color: 1,0.694,0,1
    padding: dp(10),dp(10)
"""
Builder.load_string(KV)

class ThemedButton(Button):
    active=BooleanProperty(False)
class ThemedInput(TextInput):
    pass

def bg(widget,color=BG,radius=10):
    with widget.canvas.before:
        Color(*color); widget._rect=RoundedRectangle(pos=widget.pos,size=widget.size,radius=[dp(radius)])
    widget.bind(pos=lambda *_:setattr(widget._rect,"pos",widget.pos),size=lambda *_:setattr(widget._rect,"size",widget.size))
    return widget

def label(text,size=11,color=WHITE,bold=False,**kw):
    return Label(text=text,color=color,font_size=f"{size}sp",bold=bold,**kw)

class TopBar(BoxLayout):
    def __init__(self,title,app,**kw):
        super().__init__(orientation="horizontal",size_hint_y=None,height=dp(55),padding=(dp(10),dp(5)),spacing=dp(5),**kw)
        self.add_widget(label(title,20,WHITE,True))
        self.add_widget(Widget())
        b=ThemedButton(text="⚙",active=False,size_hint_x=None,width=dp(45))
        b.font_size="21sp";b.bind(on_release=lambda *_:app.show_settings());self.add_widget(b)

class NavBar(BoxLayout):
    def __init__(self,app,**kw):
        super().__init__(size_hint_y=None,height=dp(70),padding=(dp(3),dp(4)),spacing=dp(2),**kw)
        for tab,icon,name in (("home","⌗","Home"),("flight","✈","My Flight"),("comms","◉","Comms"),("scratch","✎","Scratchpad"),("airports","⌖","Airports")):
            box=BoxLayout(orientation="vertical")
            b=Button(text=icon,background_normal="",background_color=BG,color=AMBER if app.tab==tab else MUTED,font_size="22sp",size_hint_y=None,height=dp(43))
            l=label(name,8,AMBER if app.tab==tab else MUTED);l.size_hint_y=None;l.height=dp(18)
            b.bind(on_release=lambda _,t=tab:app.switch_tab(t));box.add_widget(b);box.add_widget(l);self.add_widget(box)
        with self.canvas.before: Color(0.075,0.075,0.075,1); self.r=Rectangle(pos=self.pos,size=self.size)
        self.bind(pos=lambda *_:setattr(self.r,"pos",self.pos),size=lambda *_:setattr(self.r,"size",self.size))

class TelemetryHUD(BoxLayout):
    def __init__(self,**kw):
        super().__init__(size_hint_y=None,height=dp(64),padding=dp(3),spacing=dp(1),**kw);self.cells={}
        for title in ("ORIGIN","DEST","TAS","ALT","HDG","ETE","TOD"):
            c=BoxLayout(orientation="vertical");c.add_widget(label(title,7,MUTED));v=label("---",10,WHITE,True);c.add_widget(v);self.cells[title]=v;self.add_widget(c)
        with self.canvas.before:Color(0.06,0.06,0.06,0.98);self.r=Rectangle(pos=self.pos,size=self.size)
        self.bind(pos=lambda *_:setattr(self.r,"pos",self.pos),size=lambda *_:setattr(self.r,"size",self.size))
    def update(self,d):
        self.cells["TAS"].text=f'{d.get("speed",0):.0f} KT';self.cells["ALT"].text=f'{d.get("altitude",0):05.0f}';self.cells["HDG"].text=f'{d.get("heading",0):03.0f}'

class FlightMap(Widget):
    def __init__(self,**kw):
        super().__init__(**kw);self.data={};self.trail=[];self.route=[];self.zoom=1.0;self.cx=0;self.cy=0;self.drag=None
        self.bind(pos=lambda *_:self.redraw(),size=lambda *_:self.redraw())
    def update(self,d,trail,route):self.data=dict(d);self.trail=trail[-400:];self.route=route;self.redraw()
    def project(self,lat,lon):
        scale=dp(120)*self.zoom;lat0=self.data.get("lat",self.cy) if self.data.get("connected") else self.cy;lon0=self.data.get("lon",self.cx) if self.data.get("connected") else self.cx
        return self.center_x+(lon-lon0)*scale,self.center_y+(lat-lat0)*scale
    def on_touch_down(self,t):
        if self.collide_point(*t.pos):self.drag=t.pos;return True
        return super().on_touch_down(t)
    def on_touch_move(self,t):
        if self.drag:
            dx=t.x-self.drag[0];dy=t.y-self.drag[1];self.drag=t.pos;s=dp(120)*self.zoom;self.cx-=dx/s;self.cy-=dy/s;self.redraw();return True
        return super().on_touch_move(t)
    def on_touch_up(self,t):self.drag=None;return True
    def center_aircraft(self):
        if self.data.get("connected"):self.cx=self.data["lon"];self.cy=self.data["lat"];self.redraw()
    def zoom_by(self,n):self.zoom=max(.25,min(8,self.zoom*n));self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(0.025,0.045,0.060,1);Rectangle(pos=self.pos,size=self.size)
            Color(0.12,0.17,0.18,0.5)
            step=dp(55);x=self.x
            while x<self.right:Line(points=[x,self.y,x,self.top],width=.6);x+=step
            y=self.y
            while y<self.top:Line(points=[self.x,y,self.right,y],width=.6);y+=step
            if len(self.trail)>1:
                Color(*BLUE);pts=[]
                for p in self.trail:q=self.project(*p);pts += [q[0],q[1]]
                Line(points=pts,width=dp(2))
            if len(self.route)>1:
                Color(*AMBER);pts=[]
                for p in self.route:q=self.project(*p);pts += [q[0],q[1]]
                Line(points=pts,width=dp(1.5))
            if self.data.get("connected"):
                x,y=self.project(self.data["lat"],self.data["lon"]);Color(*AMBER);Triangle(points=[x,y+dp(12),x-dp(8),y-dp(8),x+dp(8),y-dp(8)]);Color(*WHITE);Line(circle=(x,y,dp(23)),width=1)

class DrawingPad(Widget):
    def __init__(self,**kw):super().__init__(**kw);self.strokes=[];self.current=None;self.bind(pos=lambda *_:self.redraw(),size=lambda *_:self.redraw())
    def on_touch_down(self,t):
        if self.collide_point(*t.pos):self.current=[t.pos];self.strokes.append(self.current);return True
        return super().on_touch_down(t)
    def on_touch_move(self,t):
        if self.current is not None:self.current.append(t.pos);self.redraw();return True
        return super().on_touch_move(t)
    def on_touch_up(self,t):self.current=None;return True
    def clear(self):self.strokes=[];self.redraw()
    def redraw(self,*_):
        self.canvas.clear()
        with self.canvas:
            Color(0.01,0.01,0.01,1);Rectangle(pos=self.pos,size=self.size);Color(.8,.8,.8,.9)
            for s in self.strokes:
                if len(s)>1:Line(points=[v for p in s for v in p],width=dp(2))

class BaseScreen(Screen):pass

class AeroflyATC(MDApp):
    tab=StringProperty("flight")
    def build(self):
        self.theme_cls.theme_style="Dark";self.theme_cls.primary_palette="Amber";self.theme_cls.accent_palette="Amber"
        self.settings_dir=self.user_data_dir;os.makedirs(self.settings_dir,exist_ok=True)
        self.telemetry=Telemetry() if Telemetry else None;self.alert_engine=adv.FlightAlertEngine();self.clearance=adv.ClearanceTracker();self.route=[];self.chat=[];self.flight_log=None
        self.gemini_key=self.load("gemini_key","");self.gemini_model=self.load("gemini_model","gemini-3.6-flash");self.openaip_key=self.load("openaip_key","")
        sm=ScreenManager(transition=FadeTransition(duration=.08))
        for name,fn in (("home",self.home_screen),("flight",self.flight_screen),("comms",self.comms_screen),("scratch",self.scratch_screen),("airports",self.airports_screen),("settings",self.settings_screen)):
            s=BaseScreen(name=name);s.add_widget(fn());sm.add_widget(s)
        self.sm=sm
        if self.telemetry:
            try:self.telemetry.start()
            except Exception:pass
        Clock.schedule_interval(self.tick,.25)
        return sm
    def load(self,k,d):
        try:
            with open(os.path.join(self.settings_dir,k+".txt"),encoding="utf8") as f:return f.read().strip() or d
        except OSError:return d
    def save(self,k,v):
        with open(os.path.join(self.settings_dir,k+".txt"),"w",encoding="utf8") as f:f.write(v.strip())
    def shell(self,title,body,bottom=True):
        box=BoxLayout(orientation="vertical");box.add_widget(TopBar(title,self));box.add_widget(body)
        if bottom:box.add_widget(NavBar(self))
        return box
    def home_screen(self):
        body=BoxLayout(orientation="vertical",padding=dp(8),spacing=dp(7));c=BoxLayout(orientation="vertical",padding=dp(12),spacing=dp(6),size_hint_y=None,height=dp(125));bg(c,PANEL)
        c.add_widget(label("FLIGHT OPERATIONS",11,AMBER,True));self.home_conn=label("WAITING",21,WHITE,True);c.add_widget(self.home_conn);self.home_detail=label("Start Aerofly FS Global and enable FSWidgets.",10,MUTED);c.add_widget(self.home_detail);body.add_widget(c)
        g=GridLayout(cols=2,spacing=dp(7),size_hint_y=None,height=dp(155))
        self.home_fields={}
        for k in ("CONNECTION","AI ATC","FLIGHT LOG","WEATHER"):
            p=BoxLayout(orientation="vertical",padding=dp(10),spacing=dp(4));bg(p,PANEL);p.add_widget(label(k,9,MUTED,True));v=label("OFFLINE" if k=="CONNECTION" else ("READY" if k=="AI ATC" else "NO DATA"),16,AMBER if k=="CONNECTION" else WHITE,True);p.add_widget(v);self.home_fields[k]=v;g.add_widget(p)
        body.add_widget(g);body.add_widget(Widget());return self.shell("AeroflyATC",body)
    def flight_screen(self):
        body=BoxLayout(orientation="vertical")
        row=BoxLayout(size_hint_y=None,height=dp(42),padding=dp(4),spacing=dp(4))
        for text,fn in (("LAYERS",lambda: self.flight_map.zoom_by(1.25)),("WX",lambda:self.fetch_weather("HUEN")),("RADAR",self.fetch_radar),("CENTER",self.flight_map.center_aircraft),("FILTER",lambda:self.flight_map.zoom_by(.8))):
            b=ThemedButton(text=text,active=(text=="CENTER"));b.bind(on_release=lambda _,f=fn:f());row.add_widget(b)
        body.add_widget(row);self.flight_map=FlightMap();body.add_widget(self.flight_map);self.flight_status=label("WAITING FOR ACTIVE FLIGHT TO BE DETECTED...",8,MUTED);self.flight_status.size_hint_y=None;self.flight_status.height=dp(28);body.add_widget(self.flight_status);self.hud=TelemetryHUD();body.add_widget(self.hud);return self.shell("My Flight",body)
    def comms_screen(self):
        body=BoxLayout(orientation="vertical",padding=dp(7),spacing=dp(6))
        self.radio1=self.radio_row("COM 1","118.700","122.800");self.radio2=self.radio_row("COM 2","121.900","118.100");body.add_widget(self.radio1);body.add_widget(self.radio2)
        b=ThemedButton(text="'A' FREQUENCIES",active=True,size_hint_y=None,height=dp(34));b.bind(on_release=lambda *_:self.auto_frequencies());body.add_widget(b)
        scroll=ScrollView();self.chat_label=label("ATC SYSTEM READY",12,WHITE);self.chat_label.text_size=(None,None);self.chat_label.size_hint_y=None;self.chat_label.height=dp(220);scroll.add_widget(self.chat_label);body.add_widget(scroll)
        channels=BoxLayout(size_hint_y=None,height=dp(35),spacing=dp(3))
        for x in ("COM1","COM2","INT1","INT2","INT3","ATC"):channels.add_widget(ThemedButton(text=x,active=x=="COM1"))
        body.add_widget(channels)
        r=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(5));self.msg=ThemedInput(hint_text="Type a message...",multiline=False);r.add_widget(self.msg)
        mic=ThemedButton(text="MIC",active=True,size_hint_x=None,width=dp(55));mic.bind(on_release=lambda *_:self.speech_to_text());send=ThemedButton(text="SEND",active=True,size_hint_x=None,width=dp(55));send.bind(on_release=lambda *_:self.send_message());r.add_widget(mic);r.add_widget(send);body.add_widget(r);return self.shell("Comms",body)
    def radio_row(self,title,a,s):
        box=BoxLayout(size_hint_y=None,height=dp(52),spacing=dp(5));box.add_widget(label(title,9,MUTED,True));av=label(a,17,GREEN,True);sv=label(s,15,MUTED,True);box.add_widget(av);b=ThemedButton(text="⇄",active=True,size_hint_x=None,width=dp(48));b.bind(on_release=lambda *_:self.swap_radio(av,sv));box.add_widget(b);box.add_widget(sv);box.active=av;box.standby=sv;return box
    def swap_radio(self,a,s):a.text,s.text=s.text,a.text
    def scratch_screen(self):
        body=BoxLayout(orientation="vertical");pad=DrawingPad();body.add_widget(pad);tools=BoxLayout(size_hint_y=None,height=dp(58),spacing=dp(7),padding=dp(8))
        for txt,fn in (("▣",lambda:None),("✎",lambda:None),("⌫",lambda:None),("CLEAR",pad.clear)):b=ThemedButton(text=txt,active=txt=="✎");b.bind(on_release=lambda _,f=fn:f());tools.add_widget(b)
        body.add_widget(tools);return self.shell("Scratchpad",body)
    def airports_screen(self):
        body=BoxLayout(orientation="vertical",padding=dp(7),spacing=dp(6));r=BoxLayout(size_hint_y=None,height=dp(46),spacing=dp(5));self.airport_q=ThemedInput(hint_text="ICAO / airport name",multiline=False);r.add_widget(self.airport_q);b=ThemedButton(text="SEARCH",active=True,size_hint_x=None,width=dp(78));b.bind(on_release=lambda *_:self.search_airports());r.add_widget(b);body.add_widget(r)
        self.airport_results=label("Search the live aviation data service.",11,WHITE);self.airport_results.text_size=(None,None);scroll=ScrollView();scroll.add_widget(self.airport_results);body.add_widget(scroll);return self.shell("Airports",body)
    def settings_screen(self):
        body=BoxLayout(orientation="vertical",padding=dp(8),spacing=dp(7))
        p=BoxLayout(orientation="vertical",padding=dp(10),spacing=dp(6),size_hint_y=None,height=dp(210));bg(p,PANEL);p.add_widget(label("GEMINI AI",10,AMBER,True));self.key=ThemedInput(hint_text="Gemini API key",password=True,multiline=False);self.key.text=self.gemini_key;p.add_widget(self.key);self.model=ThemedInput(text=self.gemini_model,multiline=False);p.add_widget(self.model);b=ThemedButton(text="SAVE GEMINI",active=True,size_hint_y=None,height=dp(40));b.bind(on_release=lambda *_:self.save_ai());p.add_widget(b);body.add_widget(p)
        p2=BoxLayout(orientation="vertical",padding=dp(10),spacing=dp(6),size_hint_y=None,height=dp(145));bg(p2,PANEL);p2.add_widget(label("OPENAIP",10,AMBER,True));self.openaip=ThemedInput(hint_text="OpenAIP API key",password=True,multiline=False);self.openaip.text=self.openaip_key;p2.add_widget(self.openaip);b2=ThemedButton(text="SAVE MAP KEY",active=True,size_hint_y=None,height=dp(40));b2.bind(on_release=lambda *_:self.save_map());p2.add_widget(b2);body.add_widget(p2);body.add_widget(Widget());return self.shell("Settings",body,False)
    def save_ai(self):self.gemini_key=self.key.text.strip();self.gemini_model=self.model.text.strip() or "gemini-3.6-flash";self.save("gemini_key",self.gemini_key);self.save("gemini_model",self.gemini_model);self.switch_tab("comms")
    def save_map(self):self.openaip_key=self.openaip.text.strip();self.save("openaip_key",self.openaip_key);self.switch_tab("flight")
    def switch_tab(self,tab):self.tab=tab;self.sm.current=tab
    def show_settings(self):self.sm.current="settings"
    def tick(self,_dt):
        if not self.telemetry:return
        try:
            d=self.telemetry.snapshot();self.flight_map.update(d,self.telemetry.trail_snapshot(),self.route);self.hud.update(d)
            if d.get("connected"):
                self.flight_status.text="CONNECTED • %s • %s • %s"%(d.get("transport",""),d.get("source_ip",""),d.get("phase",""))
                self.home_conn.text="FLIGHT DETECTED";self.home_detail.text="Aerofly telemetry active via "+d.get("transport","")
                self.home_fields["CONNECTION"].text="ONLINE";self.home_fields["FLIGHT LOG"].text=str(d.get("packets",0))+" PACKETS"
                alerts=self.alert_engine.evaluate(d,self.clearance.current)
                if alerts:self.flight_status.text="⚠ "+" • ".join(alerts)
            else:
                self.flight_status.text="WAITING • UDP 40092 / TCP 58585 • "+(d.get("last_error","") or "No Aerofly telemetry")
                self.home_conn.text="WAITING";self.home_fields["CONNECTION"].text="OFFLINE"
        except Exception as e:self.flight_status.text="RECOVERED: "+str(e)[:80]
    def append_chat(self,who,text):
        self.chat.append((who,text));self.chat=self.chat[-50:];self.chat_label.text="\n\n".join("[{}]\n{}".format(a,b) for a,b in self.chat);self.chat_label.texture_update();self.chat_label.height=max(dp(220),self.chat_label.texture_size[1]+dp(15))
    def send_message(self):
        m=self.msg.text.strip()
        if not m:return
        self.append_chat("PILOT",m);self.msg.text=""
        if self.clearance.current:self.append_chat("READBACK","CORRECT" if self.clearance.readback(m) else "NOT VERIFIED")
        if self.gemini_key:self.ask_gemini(m)
    def ask_gemini(self,prompt):
        def work():
            try:
                url="https://generativelanguage.googleapis.com/v1beta/models/"+urllib.parse.quote(self.gemini_model)+":generateContent?key="+urllib.parse.quote(self.gemini_key)
                payload={"contents":[{"parts":[{"text":"You are a concise ICAO ATC companion for Aerofly FS Global. Flight data: "+json.dumps(self.telemetry.snapshot() if self.telemetry else {})+" Pilot: "+prompt}]}]}
                req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"})
                with urllib.request.urlopen(req,timeout=20) as r:data=json.loads(r.read().decode())
                text=data["candidates"][0]["content"]["parts"][0]["text"];self.clearance.parse(text);Clock.schedule_once(lambda *_:self.append_chat("AI ATC",text),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.append_chat("AI ERROR",str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def fetch_weather(self,icao):
        def work():
            try:
                m=adv.fetch_metar(icao);t=adv.fetch_taf(icao);text="METAR\n"+json.dumps(m,indent=2)+"\n\nTAF\n"+json.dumps(t,indent=2);Clock.schedule_once(lambda *_:self.weather_result(text),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.weather_result("WEATHER ERROR: "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def weather_result(self,text):self.home_fields["WEATHER"].text="UPDATED";self.append_chat("WEATHER",text[:3500]);self.switch_tab("comms")
    def fetch_radar(self):
        def work():
            try:
                d=adv.rainviewer();frames=d.get("radar",{}).get("past",[]);msg="RainViewer radar frames available: %d"%len(frames)
                if frames:msg+="\nLatest frame path: "+frames[-1].get("path","")
                Clock.schedule_once(lambda *_:self.append_chat("RADAR",msg),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.append_chat("RADAR","ERROR: "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def auto_frequencies(self):self.append_chat("RADIO","A-frequency set loaded. Use COM swap to change active/standby.")
    def search_airports(self):
        q=self.airport_q.text.strip()
        if not q:return
        def work():
            try:
                rows=adv.search_airports(q);out=[]
                for x in rows:out.append(x.get("display_name",x.get("name","Unknown"))+"\n"+x.get("lat","")+" , "+x.get("lon",""))
                Clock.schedule_once(lambda *_:setattr(self.airport_results,"text","\n\n".join(out) or "No results"),0)
            except Exception as e:Clock.schedule_once(lambda *_:setattr(self.airport_results,"text","SEARCH ERROR: "+str(e)),0)
        threading.Thread(target=work,daemon=True).start()
    def speech_to_text(self):
        try:
            from jnius import autoclass
            SR=autoclass("android.speech.SpeechRecognizer");PA=autoclass("org.kivy.android.PythonActivity").mActivity
            if SR.isRecognitionAvailable(PA):self.append_chat("MIC","Android speech recognition is available. Native recognition session requested.")
            else:self.append_chat("MIC","Android speech recognition is unavailable on this device.")
        except Exception as e:self.append_chat("MIC","Speech recognition unavailable: "+str(e))
    def on_stop(self):
        if self.telemetry:
            try:self.telemetry.stop()
            except Exception:pass

if __name__=="__main__":AeroflyATC().run()
