#!/usr/bin/env python3
"""tanto-browser — минимальный браузер: сайдбар-вкладки, адреска снизу, zen."""
import json
import os
import re
import sqlite3
import sys
import time

from PyQt6.QtCore import (QPoint, QRect, QSize, Qt, QTimer, QUrl, pyqtSignal)
from PyQt6.QtGui import (QColor, QFontMetrics, QKeySequence, QPainter,
                         QShortcut)
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QMainWindow, QPushButton, QStackedWidget,
                             QStyle, QStyledItemDelegate, QVBoxLayout,
                             QWidget)
from PyQt6.QtWebEngineCore import (QWebEngineDownloadRequest, QWebEnginePage,
                                   QWebEngineProfile, QWebEngineScript,
                                   QWebEngineSettings,
                                   QWebEngineUrlRequestInfo,
                                   QWebEngineUrlRequestInterceptor)
from PyQt6.QtWebEngineWidgets import QWebEngineView

import adblock

APP_DIR = os.path.expanduser("~/.local/share/tanto-browser")
CFG_DIR = os.path.expanduser("~/.config/tanto-browser")
CFG_PATH = os.path.join(CFG_DIR, "config.json")
SEARCH = "https://duckduckgo.com/?q={}"
NEWTAB_URL = "tanto://new"
SIDEBAR_W = 230

# ── палитры: почти монохром + один акцент; режим задаётся в конфиге ──
THEMES = {
    "black": {
        "bg":      "#101014",
        "panel":   "#16161C",
        "border":  "#26262E",
        "hover":   "#1C1C24",
        "fg":      "#C8CCD4",
        "bright":  "#E8EAF0",
        "dim":     "#61656E",
        "accent":  "#E06C75",
    },
    "white": {
        "bg":      "#F7F7F9",
        "panel":   "#EFEFF3",
        "border":  "#DBDBE2",
        "hover":   "#E6E6EC",
        "fg":      "#3C4048",
        "bright":  "#101014",
        "dim":     "#9094A0",
        "accent":  "#E06C75",
    },
}
C = THEMES["black"]

MONO = "'JetBrainsMono Nerd Font', 'JetBrains Mono', monospace"


def build_qss() -> str:
    return f"""
* {{ font-family: {MONO}; font-size: 13px; }}
QMainWindow, QWidget {{ background: {C['bg']}; color: {C['fg']}; }}

QFrame#sidebar {{ background: {C['panel']}; border-right: 1px solid {C['border']}; }}
QPushButton#newtab {{ background: transparent; border: none; text-align: left;
    color: {C['dim']}; padding: 8px 14px; font-size: 12px; }}
QPushButton#newtab:hover {{ color: {C['bright']}; background: {C['hover']}; }}
QListWidget#tabs {{ background: {C['panel']}; border: none; outline: none; }}
QLabel.download {{ color: {C['dim']}; font-size: 11px; padding: 2px 14px; }}

QFrame#bottombar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; }}
QLineEdit#addr {{ background: transparent; border: none; padding: 6px 10px;
    color: {C['bright']}; selection-background-color: {C['border']}; }}
QLabel#progress {{ color: {C['accent']}; padding-right: 10px; font-size: 12px; }}
QLabel#adcount {{ color: {C['dim']}; padding-right: 10px; font-size: 12px; }}
QLabel#scheme {{ color: {C['accent']}; padding-left: 10px; font-size: 12px; }}

QListWidget#suggest {{ background: {C['panel']}; border: 1px solid {C['border']};
    border-bottom: none; outline: none; }}
QListWidget#suggest::item {{ padding: 6px 12px; color: {C['fg']};
    border: none; }}
QListWidget#suggest::item:selected {{ background: {C['border']};
    color: {C['bright']}; border-left: 2px solid {C['accent']}; }}

QFrame#findbar {{ background: {C['panel']}; border-top: 1px solid {C['border']}; }}
QLineEdit#find {{ background: transparent; border: none; padding: 5px 10px;
    color: {C['bright']}; selection-background-color: {C['border']}; }}
QLabel#findcount {{ color: {C['dim']}; padding-right: 10px; font-size: 12px; }}

QMenu {{ background: {C['panel']}; color: {C['fg']};
    border: 1px solid {C['border']}; padding: 4px 0; }}
QMenu::item {{ padding: 4px 18px; font-size: 12px; }}
QMenu::item:selected {{ background: {C['border']}; color: {C['bright']}; }}
QMenu::separator {{ height: 1px; background: {C['border']}; margin: 4px 0; }}

QScrollBar:vertical {{ background: transparent; width: 6px; }}
QScrollBar::handle:vertical {{ background: {C['border']}; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {C['dim']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {C['panel']}; color: {C['fg']};
    border: 1px solid {C['border']}; padding: 3px 6px; font-size: 12px; }}
"""


