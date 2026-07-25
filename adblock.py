#!/usr/bin/env python3
"""Сетевой adblock для tanto-browser.

QtWebEngine не запускает Chromium-расширения (нет WebExtensions API), поэтому
uBlock/AdGuard как .crx подключить нельзя. Но оба движка работают на фильтр-
листах в синтаксисе Adblock Plus — их и используем. Полноценный ABP-движок на
чистом Python неприемлемо медленный (~28 мс/запрос у adblockparser), поэтому
берём быстрый доменный слой: из правил вида `||domain^` строим множество и
матчим по доменным меткам за O(меток) — ~0.0014 мс/запрос, near-zero ложных
срабатываний. Плюс опциональная generic-косметика (скрытие `##selector`).
"""
import json
import os
import re
import threading
import time
import urllib.request

# uBO-дефолты (EasyList/EasyPrivacy/Peter Lowe) + AdGuard Base/Tracking
DEFAULT_LISTS = {
    "easylist": "https://easylist.to/easylist/easylist.txt",
    "easyprivacy": "https://easylist.to/easylist/easyprivacy.txt",
    "peterlowe": "https://pgl.yoyo.org/adservers/serverlist.php"
                 "?hostformat=adblockplus&mimetype=plaintext",
    "adguard-base": "https://filters.adtidy.org/extension/ublock/filters/2.txt",
    "adguard-tracking":
        "https://filters.adtidy.org/extension/ublock/filters/3.txt",
    "adguard-russian":
        "https://filters.adtidy.org/extension/ublock/filters/1.txt",
}
REFRESH_DAYS = 7

_DOMAIN_RULE = re.compile(r'^(@@)?\|\|([a-z0-9][a-z0-9.-]*)\^(?:\$(.*))?$')
_COSMETIC_SKIP = (":has(", ":has-text(", ":matches-", ":style(", ":remove(",
                  ":upward(", ":xpath(", ":-abp-", ":watch-attr", "[-ext-",
                  ":min-text-length", "+js(")
_SEL_OK = re.compile(r'^[a-zA-Z0-9 .#>+~*_:()\[\]="\'^$|,-]+$')


class AdBlockEngine:
    def __init__(self, cache_dir: str, lists: dict | None = None,
                 cosmetic: bool = False):
        self.dir = cache_dir
        self.lists = lists or DEFAULT_LISTS
        self.want_cosmetic = cosmetic
        self.block: set[str] = set()
        self.allow: set[str] = set()
        self.cosmetic_css = ""
        self.blocked_count = 0
        self.ready = False
        os.makedirs(self.dir, exist_ok=True)

    # ── матчинг ────────────────────────────────────────────────────────
    def should_block(self, host: str) -> bool:
        if not host or not self.block:
            return False
        parts = host.split(".")
        for i in range(len(parts) - 1):
            d = ".".join(parts[i:])
            if d in self.allow:
                return False
            if d in self.block:
                return True
        return False

    # ── парсинг кеша ──────────────────────────────────────────────────
    def _parse_file(self, path, block, allow, cosmetic):
        try:
            f = open(path, encoding="utf-8", errors="replace")
        except OSError:
            return
        with f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line[0] == "!" or line[0] == "[":
                    continue
                m = _DOMAIN_RULE.match(line)
                if m:
                    exc, dom, opts = m.group(1), m.group(2), m.group(3)
                    if exc:
                        # только БЕЗУСЛОВНЫЕ исключения дают blanket-allow;
                        # scoped `@@…$script,domain=…` разблокировали бы домен
                        # целиком — их пропускаем
                        if opts:
                            continue
                        allow.add(dom)
                    else:
                        # правило с domain=/негацией — не blanket-блок, пропуск
                        if opts and ("domain=" in opts or "~" in opts):
                            continue
                        block.add(dom)
                    continue
                if cosmetic is not None and line.startswith("##"):
                    sel = line[2:]
                    if any(t in sel for t in _COSMETIC_SKIP):
                        continue
                    if _SEL_OK.match(sel):
                        cosmetic.append(sel)

    def load(self):
        block, allow = set(), set()
        cosmetic = [] if self.want_cosmetic else None
        for name in self.lists:
            self._parse_file(os.path.join(self.dir, name + ".txt"),
                             block, allow, cosmetic)
        self.block, self.allow = block, allow
        if cosmetic:
            # по одному правилу на селектор: битый селектор гасит лишь себя
            self.cosmetic_css = "".join(
                s + "{display:none!important}" for s in cosmetic)
        self.ready = bool(block)

    # ── обновление листов ─────────────────────────────────────────────
    def _meta_path(self):
        return os.path.join(self.dir, "meta.json")

    def _stale(self) -> bool:
        try:
            meta = json.load(open(self._meta_path()))
            age = time.time() - meta.get("updated", 0)
            return age > REFRESH_DAYS * 86400
        except (OSError, ValueError):
            return True

    def _has_cache(self) -> bool:
        return all(os.path.exists(os.path.join(self.dir, n + ".txt"))
                   for n in self.lists)

    def _download(self):
        ok = False
        for name, url in self.lists.items():
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "tanto-browser"})
                data = urllib.request.urlopen(req, timeout=40).read()
                tmp = os.path.join(self.dir, name + ".txt.tmp")
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, os.path.join(self.dir, name + ".txt"))
                ok = True
            except Exception:
                continue  # недоступный лист просто пропускаем
        if ok:
            json.dump({"updated": time.time()}, open(self._meta_path(), "w"))

    def start(self, on_ready=None):
        """Грузит кеш и (при необходимости) качает листы — всё в фоне."""
        def worker():
            if self._has_cache():
                self.load()
                if on_ready:
                    on_ready()
            if not self._has_cache() or self._stale():
                self._download()
                self.load()
                if on_ready:
                    on_ready()
        threading.Thread(target=worker, daemon=True).start()
