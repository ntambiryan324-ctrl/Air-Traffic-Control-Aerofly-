"""Offline local ATC agent foundation. No API key is required."""
from __future__ import annotations
import json, math, re, threading, urllib.request
from pathlib import Path
MODEL_REPO="Qwen/Qwen2.5-1.5B-Instruct-GGUF"
MODEL_FILE="qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_URL=f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}?download=true"
MODEL_SIZE_BYTES=1120000000
SYSTEM_PROMPT="You are AeroflyATC, an offline ATC assistant for a flight simulator.\nUse only facts supplied in the current simulator state, navigation tools, weather, terrain,\nairspace and retrieved aviation knowledge. Never invent a waypoint, frequency, runway,\nairway, altitude restriction, procedure or aircraft position. Use concise standard aviation\nphraseology. This is simulation assistance, not real-world ATC authorization. If information\nis unavailable, say so instead of guessing."
class AviationTools:
    def __init__(self,provider=None): self.provider=provider
    @staticmethod
    def distance_nm(a,b,c,d):
        r=3440.065;p1,p2=math.radians(a),math.radians(c);dp=math.radians(c-a);dl=math.radians(d-b)
        x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return 2*r*math.asin(min(1,math.sqrt(x)))
    @staticmethod
    def bearing_deg(a,b,c,d):
        p1,p2=math.radians(a),math.radians(c);dl=math.radians(d-b)
        return (math.degrees(math.atan2(math.sin(dl)*math.cos(p2),math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)))+360)%360
    def resolve_fix(self,ident,state):
        fn=getattr(self.provider,"search_navdata",None) if self.provider else None
        if not fn:return None
        try:
            r=fn(ident);r=[r] if isinstance(r,dict) else r
            for x in r or []:
                if str(x.get("ident",x.get("name",""))).upper()==ident.upper():return x
        except Exception:pass
        return None
class LocalModel:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.model_path=self.root/MODEL_FILE;self.server_url="http://127.0.0.1:8089"
    @property
    def model_present(self):
        try:return self.model_path.stat().st_size>100_000_000
        except OSError:return False
    def download_model(self,progress=None):
        tmp=self.model_path.with_suffix(".part");req=urllib.request.Request(MODEL_URL,headers={"User-Agent":"AeroflyATC/2.0"})
        with urllib.request.urlopen(req,timeout=30) as src,open(tmp,"wb") as dst:
            total=int(src.headers.get("Content-Length") or MODEL_SIZE_BYTES);done=0
            while True:
                b=src.read(1024*1024)
                if not b:break
                dst.write(b);done+=len(b)
                if progress:progress(done,total)
        tmp.replace(self.model_path)
    def chat(self,payload,timeout=45):
        try:
            body=json.dumps({"messages":[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":json.dumps(payload,separators=(",",":"))}],"temperature":0.15,"top_p":0.85,"max_tokens":180}).encode()
            req=urllib.request.Request(self.server_url+"/v1/chat/completions",data=body,headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=timeout) as r:return json.loads(r.read().decode())["choices"][0]["message"]["content"].strip()
        except Exception:return None
class OfflineATCAgent:
    def __init__(self,data_dir,provider=None):
        self.data_dir=Path(data_dir);self.model=LocalModel(self.data_dir/"models");self.tools=AviationTools(provider)
    def status(self):return {"local":True,"model":"Qwen2.5-1.5B-Instruct-Q4_K_M","model_present":self.model.model_present,"api_key_required":False}
    def download_model_async(self,progress=None,done=None):
        def w():
            err=None
            try:self.model.download_model(progress)
            except Exception as e:err=str(e)
            if done:done(err)
        threading.Thread(target=w,daemon=True).start()
    def respond(self,message,aircraft=None,context=None):
        aircraft=aircraft or {};context=context or {}
        answer=self.model.chat({"aircraft":aircraft,"aviation_context":context,"request":message}) if self.model.model_present else None
        if answer and not any(x in answer.lower() for x in ("i have authorized","real-world atc clearance")):return answer
        m=re.search(r"(?i)\bdirect\s+([A-Z0-9]{2,7})",message.strip())
        if m:
            ident=m.group(1).upper();fix=self.tools.resolve_fix(ident,aircraft)
            if fix and aircraft.get("lat") is not None and aircraft.get("lon") is not None:
                lat=fix.get("lat",fix.get("latitude"));lon=fix.get("lon",fix.get("longitude"))
                if lat is not None and lon is not None:
                    d=self.tools.distance_nm(float(aircraft["lat"]),float(aircraft["lon"]),float(lat),float(lon));b=self.tools.bearing_deg(float(aircraft["lat"]),float(aircraft["lon"]),float(lat),float(lon))
                    return f"SIM ATC: Continue direct {ident}. Current bearing {b:.0f}, {d:.1f} NM."
            return f"SIM ATC: Unable to verify {ident} in the loaded navigation database. No clearance generated."
        return "SIM ATC: Local model is not loaded yet. Load the offline model to enable natural-language ATC."