def build_newtab_html() -> str:
    return f"""<!doctype html><html><head><style>
html,body {{ height:100%; margin:0; background:{C['bg']};
  display:flex; align-items:center; justify-content:center;
  font-family:{MONO}; }}
span {{ color:{C['dim']}; font-size:28px; letter-spacing:.3em; }}
b {{ color:{C['accent']}; }}
</style></head><body><span>tanto<b>.</b></span></body></html>"""


def load_cfg() -> dict:
    try:
        with open(CFG_PATH) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def is_private_host(host: str) -> bool:
    """Локальный/приватный хост: RFC1918, loopback, localhost, .local/.lan."""
    if not host:
        return False
    if host == "localhost" or host.endswith((".local", ".lan")):
        return True
    m = re.fullmatch(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})", host)
    if not m:
        return False
    a, b, c, d = (int(x) for x in m.groups())
    if max(a, b, c, d) > 255:
        return False
    return (a == 10 or a == 127
            or (a == 192 and b == 168)
            or (a == 172 and 16 <= b <= 31))


def to_url(text: str) -> QUrl | None:
    t = text.strip()
    if not t:
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t) or re.match(
            r"^(mailto|tel|about|data|javascript|view-source|file|chrome|"
            r"tanto):", t):
        return QUrl(t)
    if " " not in t and ("." in t or t.startswith("localhost")):
        # локальные адреса (IP/localhost/.local/.lan) обычно без SSL — http
        host = t.split("/", 1)[0].split(":", 1)[0]
        scheme = "http" if is_private_host(host) else "https"
        return QUrl(f"{scheme}://{t}")
    q = QUrl.toPercentEncoding(t).data().decode()
    return QUrl(SEARCH.format(q))


# ── список вкладок: рисуем сами — акцентная черта, × по ховеру ────────
class TabDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def sizeHint(self, opt, idx):
        return QSize(0, 30)

    def paint(self, p: QPainter, opt, idx):
        r = opt.rect
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        hov = idx.row() == self.view.hover_row
        if sel:
            p.fillRect(r, QColor(C["border"]))
            p.fillRect(QRect(r.left(), r.top() + 7, 2, r.height() - 14),
                       QColor(C["accent"]))
        elif hov:
            p.fillRect(r, QColor(C["hover"]))
        fm: QFontMetrics = opt.fontMetrics
        pad_r = 30 if hov else 12
        tr = r.adjusted(14, 0, -pad_r, 0)
        p.setPen(QColor(C["bright"] if sel else C["fg"]))
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(idx.data() or "…",
                                 Qt.TextElideMode.ElideRight, tr.width()))
        if hov:
            cr = self.view.close_rect(r)
            p.setPen(QColor(C["accent"] if self.view.hover_close
                            else C["dim"]))
            p.drawText(cr, Qt.AlignmentFlag.AlignCenter, "×")


class TabList(QListWidget):
    closeRequested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setObjectName("tabs")
        self.hover_row = -1
        self.hover_close = False
        self.setMouseTracking(True)
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setItemDelegate(TabDelegate(self))
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    @staticmethod
    def close_rect(item_rect: QRect) -> QRect:
        return QRect(item_rect.right() - 26, item_rect.top(),
                     22, item_rect.height())

    def _update_hover(self, pos: QPoint):
        idx = self.indexAt(pos)
        row = idx.row() if idx.isValid() else -1
        close = row >= 0 and self.close_rect(
            self.visualRect(idx)).contains(pos)
        if (row, close) != (self.hover_row, self.hover_close):
            self.hover_row, self.hover_close = row, close
            self.viewport().update()

    def mouseMoveEvent(self, e):
        self._update_hover(e.position().toPoint())
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_row, self.hover_close = -1, False
        self.viewport().update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        idx = self.indexAt(pos)
        if idx.isValid():
            if e.button() == Qt.MouseButton.MiddleButton:
                self.closeRequested.emit(idx.row())
                return
            if e.button() == Qt.MouseButton.LeftButton and \
                    self.close_rect(self.visualRect(idx)).contains(pos):
                self.closeRequested.emit(idx.row())
                return
        super().mousePressEvent(e)


# ── страница: target=_blank и созданные окна уводим во вкладки ────────
class WebPage(QWebEnginePage):
    def __init__(self, profile, win, view):
        super().__init__(profile, view)
        self.win = win
        # в Qt6 certificateError — сигнал, не виртуальный метод
        self.certificateError.connect(self._on_cert_error)

    def createWindow(self, wtype):
        bg = wtype == QWebEnginePage.WebWindowType.WebBrowserBackgroundTab
        view = self.win.new_tab(switch=not bg)
        return view.page()

    def _on_cert_error(self, error):
        # самоподписанные сертификаты принимаем только для приватных хостов
        # (домашний лаб: Proxmox :8006 и пр.), публичные сайты — блокируем
        if is_private_host(error.url().host()):
            error.acceptCertificate()
        else:
            error.rejectCertificate()


