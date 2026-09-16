"""Offline FAA knowledge pack updater/retriever.

Sources are official FAA publications. The current FAA publications page lists the
Pilot/Controller Glossary effective 2026-07-09 and active JO 7110.65BB with changes.
The documents are downloaded to app-private storage and never require an API key.
"""
from __future__ import annotations
import html, re, urllib.request
from html.parser import HTMLParser
from pathlib import Path

SOURCES={
 "pilot_controller_glossary":"https://www.faa.gov/air_traffic/publications/atpubs/pcg_html/",
 "aim":"https://www.faa.gov/air_traffic/publications/atpubs/aim_html/",
 "atc_order_7110_65":"https://www.faa.gov/air_traffic/publications/atpubs/atc_html/",
 "publications":"https://www.faa.gov/air_traffic/publications/",
}

class _Text(HTMLParser):
    def __init__(self): super().__init__();self.parts=[]
    def handle_data(self,d):
        d=d.strip()
        if d:self.parts.append(d)
    def text(self):return re.sub(r"\s+"," "," ".join(self.parts))

class FAAKnowledge:
    def __init__(self,root):
        self.root=Path(root)/"faa";self.root.mkdir(parents=True,exist_ok=True)
    def update(self,timeout=30):
        results={}
        for name,url in SOURCES.items():
            try:
                req=urllib.request.Request(url,headers={"User-Agent":"AeroflyATC/2.0"})
                with urllib.request.urlopen(req,timeout=timeout) as r: raw=r.read().decode("utf-8","ignore")
                p=_Text();p.feed(raw);text=p.text()
                (self.root/(name+".txt")).write_text(text,encoding="utf-8")
                results[name]=len(text)
            except Exception as e:results[name]=str(e)
        return results
    def search(self,query,limit=5):
        terms=[x.lower() for x in re.findall(r"[A-Za-z0-9]{3,}",query)]
        scored=[]
        for path in self.root.glob("*.txt"):
            try:t=path.read_text(encoding="utf-8")
            except Exception:continue
            chunks=re.split(r"(?<=[.!?])\s+",t)
            for chunk in chunks:
                low=chunk.lower();score=sum(low.count(q) for q in terms)
                if score:scored.append((score,chunk[:1200]))
        scored.sort(reverse=True,key=lambda x:x[0])
        return [x[1] for x in scored[:limit]]
