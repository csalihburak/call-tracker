"""Bot sürecini panelden başlatma/durdurma ve canlılık tespiti.

Bot (`python -m ig_agent.run`) panelden bağımsız, ayrı bir oturumda çalışır;
panel kapansa bile bot çalışmaya devam eder. Çıktısı `ig_agent.log`'a yazılır.
Canlılık iki sinyalle ölçülür: PID yaşıyor mu + son nabız yeterince yeni mi.
"""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import repository as repo
from .config import PROJE_KOKU

LOG_YOLU = PROJE_KOKU / "ig_agent.log"

# Bu kadar saniyedir nabız yoksa bot "yanıt vermiyor" sayılır. Bot en uzun
# tarayıcı işlemlerinde (sayfa yükleme ~60 sn) nabız atamayabilir.
NABIZ_ZAMAN_ASIMI_SN = 120


def pid_yasiyor_mu(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        # Panelin başlattığı süreç öldüyse zombi kalır; toplayıp ölü say
        if os.waitpid(pid, os.WNOHANG)[0] == pid:
            return False
    except ChildProcessError:
        pass  # bizim çocuğumuz değil (ör. terminalden başlatıldı)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # var ama başka kullanıcıya ait
    return True


def kayitli_pid(conn: sqlite3.Connection) -> Optional[int]:
    try:
        return int(repo.durum_getir(conn, "bot_pid", "") or 0) or None
    except ValueError:
        return None


def durum(conn: sqlite3.Connection, simdi: Optional[datetime] = None) -> dict:
    """{'pid', 'surec_var', 'nabiz_yasi_sn', 'canli', 'etkinlik'}"""
    simdi = simdi or datetime.now()
    pid = kayitli_pid(conn)
    surec_var = pid_yasiyor_mu(pid)
    nabiz_yasi = None
    ham = repo.durum_getir(conn, "bot_nabiz", "")
    if ham:
        try:
            nabiz_yasi = (simdi - datetime.fromisoformat(ham)).total_seconds()
        except ValueError:
            pass
    return {
        "pid": pid,
        "surec_var": surec_var,
        "nabiz_yasi_sn": nabiz_yasi,
        "canli": surec_var and nabiz_yasi is not None and nabiz_yasi < NABIZ_ZAMAN_ASIMI_SN,
        "etkinlik": repo.durum_getir(conn, "bot_durum", ""),
    }


def baslat(conn: sqlite3.Connection, python: str = sys.executable) -> int:
    """Bot sürecini başlatır (zaten çalışıyorsa mevcut PID'i döner)."""
    mevcut = kayitli_pid(conn)
    if pid_yasiyor_mu(mevcut):
        return mevcut  # type: ignore[return-value]
    log = open(LOG_YOLU, "a", encoding="utf-8")
    log.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} bot başlatılıyor =====\n")
    log.flush()
    surec = subprocess.Popen(
        [python, "-u", "-m", "ig_agent.run"],
        cwd=str(PROJE_KOKU),
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # panel kapansa da bot yaşasın
    )
    log.close()
    repo.durum_ayarla(conn, "bot_pid", surec.pid)
    repo.nabiz_at(conn, "başlatılıyor")
    return surec.pid


def durdur(conn: sqlite3.Connection) -> bool:
    """Bot sürecine SIGTERM gönderir (tarayıcıyı düzgün kapatır)."""
    pid = kayitli_pid(conn)
    if not pid_yasiyor_mu(pid):
        repo.durum_ayarla(conn, "bot_pid", "")
        return False
    os.kill(pid, signal.SIGTERM)  # type: ignore[arg-type]
    return True


def log_son_satirlar(n: int = 60, yol: Path = LOG_YOLU) -> str:
    if not yol.exists():
        return ""
    with open(yol, "rb") as f:
        f.seek(0, os.SEEK_END)
        boyut = f.tell()
        f.seek(max(0, boyut - 64_000))
        metin = f.read().decode("utf-8", errors="replace")
    return "\n".join(metin.splitlines()[-n:])