# ── сетевой adblock: режем запросы к рекламным/трекерным доменам ──────
class AdBlockInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, engine, is_enabled, on_block):
        super().__init__()
        self.engine = engine
        self.is_enabled = is_enabled
        self.on_block = on_block

    def interceptRequest(self, info):
        if not self.is_enabled():
            return
        # верхнеуровневую навигацию не трогаем — иначе не открыть сайт
        if info.resourceType() == \
                QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMainFrame:
            return
        if self.engine.should_block(info.requestUrl().host()):
            info.block(True)
            self.on_block()


# ── тонкая полоска прогресса для zen-режима ───────────────────────────
class ProgressLine(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(2)
        self.value = 0
        self.hide()

    def set_value(self, v: int):
        self.value = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(C["bg"]))
        w = int(self.width() * self.value / 100)
        p.fillRect(0, 0, w, 2, QColor(C["accent"]))


# ── хот-зона у левого края: peek сайдбара, когда тот скрыт ────────────
class EdgePeek(QWidget):
    hovered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(5)
        self.setMouseTracking(True)

    def enterEvent(self, e):
        self.hovered.emit()


class Sidebar(QFrame):
    left = pyqtSignal()

    def leaveEvent(self, e):
        self.left.emit()
        super().leaveEvent(e)


# ── история посещений (sqlite) ────────────────────────────────────────
class History:
    def __init__(self, path: str):
        self.con = sqlite3.connect(path)
        self.con.execute(
            "CREATE TABLE IF NOT EXISTS history("
            "url TEXT PRIMARY KEY, title TEXT, visits INTEGER DEFAULT 1, "
            "last REAL)")
        self.con.commit()

    def add(self, url: str, title: str, ts: float):
        if not url or url.startswith(("tanto://", "about:")):
            return
        self.con.execute(
            "INSERT INTO history(url, title, visits, last) "
            "VALUES(?,?,1,?) ON CONFLICT(url) DO UPDATE SET "
            "visits = visits + 1, last = ?, title = ?",
            (url, title, ts, ts, title))
        self.con.commit()

    def match(self, text: str, limit: int = 5) -> list[tuple[str, str]]:
        like = f"%{text}%"
        rows = self.con.execute(
            "SELECT url, title FROM history WHERE url LIKE ? OR title LIKE ? "
            "ORDER BY visits DESC, last DESC LIMIT ?",
            (like, like, limit)).fetchall()
        return rows


# ── попап подсказок: выпадает ВВЕРХ над адресной строкой ──────────────
class SuggestPopup(QListWidget):
    chosen = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("suggest")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # адреска держит фокус
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.itemClicked.connect(
            lambda it: self.chosen.emit(it.data(Qt.ItemDataRole.UserRole)))
        self.hide()

    def fill(self, entries: list[tuple[str, str, str]]):
        """entries: (icon, display, value)."""
        self.clear()
        for icon, display, value in entries:
            it = QListWidgetItem(f"{icon}  {display}")
            it.setData(Qt.ItemDataRole.UserRole, value)
            self.addItem(it)
        if self.count():
            self.setCurrentRow(-1)
            self._place()
            self.show()
            self.raise_()
        else:
            self.hide()

    def _place(self):
        anchor = self.parent()._addr_anchor()
        row_h = 30
        h = min(self.count(), 8) * row_h + 2
        w = anchor.width()
        x = anchor.x()
        y = anchor.y() - h  # растём вверх от верхнего края адрески
        self.setGeometry(x, y, w, h)

    def move_sel(self, step: int):
        n = self.count()
        if not n:
            return
        cur = self.currentRow()
        nxt = 0 if cur < 0 and step > 0 else (n - 1 if cur < 0 else
                                              (cur + step) % n)
        self.setCurrentRow(nxt)

    def current_value(self):
        it = self.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None


# ── адресная строка со стрелочной навигацией по подсказкам ────────────
class AddressBar(QLineEdit):
    def __init__(self):
        super().__init__()
        self.popup: SuggestPopup | None = None

    def keyPressEvent(self, e):
        p = self.popup
        k = e.key()
        if p and p.isVisible():
            if k == Qt.Key.Key_Down:
                p.move_sel(1)
                return
            if k == Qt.Key.Key_Up:
                p.move_sel(-1)
                return
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                val = p.current_value()
                if val is not None:
                    self.setText(val)
        super().keyPressEvent(e)


