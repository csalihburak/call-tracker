"""run.py argümanları, istemci fabrikası ve surec.py platform ayrımı."""

from __future__ import annotations

import pytest

from ig_agent import db, platformlar, repository as repo, run, surec
from ig_agent.config import Ayarlar, ayarlari_yukle
from ig_agent.instagram import InstagramClient
from ig_agent.tiktok import TikTokClient


def test_istemci_olustur():
    assert isinstance(platformlar.istemci_olustur("instagram", Ayarlar()), InstagramClient)
    assert isinstance(platformlar.istemci_olustur("tiktok", ayarlari_yukle("tiktok")), TikTokClient)
    with pytest.raises(ValueError):
        platformlar.istemci_olustur("facebook", Ayarlar())
    with pytest.raises(ValueError):
        platformlar.istemci_olustur("myspace", Ayarlar())


def test_run_arguman():
    assert run.arg_coz([]).platform == "instagram"
    assert run.arg_coz(["--platform", "tiktok"]).platform == "tiktok"
    with pytest.raises(SystemExit):
        run.arg_coz(["--platform", "myspace"])


def test_log_yollari():
    assert surec.log_yolu().name == "ig_agent.log"
    assert surec.log_yolu("tiktok").name == "tiktok_agent.log"
    assert surec.LOG_YOLU == surec.log_yolu()


@pytest.fixture
def conn(tmp_path):
    c = db.hazirla(Ayarlar(veritabani_yolu=str(tmp_path / "s.db")))
    yield c
    c.close()


def test_baslat_platform_argumani_ve_pid_anahtari(conn, tmp_path, monkeypatch):
    komutlar = []

    class SahteSurec:
        pid = 4242

    monkeypatch.setattr(surec, "log_yolu", lambda platform="instagram": tmp_path / f"{platform}.log")
    monkeypatch.setattr(surec.subprocess, "Popen",
                        lambda komut, **kw: komutlar.append(komut) or SahteSurec())
    monkeypatch.setattr(surec, "pid_yasiyor_mu", lambda pid: False)
    assert surec.baslat(conn, python="py", platform="tiktok") == 4242
    assert komutlar[0][-2:] == ["--platform", "tiktok"]
    assert repo.durum_getir(conn, "tiktok:bot_pid") == "4242"
    assert repo.durum_getir(conn, "bot_pid") == ""
    assert surec.kayitli_pid(conn, "tiktok") == 4242 and surec.kayitli_pid(conn) is None
    assert (tmp_path / "tiktok.log").exists()


def test_durdur_yalniz_kendi_platformu(conn, monkeypatch):
    oldurulen = []
    monkeypatch.setattr(surec, "pid_yasiyor_mu", lambda pid: bool(pid))
    monkeypatch.setattr(surec.os, "kill", lambda pid, sinyal: oldurulen.append(pid))
    repo.durum_ayarla(conn, "bot_pid", "111")
    repo.durum_ayarla(conn, "bot_pid", "222", platform="tiktok")
    assert surec.durdur(conn, platform="tiktok")
    assert oldurulen == [222]


def test_durum_platform_nabzi(conn):
    repo.nabiz_at(conn, "tiktok işi", platform="tiktok")
    assert surec.durum(conn, platform="tiktok")["etkinlik"] == "tiktok işi"
    assert surec.durum(conn)["etkinlik"] == ""
