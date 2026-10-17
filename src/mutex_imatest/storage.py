from __future__ import annotations
from pathlib import Path
import json,sqlite3,time,uuid,hashlib
from .models import AnalysisResult
from .utils import atomic_json

class Session:
    def __init__(self,path):
        self.path=Path(path).resolve();self.path.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path/"session.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS results(id TEXT PRIMARY KEY, fingerprint TEXT, source TEXT, chart_id TEXT, result_json TEXT, created REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT)")
        self.db.commit()
        if not (self.path/"session.json").exists():
            atomic_json(self.path/"session.json",{"format":"MUTEX Session","schema_version":1,"created":time.time()})
    def add(self,result):
        identity={"fingerprint":result.image.fingerprint,"chart":result.template,"settings":result.settings}
        uid=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        target=self.path/"results"/(uid+".json");result.save(target)
        existing=self.db.execute("SELECT created FROM results WHERE id=?",(uid,)).fetchone()
        self.db.execute("INSERT OR REPLACE INTO results VALUES(?,?,?,?,?,?)",(uid,result.image.fingerprint,result.image.path,result.chart_id,str(target.relative_to(self.path)),existing[0] if existing else time.time()))
        self.db.commit();return uid
    def load_results(self):
        return [AnalysisResult.load(self.path/file) for (file,) in self.db.execute("SELECT result_json FROM results ORDER BY created")]
    def save_state(self,key,data):
        self.db.execute("INSERT OR REPLACE INTO state VALUES(?,?)",(key,json.dumps(data,ensure_ascii=False)))
        self.db.commit()
    def state(self,key,default=None):
        row=self.db.execute("SELECT value FROM state WHERE key=?",(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def close(self):self.db.close()