# ── главное окно ──────────────────────────────────────────────────────
class TantoBrowser(QMainWindow):
    ad_ready = pyqtSignal()  # эмитится из фонового потока adblock

    def __init__(self, profile: QWebEngineProfile, cfg: dict):
        super().__init__()
        self.profile = profile
        self.cfg = cfg
        self.views: dict[int, QWebEngineView] = {}
        self._next_id = 0
        self.closed_urls: list[str] = []
        self.peeking = False
        self._zen_restore = None
        self._fs_restore = None
        self.history = History(os.path.join(APP_DIR, "history.db"))
        self.nam = QNetworkAccessManager(self)
        self._sugg_seq = 0
        self._sugg_timer = QTimer(self)
        self._sugg_timer.setSingleShot(True)
        self._sugg_timer.setInterval(160)
        self._sugg_timer.timeout.connect(self._fetch_search_suggest)

        # adblock: движок грузится/качает листы в фоне, старт не блокируется
        self.adblock_on = cfg.get("adblock", True)
        self.adblock = adblock.AdBlockEngine(
            os.path.join(APP_DIR, "adblock"),
            cosmetic=cfg.get("adblock_cosmetic", False))
        self.interceptor = AdBlockInterceptor(
            self.adblock, lambda: self.adblock_on, self._on_ad_blocked)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.ad_ready.connect(self._on_ad_ready)
        self._ad_dirty = False

        self.setWindowTitle("tanto")
        g = cfg.get("geometry", [1200, 800])
        self.resize(g[0], g[1])

        # сайдбар
        self.sidebar = Sidebar()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_W)
        self.sidebar.left.connect(self._peek_end)
        sv = QVBoxLayout(self.sidebar)
        sv.setContentsMargins(0, 4, 0, 6)
        sv.setSpacing(0)
        newtab_btn = QPushButton("＋  новая вкладка")
        newtab_btn.setObjectName("newtab")
        newtab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        newtab_btn.clicked.connect(lambda: self.new_tab())
        self.tabs = TabList()
        self.tabs.currentRowChanged.connect(self._on_row_changed)
        self.tabs.closeRequested.connect(self.close_tab)
        self.downloads_box = QVBoxLayout()
        self.downloads_box.setSpacing(0)
        sv.addWidget(newtab_btn)
        sv.addWidget(self.tabs, 1)
        sv.addLayout(self.downloads_box)

        # стек страниц
        self.stack = QStackedWidget()

        # нижняя панель: адреска + прогресс
        self.bottombar = QFrame()
        self.bottombar.setObjectName("bottombar")
        bh = QHBoxLayout(self.bottombar)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        self.scheme_lbl = QLabel("")
        self.scheme_lbl.setObjectName("scheme")
        self.addr = AddressBar()
        self.addr.setObjectName("addr")
        self.addr.setPlaceholderText("url или поиск…")
        self.addr.returnPressed.connect(self._navigate)
        self.addr.textEdited.connect(self._on_addr_edited)
        self.addr.editingFinished.connect(self._hide_suggest)
        self.adcount_lbl = QLabel("")
        self.adcount_lbl.setObjectName("adcount")
        self.adcount_lbl.setToolTip("adblock — Ctrl+Shift+A")
        self.progress_lbl = QLabel("")
        self.progress_lbl.setObjectName("progress")
        bh.addWidget(self.scheme_lbl)
        bh.addWidget(self.addr, 1)
        bh.addWidget(self.adcount_lbl)
        bh.addWidget(self.progress_lbl)

        # попап подсказок — плавающий оверлей-child окна, растёт вверх
        self.suggest = SuggestPopup(self)
        self.addr.popup = self.suggest
        self.suggest.chosen.connect(self._suggest_chosen)

        # find bar
        self.findbar = QFrame()
        self.findbar.setObjectName("findbar")
        fh = QHBoxLayout(self.findbar)
        fh.setContentsMargins(0, 0, 0, 0)
        self.find_edit = QLineEdit()
        self.find_edit.setObjectName("find")
        self.find_edit.setPlaceholderText("найти на странице…")
        self.find_edit.textChanged.connect(lambda t: self._find(t))
        self.find_edit.returnPressed.connect(lambda: self._find_step(1))
        self.find_count = QLabel("")
        self.find_count.setObjectName("findcount")
        fh.addWidget(self.find_edit, 1)
        fh.addWidget(self.find_count)
        self.findbar.hide()

        self.progress_line = ProgressLine()

        self.edge = EdgePeek()
        self.edge.hovered.connect(self._peek_start)
        self.edge.hide()

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        right.addWidget(self.stack, 1)
        right.addWidget(self.progress_line)
        right.addWidget(self.findbar)
        right.addWidget(self.bottombar)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.edge)
        root.addWidget(self.sidebar)
        root.addLayout(right, 1)
        self.setCentralWidget(central)

        self._shortcuts()
        self._apply_panels(cfg.get("sidebar", True),
                           cfg.get("bottombar", True))
        self._refresh_adcount()
        self.adblock.start(on_ready=self.ad_ready.emit)
        self._restore_session()

    # ── панели ────────────────────────────────────────────────────────
    def _apply_panels(self, side: bool, bottom: bool):
        self.cfg["sidebar"], self.cfg["bottombar"] = side, bottom
        self.peeking = False
        self.sidebar.setVisible(side)
        self.edge.setVisible(not side)
        self.bottombar.setVisible(bottom)

    def toggle_sidebar(self):
        self._apply_panels(not self.cfg["sidebar"], self.cfg["bottombar"])

    def toggle_bottombar(self):
        self._apply_panels(self.cfg["sidebar"], not self.cfg["bottombar"])

    def toggle_zen(self):
        if self.cfg["sidebar"] or self.cfg["bottombar"]:
            self._zen_restore = (self.cfg["sidebar"], self.cfg["bottombar"])
            self._apply_panels(False, False)
        else:
            side, bottom = self._zen_restore or (True, True)
            self._apply_panels(side, bottom)

    def _peek_start(self):
        if not self.cfg["sidebar"] and not self.peeking:
            self.peeking = True
            self.sidebar.show()
            self.edge.hide()

    def _peek_end(self):
        if self.peeking:
            self.peeking = False
            self.sidebar.hide()
            self.edge.show()

    def _peek_flash(self, ms=2500):
        if not self.cfg["sidebar"] and not self.peeking:
            self._peek_start()
            QTimer.singleShot(ms, self._peek_end)

    # ── вкладки ───────────────────────────────────────────────────────
    def new_tab(self, url: str | None = None, switch=True) -> QWebEngineView:
        vid = self._next_id
        self._next_id += 1
        view = QWebEngineView()
        page = WebPage(self.profile, self, view)
        view.setPage(page)
        self.views[vid] = view
        self.stack.addWidget(view)

        view.titleChanged.connect(lambda t, v=vid: self._on_title(v, t))
        view.urlChanged.connect(lambda u, v=vid: self._on_url(v, u))
        view.loadProgress.connect(lambda p, v=vid: self._on_progress(v, p))
        view.loadFinished.connect(lambda ok, v=vid: self._on_loaded(v, ok))
        page.fullScreenRequested.connect(self._on_fullscreen)

        item = QListWidgetItem("новая вкладка")
        item.setData(Qt.ItemDataRole.UserRole, vid)
        self.tabs.addItem(item)

        if url:
            view.setUrl(QUrl(url))
        else:
            view.setHtml(build_newtab_html(), QUrl(NEWTAB_URL))
        if switch:
            self.tabs.setCurrentItem(item)
            if not url:
                self.focus_addr()
        return view

    def close_tab(self, row: int):
        item = self.tabs.item(row)
        if item is None:
            return
        vid = item.data(Qt.ItemDataRole.UserRole)
        view = self.views.pop(vid)
        u = view.url().toString()
        if u and u != NEWTAB_URL:
            self.closed_urls.append(u)
        self.tabs.takeItem(row)
        self.stack.removeWidget(view)
        view.deleteLater()
        if self.tabs.count() == 0:
            self.new_tab()

    def close_current(self):
        self.close_tab(self.tabs.currentRow())

    def reopen_tab(self):
        if self.closed_urls:
            self.new_tab(self.closed_urls.pop())

    def cycle_tab(self, step: int):
        n = self.tabs.count()
        if n > 1:
            self.tabs.setCurrentRow((self.tabs.currentRow() + step) % n)

    def goto_tab(self, i: int):
        if i < self.tabs.count():
            self.tabs.setCurrentRow(i)

    def current_view(self) -> QWebEngineView | None:
        item = self.tabs.currentItem()
        if item is None:
            return None
        return self.views.get(item.data(Qt.ItemDataRole.UserRole))

    def _on_row_changed(self, row: int):
        view = self.current_view()
        if view is None:
            return
        self.stack.setCurrentWidget(view)
        self._sync_addr(view.url())
        self.setWindowTitle((view.title() or "tanto") + " — tanto")
        if not self.addr.hasFocus():
            view.setFocus()

    def _item_for(self, vid: int) -> QListWidgetItem | None:
        for i in range(self.tabs.count()):
            it = self.tabs.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == vid:
                return it
        return None

    def _is_current(self, vid: int) -> bool:
        it = self.tabs.currentItem()
        return it is not None and it.data(Qt.ItemDataRole.UserRole) == vid

    def _on_title(self, vid: int, title: str):
        it = self._item_for(vid)
        if it:
            it.setText(title or "…")
        if self._is_current(vid):
            self.setWindowTitle((title or "tanto") + " — tanto")

    def _on_url(self, vid: int, url: QUrl):
        if self._is_current(vid):
            self._sync_addr(url)

    def _on_progress(self, vid: int, p: int):
        if not self._is_current(vid):
            return
        loading = 0 < p < 100
        self.progress_lbl.setText(f"{p}%" if loading else "")
        self.progress_line.setVisible(loading and
                                      not self.bottombar.isVisible())
        self.progress_line.set_value(p)

    def _on_loaded(self, vid: int, ok: bool):
        self._on_progress(vid, 100)
        view = self.views.get(vid)
        if ok and view:
            self.history.add(view.url().toString(), view.title(), time.time())

    # ── адреска ───────────────────────────────────────────────────────
    def _sync_addr(self, url: QUrl):
        s = url.toString()
        if s == NEWTAB_URL or s == "about:blank":
            s = ""
        if not self.addr.hasFocus():
            self.addr.setText(s)
            self.addr.setCursorPosition(0)
        insecure = url.scheme() == "http"
        self.scheme_lbl.setText("⚠ http" if insecure else "")

    def _navigate(self):
        self.suggest.hide()
        url = to_url(self.addr.text())
        view = self.current_view()
        if url is None or view is None:
            return
        view.setUrl(url)
        view.setFocus()
        self._addr_overlay_end()

    def focus_addr(self):
        if not self.bottombar.isVisible():
            self.bottombar.show()  # временный оверлей, спрячем после Enter/Esc
        self.addr.setFocus()
        self.addr.selectAll()

    def _addr_overlay_end(self):
        if not self.cfg["bottombar"]:
            self.bottombar.hide()

    # ── подсказки в адресной строке ───────────────────────────────────
    def _addr_anchor(self) -> QRect:
        tl = self.addr.mapTo(self, QPoint(0, 0))
        return QRect(tl, self.addr.size())

    def _on_addr_edited(self, text: str):
        self._sugg_text = text.strip()
        if not self._sugg_text:
            self.suggest.hide()
            self._sugg_timer.stop()
            return
        self._sugg_hist = [
            ("↗", (title or url)[:70], url)
            for url, title in self.history.match(self._sugg_text, 5)]
        self._sugg_search = []
        self._refresh_suggest(from_user=True)
        self._sugg_timer.start()  # debounce сетевого запроса

    def _refresh_suggest(self, from_user: bool = False):
        # синхронный путь (from_user) вызывается только при наборе — фокус есть;
        # для позднего ответа сети проверяем фокус, чтобы не всплыть некстати
        if not getattr(self, "_sugg_text", ""):
            return
        if not from_user and not self.addr.hasFocus():
            return
        out, seen = [], set()
        for e in getattr(self, "_sugg_hist", []):
            if e[2] not in seen:
                seen.add(e[2])
                out.append(e)
        for s in getattr(self, "_sugg_search", []):
            if s not in seen:
                seen.add(s)
                out.append(("⌕", s, s))
        if not out:
            out = [("⌕", self._sugg_text, self._sugg_text)]
        self.suggest.fill(out[:8])

    def _fetch_search_suggest(self):
        t = getattr(self, "_sugg_text", "")
        if not t:
            return
        # не сливаем в поисковик то, что выглядит прямым адресом/внутренним IP
        host = t.split("/", 1)[0].split(":", 1)[0]
        if "://" in t or (" " not in t and ("." in t or is_private_host(host))):
            return
        # каждый запрос помечаем seq; старые ответы просто игнорируем — без
        # abort(), который синхронно эмитит finished и роняет обработчик
        self._sugg_seq += 1
        seq = self._sugg_seq
        q = QUrl.toPercentEncoding(t).data().decode()
        req = QNetworkRequest(
            QUrl(f"https://ac.duckduckgo.com/ac/?type=list&q={q}"))
        req.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, b"tanto")
        reply = self.nam.get(req)
        reply.finished.connect(
            lambda r=reply, s=seq: self._on_search_suggest(r, t, s))

    def _on_search_suggest(self, reply, t: str, seq: int):
        data = bytes(reply.readAll())
        reply.deleteLater()
        if seq != self._sugg_seq or t != getattr(self, "_sugg_text", ""):
            return  # ответ устарел — пришёл новый запрос или сменился текст
        try:
            j = json.loads(data.decode("utf-8", "replace"))
            sugg = j[1] if isinstance(j, list) and len(j) > 1 else []
        except (ValueError, IndexError):
            sugg = []
        self._sugg_search = [s for s in sugg if isinstance(s, str)][:6]
        self._refresh_suggest()

    def _suggest_chosen(self, value: str):
        self.addr.setText(value)
        self._navigate()

    def _hide_suggest(self):
        self.suggest.hide()

    # ── adblock ───────────────────────────────────────────────────────
    def _on_ad_blocked(self):
        # зовётся очень часто — только копим счётчик, UI обновляем по таймеру
        self.adblock.blocked_count += 1
        if not self._ad_dirty:
            self._ad_dirty = True
            QTimer.singleShot(400, self._refresh_adcount)

    def _refresh_adcount(self):
        self._ad_dirty = False
        if not self.adblock_on:
            self.adcount_lbl.setText("⦸ off")
        elif not self.adblock.ready:
            self.adcount_lbl.setText("⦸ …")
        else:
            self.adcount_lbl.setText(f"⦸ {self.adblock.blocked_count}")

    def _on_ad_ready(self):
        self._refresh_adcount()
        if self.adblock.want_cosmetic and self.adblock.cosmetic_css:
            self._inject_cosmetic()

    def _inject_cosmetic(self):
        js = (
            "(function(){var s=document.createElement('style');"
            "s.textContent=%s;"
            "(document.head||document.documentElement).appendChild(s);"
            "})();" % json.dumps(self.adblock.cosmetic_css))
        script = QWebEngineScript()
        script.setName("tanto-cosmetic")
        script.setInjectionPoint(
            QWebEngineScript.InjectionPoint.DocumentReady)
        script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
        script.setRunsOnSubFrames(True)
        script.setSourceCode(js)
        scripts = self.profile.scripts()
        for s in scripts.find("tanto-cosmetic"):
            scripts.remove(s)
        scripts.insert(script)

    def toggle_adblock(self):
        self.adblock_on = not self.adblock_on
        self._refresh_adcount()

    # ── поиск по странице ─────────────────────────────────────────────
    def toggle_find(self):
        if self.findbar.isVisible():
            self._find_close()
        else:
            self.findbar.show()
            self.find_edit.setFocus()
            self.find_edit.selectAll()

    def _find(self, text: str, flags=QWebEnginePage.FindFlag(0)):
        view = self.current_view()
        if view is None:
            return
        view.page().findText(text, flags, self._find_result)

    def _find_step(self, direction: int):
        flags = (QWebEnginePage.FindFlag.FindBackward
                 if direction < 0 else QWebEnginePage.FindFlag(0))
        self._find(self.find_edit.text(), flags)

    def _find_result(self, r):
        n, a = r.numberOfMatches(), r.activeMatch()
        self.find_count.setText(f"{a}/{n}" if n else
                                ("нет" if self.find_edit.text() else ""))

    def _find_close(self):
        view = self.current_view()
        if view:
            view.page().findText("")
            view.setFocus()
        self.find_count.setText("")
        self.findbar.hide()

    # ── esc: закрыть find / оверлей адрески / выйти из fullscreen ─────
    def _escape(self):
        if self.suggest.isVisible():
            self.suggest.hide()
        elif self.findbar.isVisible():
            self._find_close()
        elif self.addr.hasFocus():
            view = self.current_view()
            if view:
                self._sync_addr(view.url())
                view.setFocus()
            self._addr_overlay_end()

    # ── загрузки ──────────────────────────────────────────────────────
    def on_download(self, dl: QWebEngineDownloadRequest):
        dl.setDownloadDirectory(os.path.expanduser("~/Downloads"))
        dl.accept()
        lbl = QLabel()
        lbl.setProperty("class", "download")
        lbl.setStyleSheet(f"color:{C['dim']}; font-size:11px; "
                          f"padding:2px 14px;")
        self.downloads_box.addWidget(lbl)
        name = dl.downloadFileName()
        short = name if len(name) <= 22 else name[:19] + "…"

        def upd():
            total = dl.totalBytes()
            if total > 0:
                pct = int(dl.receivedBytes() * 100 / total)
                lbl.setText(f"↓ {short}  <span style='color:{C['accent']}'>"
                            f"{pct}%</span>")

        def fin():
            state = dl.state()
            ok = state == QWebEngineDownloadRequest.DownloadState \
                .DownloadCompleted
            lbl.setText(f"↓ {short}  {'✓' if ok else '✗'}")
            QTimer.singleShot(4000, lbl.deleteLater)

        lbl.setText(f"↓ {short}")
        dl.receivedBytesChanged.connect(upd)
        dl.isFinishedChanged.connect(fin)
        self._peek_flash()

    # ── fullscreen (видео) ────────────────────────────────────────────
    def _on_fullscreen(self, request):
        request.accept()
        if request.toggleOn():
            self._fs_restore = (self.cfg["sidebar"], self.cfg["bottombar"],
                                self.isMaximized())
            self._apply_panels(False, False)
            self.showFullScreen()
        else:
            side, bottom, maxed = self._fs_restore or (True, True, False)
            self._apply_panels(side, bottom)
            self.showMaximized() if maxed else self.showNormal()

    # ── хоткеи ────────────────────────────────────────────────────────
    def _shortcuts(self):
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.ShortcutContext.WindowShortcut)
            s.activated.connect(fn)

        sc("Ctrl+T", lambda: self.new_tab())
        sc("Ctrl+W", self.close_current)
        sc("Ctrl+Shift+T", self.reopen_tab)
        sc("Ctrl+Tab", lambda: self.cycle_tab(1))
        sc("Ctrl+Shift+Tab", lambda: self.cycle_tab(-1))
        for i in range(1, 9):
            sc(f"Ctrl+{i}", lambda i=i: self.goto_tab(i - 1))
        sc("Ctrl+9", lambda: self.goto_tab(self.tabs.count() - 1))
        sc("Ctrl+L", self.focus_addr)
        sc("Ctrl+F", self.toggle_find)
        sc("Ctrl+R", lambda: self._view_do("reload"))
        sc("F5", lambda: self._view_do("reload"))
        sc("Alt+Left", lambda: self._view_do("back"))
        sc("Alt+Right", lambda: self._view_do("forward"))
        sc("Ctrl+B", self.toggle_sidebar)
        sc("Ctrl+Shift+B", self.toggle_bottombar)
        sc("Ctrl+Shift+Z", self.toggle_zen)
        sc("Ctrl+Shift+A", self.toggle_adblock)
        sc("Ctrl+=", lambda: self._zoom(0.1))
        sc("Ctrl+-", lambda: self._zoom(-0.1))
        sc("Ctrl+0", lambda: self._zoom(None))
        sc("Ctrl+Q", self.close)
        sc("Escape", self._escape)
        sc("F3", lambda: self._find_step(1))
        sc("Shift+F3", lambda: self._find_step(-1))

    def _view_do(self, action: str):
        view = self.current_view()
        if view:
            getattr(view, action)()

    def _zoom(self, delta):
        view = self.current_view()
        if view:
            view.setZoomFactor(1.0 if delta is None else
                               max(0.3, min(3.0, view.zoomFactor() + delta)))

    # ── сессия ────────────────────────────────────────────────────────
    def _restore_session(self):
        urls = self.cfg.get("tabs", [])
        if urls:
            for u in urls:
                self.new_tab(u, switch=False)
            self.tabs.setCurrentRow(
                min(self.cfg.get("active", 0), self.tabs.count() - 1))
        else:
            self.new_tab()

    def closeEvent(self, e):
        tabs = []
        for i in range(self.tabs.count()):
            vid = self.tabs.item(i).data(Qt.ItemDataRole.UserRole)
            u = self.views[vid].url().toString()
            if u and u != NEWTAB_URL and u != "about:blank":
                tabs.append(u)
        self.cfg.update({
            "tabs": tabs,
            "active": self.tabs.currentRow(),
            "geometry": [self.width(), self.height()],
            "adblock": self.adblock_on,
        })
        os.makedirs(CFG_DIR, exist_ok=True)
        with open(CFG_PATH, "w") as f:
            json.dump(self.cfg, f, indent=2)
        super().closeEvent(e)


