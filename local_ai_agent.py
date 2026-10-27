"""Offline local ATC agent. Optional at startup; no API key required."""
from __future__ import annotations
import json, math, os, re, shutil, stat, subprocess, threading, time, urllib.request
from pathlib import Path

try:
    from faa_knowledge import FAAKnowledge
except Exception:
    FAAKnowledge = None

MODEL_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
MODEL_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}?download=true"
MODEL_SIZE_BYTES = 1_120_000_000
SYSTEM_PROMPT = ("You are AeroflyATC, an offline ATC assistant for a flight simulator. "
                 "Use only supplied simulator state, navigation, weather, terrain, airspace "
                 "and retrieved aviation knowledge. Never invent aviation facts. "
                 "Use concise standard phraseology. This is simulation assistance, not real ATC.")

class AviationTools:
    def __init__(self, provider=None): self.provider = provider
    @staticmethod
    def distance_nm(lat1, lon1, lat2, lon2):
        r=3440.065; p1,p2=math.radians(lat1),math.radians(lat2)
        dp=math.radians(lat2-lat1); dl=math.radians(lon2-lon1)
        x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return 2*r*math.asin(min(1,math.sqrt(x)))
    @staticmethod
    def bearing_deg(lat1, lon1, lat2, lon2):
        p1,p2=math.radians(lat1),math.radians(lat2); dl=math.radians(lon2-lon1)
        return (math.degrees(math.atan2(math.sin(dl)*math.cos(p2),
                math.cos(p1)*math.sin(p2)-math.sin(p1)*math.cos(p2)*math.cos(dl)))+360)%360
    def resolve_fix(self, ident, state=None):
        fn=getattr(self.provider,"search_navdata",None) if self.provider else None
        if not fn: return None
        try:
            result=fn(ident); items=[result] if isinstance(result,dict) else result
            for item in items or []:
                if str(item.get("ident",item.get("name",""))).upper()==ident.upper(): return item
        except Exception: pass
        return None

class LocalModel:
    def __init__(self, root):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.model_path=self.root/MODEL_FILE; self.server_url="http://127.0.0.1:8089"
        self.process=None
        self.binary_source=Path(__file__).resolve().parent/"native"/"arm64-v8a"/"llama-server"
        self.binary_path=self.root/"llama-server"
    @property
    def model_present(self):
        try: return self.model_path.stat().st_size>100_000_000
        except OSError: return False
    @property
    def runtime_present(self): return self.binary_source.exists() or self.binary_path.exists()
    def download_model(self, progress=None):
        tmp=self.model_path.with_suffix(".part")
        req=urllib.request.Request(MODEL_URL,headers={"User-Agent":"AeroflyATC/2.0"})
        with urllib.request.urlopen(req,timeout=60) as src,open(tmp,"wb") as dst:
            total=int(src.headers.get("Content-Length") or MODEL_SIZE_BYTES); done=0
            while True:
                block=src.read(1024*1024)
                if not block: break
                dst.write(block); done+=len(block)
                if progress: progress(done,total)
        if tmp.stat().st_size<100_000_000: raise RuntimeError("Downloaded model is unexpectedly small.")
        tmp.replace(self.model_path)
    def _prepare_binary(self):
        if self.binary_path.exists(): return self.binary_path
        if not self.binary_source.exists(): return None
        shutil.copy2(self.binary_source,self.binary_path)
        os.chmod(self.binary_path,os.stat(self.binary_path).st_mode|stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH)
        return self.binary_path
    def start_server(self):
        if self.process and self.process.poll() is None: return True
        if not self.model_present: return False
        binary=self._prepare_binary()
        if binary is None: return False
        try:
            self.process=subprocess.Popen([str(binary),"-m",str(self.model_path),"--host","127.0.0.1",
                "--port","8089","-c","2048","-t","4","--no-webui"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            time.sleep(1); return self.process.poll() is None
        except Exception:
            self.process=None; return False
    def stop_server(self):
        try:
            if self.process and self.process.poll() is None: self.process.terminate()
        except Exception: pass
        self.process=None
    def chat(self,payload,timeout=45):
        if not self.start_server(): return None
        try:
            body=json.dumps({"messages":[{"role":"system","content":SYSTEM_PROMPT},
                {"role":"user","content":json.dumps(payload,separators=(",",":"))}],
                "temperature":0.15,"top_p":0.85,"max_tokens":180}).encode()
            req=urllib.request.Request(self.server_url+"/v1/chat/completions",data=body,
                headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req,timeout=timeout) as response:
                return json.loads(response.read().decode())["choices"][0]["message"]["content"].strip()
        except Exception: return None

class OfflineATCAgent:
    def __init__(self,data_dir,provider=None):
        self.data_dir=Path(data_dir); self.model=LocalModel(self.data_dir/"models")
        self.tools=AviationTools(provider)
        self.knowledge=FAAKnowledge(self.data_dir) if FAAKnowledge else None
    def status(self):
        return {"local":True,"model":"Qwen2.5-1.5B-Instruct-Q4_K_M",
                "model_present":self.model.model_present,"runtime_present":self.model.runtime_present,
                "server_running":bool(self.model.process and self.model.process.poll() is None),
                "faa_knowledge":bool(self.knowledge and list(self.knowledge.root.glob("*.txt"))),
                "api_key_required":False}
    def update_faa_knowledge_async(self,done=None):
        def worker():
            error=None
            try:
                if not self.knowledge: raise RuntimeError("FAA knowledge module unavailable.")
                self.knowledge.update()
            except Exception as exc: error=str(exc)
            if done: done(error)
        threading.Thread(target=worker,daemon=True).start()
    def download_model_async(self,progress=None,done=None):
        def worker():
            error=None
            try: self.model.download_model(progress)
            except Exception as exc: error=str(exc)
            if done: done(error)
        threading.Thread(target=worker,daemon=True).start()
    def respond(self,message,aircraft=None,context=None):
        aircraft=aircraft or {}; context=context or {}
        knowledge=self.knowledge.search(message,4) if self.knowledge else []
        payload={"aircraft":aircraft,"aviation_context":context,"faa_knowledge":knowledge,"request":message}
        answer=self.model.chat(payload) if self.model.model_present else None
        if answer and "real-world atc clearance" not in answer.lower(): return answer
        match=re.search(r"(?i)\bdirect\s+([A-Z0-9]{2,7})",message.strip())
        if match:
            ident=match.group(1).upper(); fix=self.tools.resolve_fix(ident,aircraft)
            if fix and aircraft.get("lat") is not None and aircraft.get("lon") is not None:
                lat=fix.get("lat",fix.get("latitude")); lon=fix.get("lon",fix.get("longitude"))
                if lat is not None and lon is not None:
                    d=self.tools.distance_nm(float(aircraft["lat"]),float(aircraft["lon"]),float(lat),float(lon))
                    b=self.tools.bearing_deg(float(aircraft["lat"]),float(aircraft["lon"]),float(lat),float(lon))
                    return f"SIM ATC: Continue direct {ident}. Current bearing {b:.0f}, {d:.1f} NM."
            return f"SIM ATC: Unable to verify {ident} in the loaded navigation database. No clearance generated."
        return "SIM ATC: Local model is not loaded yet."
