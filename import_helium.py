#!/usr/bin/env python3
"""Импорт кук из профиля Helium (Chromium) в cookie-store tanto-browser.

Helium на Linux шифрует куки AES-128-CBC с ключом из пароля "peanuts"
(basic-хранилище, без keyring). Расшифровываем и отдаём как QNetworkCookie.
"""
import os
import shutil
import sqlite3
import tempfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

HELIUM_DIR = os.path.expanduser("~/.config/net.imput.helium")
COOKIE_DB = os.path.join(HELIUM_DIR, "Default", "Cookies")
CHROME_EPOCH_OFFSET = 11644473600  # секунд между 1601-01-01 и 1970-01-01


def _key(password: bytes = b"peanuts") -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16,
                     salt=b"saltysalt", iterations=1)
    return kdf.derive(password)


def _decrypt(enc: bytes, key: bytes) -> str | None:
    if not enc.startswith(b"v10"):
        return None
    ct = enc[3:]
    if len(ct) % 16:
        return None
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    pad = pt[-1]
    if pad < 1 or pad > 16:
        return None
    pt = pt[:-pad]
    # новый Chromium добавляет 32-байтный SHA256(host) перед значением
    return pt[32:].decode("utf-8", "replace")


def read_cookies(db_path: str = COOKIE_DB) -> list[dict]:
    """Список расшифрованных кук; пустой, если профиль Helium не найден."""
    if not os.path.exists(db_path):
        return []
    tmp = tempfile.mktemp(suffix=".cookies")
    shutil.copy(db_path, tmp)
    out = []
    try:
        con = sqlite3.connect(tmp)
        cur = con.cursor()
        rows = cur.execute(
            "SELECT host_key, name, value, encrypted_value, path, "
            "expires_utc, is_secure, is_httponly, samesite "
            "FROM cookies")
        key = _key()
        for host, name, value, enc, path, expires, secure, httponly, ss \
                in rows:
            if enc:
                val = _decrypt(bytes(enc), key)
                if val is None:
                    continue
            else:
                val = value
            out.append({
                "host": host, "name": name, "value": val, "path": path,
                "expires": expires, "secure": bool(secure),
                "httponly": bool(httponly), "samesite": ss,
            })
        con.close()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return out


def _push(store, cookies: list[dict]) -> int:
    from PyQt6.QtCore import QDateTime, QUrl
    from PyQt6.QtNetwork import QNetworkCookie

    ss_map = {
        0: QNetworkCookie.SameSite.None_,
        1: QNetworkCookie.SameSite.Lax,
        2: QNetworkCookie.SameSite.Strict,
    }
    count = 0
    for c in cookies:
        ck = QNetworkCookie(c["name"].encode(), c["value"].encode())
        ck.setDomain(c["host"])
        ck.setPath(c["path"] or "/")
        ck.setSecure(c["secure"])
        ck.setHttpOnly(c["httponly"])
        if c["samesite"] in ss_map:
            ck.setSameSitePolicy(ss_map[c["samesite"]])
        if c["expires"]:
            unix = c["expires"] / 1_000_000 - CHROME_EPOCH_OFFSET
            if unix > 0:
                ck.setExpirationDate(QDateTime.fromSecsSinceEpoch(int(unix)))
        host = c["host"].lstrip(".")
        scheme = "https" if c["secure"] else "http"
        store.setCookie(ck, QUrl(f"{scheme}://{host}/"))
        count += 1
    return count


def inject(profile, cookies: list[dict], done=None):
    """Заливает куки в cookie-store профиля.

    Cookie-store в QtWebEngine инициализируется лениво — только после первой
    навигации, поэтому сперва грузим about:blank скрытой страницей, а куки
    ставим в loadFinished. Требует запущенного Qt event loop; по завершении
    зовёт done(count). Возвращает QWebEnginePage — держи ссылку до конца.
    """
    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtWebEngineCore import QWebEnginePage

    store = profile.cookieStore()
    accepted = {"n": 0}
    store.cookieAdded.connect(lambda c: accepted.__setitem__(
        "n", accepted["n"] + 1))
    page = QWebEnginePage(profile)

    def on_load(ok):
        _push(store, cookies)
        if done:
            # ждём, пока стор прожуёт очередь и сбросит на диск
            QTimer.singleShot(3000, lambda: done(accepted["n"]))

    page.loadFinished.connect(on_load)
    page.setUrl(QUrl("about:blank"))
    return page