def main():
    global C
    cfg = load_cfg()
    cfg.setdefault("theme", "black")
    C = THEMES.get(cfg["theme"], THEMES["black"])

    # сообщаем сайтам предпочитаемую схему через prefers-color-scheme.
    # Blink читает это из --blink-settings=preferredColorScheme (0=dark,1=light);
    # флаг должен быть выставлен до создания QApplication.
    scheme = 1 if cfg["theme"] == "white" else 0
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        f"{flags} --blink-settings=preferredColorScheme={scheme}").strip()

    app = QApplication(sys.argv)
    app.setApplicationName("tanto-browser")
    app.setDesktopFileName("tanto-browser")
    app.setStyleSheet(build_qss())

    os.makedirs(APP_DIR, exist_ok=True)
    profile = QWebEngineProfile("tanto", app)
    profile.setPersistentStoragePath(os.path.join(APP_DIR, "storage"))
    profile.setCachePath(os.path.join(APP_DIR, "cache"))
    profile.setPersistentCookiesPolicy(
        QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
    s = profile.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled,
                   True)
    s.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled,
                   True)

    if "--import-helium" in sys.argv:
        import import_helium
        cookies = import_helium.read_cookies()
        if not cookies:
            print("Helium: профиль/куки не найдены —",
                  import_helium.COOKIE_DB)
            sys.exit(1)

        def done(n):
            print(f"Импортировано кук из Helium: {n} из {len(cookies)}")
            app.quit()

        page = import_helium.inject(profile, cookies, done)
        _ = page  # держим ссылку, чтобы страницу не собрал GC
        print(f"Заливаю {len(cookies)} кук в tanto…")
        sys.exit(app.exec())

    win = TantoBrowser(profile, cfg)
    profile.downloadRequested.connect(win.on_download)

    for arg in sys.argv[1:]:
        if not arg.startswith("-"):
            win.new_tab(to_url(arg).toString())

    win.show()
    if "--smoke" in sys.argv:
        QTimer.singleShot(4000, app.quit)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
