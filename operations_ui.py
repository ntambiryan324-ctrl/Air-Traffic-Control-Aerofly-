import json, os, threading, time
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
import advanced_features as adv

class OperationsScreen(Screen):
    def __init__(self, app_ref, **kw):
        super().__init__(**kw); self.app_ref=app_ref
        root=BoxLayout(orientation="vertical",spacing=dp(6),padding=dp(7))
        root.add_widget(app_ref.header("OPERATIONS","Airport intelligence • weather • radar • navigation • datalink"))
        s=ScrollView(); box=BoxLayout(orientation="vertical",spacing=dp(6),size_hint_y=None); box.bind(minimum_height=box.setter("height"))
        self.icao=TextInput(text="HUEN",multiline=False,hint_text="ICAO airport",size_hint_y=None,height=dp(44))
        box.add_widget(self.icao)
        for label,fn in (("AIRPORT INFO",self.airport),("METAR",self.metar),("TAF",self.taf),("SEARCH AIRPORTS",self.search),("RADAR",self.radar),("ROUTE ANALYSIS",self.route),("NEAREST AIRPORT",self.nearest),("REPLAY LOG",self.replay)):
            b=app_ref.button(label, label=="METAR",42); b.bind(on_press=fn); box.add_widget(b)
        self.output=TextInput(readonly=True,multiline=True,size_hint_y=None,height=dp(220)); box.add_widget(self.output)
        self.alerts=Label(text="FLIGHT ALERTS: none",size_hint_y=None,height=dp(42)); box.add_widget(self.alerts)
        row=BoxLayout(size_hint_y=None,height=dp(48),spacing=dp(4))
        self.dl=TextInput(hint_text="CPDLC / datalink message…",multiline=False)
        b=app_ref.button("QUEUE",True,42);b.size_hint_x=None;b.width=dp(90);b.bind(on_press=self.send_dl)
        row.add_widget(self.dl);row.add_widget(b);box.add_widget(row)
        lr=BoxLayout(size_hint_y=None,height=dp(44),spacing=dp(4))
        for label,on in (("START LOG",True),("STOP LOG",False)):
            b=app_ref.button(label,on,40);b.bind(on_press=lambda _,v=on:self.log(v));lr.add_widget(b)
        box.add_widget(lr); self.logstatus=Label(text="FLIGHT LOGGER: stopped",size_hint_y=None,height=dp(28));box.add_widget(self.logstatus)
        s.add_widget(box);root.add_widget(s);self.add_widget(root)
        Clock.schedule_interval(self.refresh_alerts,1)
    def worker(self,fn):
        def run():
            try:r=fn();Clock.schedule_once(lambda *_:self.show(r,None),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.show(None,e),0)
        threading.Thread(target=run,daemon=True).start()
    def show(self,data,err):
        self.output.text=("REQUEST FAILED\n"+repr(err)) if err else json.dumps(data,indent=2)[:14000]
    def airport(self,*_):self.worker(lambda:adv.fetch_airport(self.icao.text))
    def search(self,*_):self.worker(lambda:adv.search_airports(self.icao.text))
    def nearest(self,*_):
        d=self.app_ref.telemetry.snapshot()
        if not d.get("connected"): self.output.text="Connect Aerofly first."; return
        n=adv.nearest_airport(d["lat"],d["lon"])
        self.output.text=("NEAREST REFERENCE AIRPORT\\nICAO: %s\\nNAME: %s\\nDISTANCE: %.1f NM\\nPOSITION: %.4f, %.4f"%n) if n else "No airport reference available."
    def replay(self,*_):
        rows=self.app_ref.logger.load()
        if not rows:self.output.text="No recorded flight log.";return
        first,last=rows[0],rows[-1]
        self.output.text="FLIGHT REPLAY LOG\\nSAMPLES: %d\\nSTART: %s\\nEND: %s\\n\\nReplay data is retained locally in flight_log.jsonl and can be rendered on the map in the next playback pass."%(len(rows),time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(first["t"])),time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(last["t"])))
    def metar(self,*_):self.worker(lambda:adv.fetch_metar(self.icao.text))
    def taf(self,*_):self.worker(lambda:adv.fetch_taf(self.icao.text))
    def radar(self,*_):
        def done(data):
            frames=data.get("radar",{}).get("past",[])
            if not frames: return
            f=frames[-1]; url=data.get("host","")+f.get("path","")+"/256/{z}/{x}/{y}/2/1_0.png"
            ok=self.app_ref.enable_radar(url)
            self.output.text=("RAIN RADAR MODE ENABLED\n"+url) if ok else "Radar metadata loaded, but map overlay is unavailable."
        def run():
            try:r=adv.rainviewer();Clock.schedule_once(lambda *_:done(r),0)
            except Exception as e:Clock.schedule_once(lambda *_:self.show(None,e),0)
        threading.Thread(target=run,daemon=True).start()
    def route(self,*_):
        p=self.app_ref.plan.get("points",[])
        if len(p)>1:
            dist=adv.route_distance(p); brg=adv.initial_bearing(*p[0],*p[1])
            self.output.text="ROUTE DISTANCE: %.1f NM\nFIRST LEG: %03.0f°\nWAYPOINTS: %d"%(dist,brg,len(p))
        else:self.output.text="Add two or more route points in Flight Plan."
    def refresh_alerts(self,*_):
        d=self.app_ref.telemetry.snapshot(); a=self.app_ref.alert_engine.evaluate(d,self.app_ref.clearance.current)
        self.alerts.text="FLIGHT ALERTS: "+(" • ".join(a) if a else "none")
    def send_dl(self,*_):
        m=self.dl.text.strip()
        if not m:return
        self.app_ref.datalink.append({"time":time.time(),"direction":"OUT","message":m});self.dl.text=""
        self.output.text="CPDLC QUEUED\n"+m+"\n\nNo documented Aerofly FSWidgets CPDLC write channel exists, so this is an in-app datalink queue."
    def log(self,on):
        self.app_ref.logger.start() if on else self.app_ref.logger.stop()
        self.logstatus.text="FLIGHT LOGGER: "+("recording" if on else "stopped")
