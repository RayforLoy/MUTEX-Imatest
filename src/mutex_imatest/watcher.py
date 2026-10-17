from __future__ import annotations
from pathlib import Path
import time,os
from PySide6.QtCore import QObject,QTimer,Signal
from .models import IMAGE_EXTENSIONS

def can_read_complete(path):
    if os.name!="nt":return True
    import ctypes
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p,ctypes.c_ulong,ctypes.c_ulong,ctypes.c_void_p]
    kernel.CreateFileW.restype=ctypes.c_void_p
    handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0,None)
    if handle==ctypes.c_void_p(-1).value:return False
    kernel.CloseHandle.argtypes=[ctypes.c_void_p];kernel.CloseHandle(handle);return True

class SettledWatcher(QObject):
    file_ready=Signal(str)
    error=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.folder=None;self.states={};self.seen=set()
        self.timer=QTimer(self);self.timer.setInterval(1500);self.timer.timeout.connect(self.poll)
    def start(self,folder,existing=False):
        self.folder=Path(folder).resolve();self.states={};self.seen=set()
        if not self.folder.is_dir():raise ValueError("Watch directory does not exist")
        if not existing:
            self.seen={(str(p),p.stat().st_size,p.stat().st_mtime_ns) for p in self.folder.iterdir() if p.is_file()}
        self.timer.start()
    def stop(self):self.timer.stop();self.folder=None
    def poll(self):
        if not self.folder:return
        now=time.monotonic()
        try:
            for p in self.folder.iterdir():
                if not p.is_file() or p.suffix.lower() not in IMAGE_EXTENSIONS:continue
                stat=p.stat();signature=(str(p),stat.st_size,stat.st_mtime_ns)
                if signature in self.seen or stat.st_size==0:continue
                previous=self.states.get(str(p))
                if previous and previous[0]==signature:
                    if now-previous[1]>=3 and can_read_complete(p):
                        self.seen.add(signature);self.file_ready.emit(str(p));self.states.pop(str(p),None)
                else:self.states[str(p)]=(signature,now)
        except OSError as exc:self.error.emit(str(exc))
