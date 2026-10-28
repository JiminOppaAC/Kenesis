"""
Kinesis - fonds d'écran animés (vidéo, GIF, image) pour Windows, multi-écrans.
Optimisé pour les écrans ultrawide (ex : 3440x1440). Aucun son, aucun accès réseau.

Lancement :  python kinesis.py
Démarrage caché (barre système) :  python kinesis.py --tray
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import (
    QAbstractNativeEventFilter, QEvent, QLocale, QMimeData, QObject, QPoint, QRect,
    QRectF, QSize, Qt, QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QDrag, QFont, QFontDatabase, QFontMetrics, QIcon,
    QImage, QMovie, QPainter, QPainterPath, QPen, QPixmap, QRegion,
)
from PySide6.QtMultimedia import QMediaPlayer, QVideoFrame, QVideoSink
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QComboBox, QFileDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMenu, QPushButton, QScrollArea, QStyle,
    QStyledItemDelegate, QSystemTrayIcon, QToolButton, QVBoxLayout, QWidget,
)

try:
    from PySide6.QtSvg import QSvgRenderer
except Exception:          # QtSvg absent : les icônes seront simplement omises
    QSvgRenderer = None


# ============================================================================
# Chemins, ressources, configuration
# ============================================================================
def resource_path(*parts):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


ASSETS = resource_path("assets")


def find_asset(name):
    """Trouve un fichier de ressources, même si le dossier assets est rangé à plat."""
    for sub in ("", "fonts", "icons"):
        f = ASSETS / sub / name
        if f.exists():
            return f
    try:
        for f in ASSETS.rglob(name):
            return f
    except OSError:
        pass
    return None

_APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
APP_DIR = _APPDATA / "Kinesis"
OLD_APP_DIR = _APPDATA / "UltraWall"      # ancien nom du projet
LIB_DIR = APP_DIR / "library"
THUMB_DIR = APP_DIR / "thumbs"
CONFIG_FILE = APP_DIR / "config.json"

VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
GIF_EXT = {".gif"}
ALL_EXT = VIDEO_EXT | IMAGE_EXT | GIF_EXT


def migrate_from_ultrawall():
    """Reprend la bibliothèque et les réglages de l'ancien dossier UltraWall."""
    try:
        if OLD_APP_DIR.exists() and not APP_DIR.exists():
            OLD_APP_DIR.rename(APP_DIR)
    except OSError:
        pass


def load_config():
    cfg = {"screens": {}, "pause_fullscreen": True, "language": None}
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass
    if not isinstance(cfg.get("screens"), dict):
        cfg["screens"] = {}
    return cfg


def save_config(cfg):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ============================================================================
# Design
# ============================================================================
TEXT = "#696969"
LIGHT = "#B5B5B5"
LINE = "#dadada"
PANEL = "#f9f9f9"
# Écran 1 = bleu, 2 = rouge, 3 = jaune (puis 2 couleurs supplémentaires)
SCREEN_COLORS = ["#60a3bc", "#e55039", "#f6b93b", "#58b88a", "#9b7fc7"]
FRAME_OPACITY = 0.66          # cadres des écrans : couleur à ~66 % sur fond blanc
FONT_FAMILY = "Arvo"
TITLE_H = 40
PREVIEW_MAX = 180             # hauteur max d'un écran dans l'interface
PREVIEW_MIN = 100
CARD_MIN_W = 290
MIME_FILE = "application/x-kinesis-file"


def blend(hex_color, opacity, base=(255, 255, 255)):
    c = QColor(hex_color)
    return QColor(round(c.red() * opacity + base[0] * (1 - opacity)),
                  round(c.green() * opacity + base[1] * (1 - opacity)),
                  round(c.blue() * opacity + base[2] * (1 - opacity)))


def load_fonts():
    for name in ("Arvo-Regular.ttf", "Arvo-Bold.ttf"):
        f = find_asset(name)
        if f:
            QFontDatabase.addApplicationFont(str(f))


def build_qss():
    return f"""
* {{ font-family: "{FONT_FAMILY}"; }}
QWidget {{ color: {TEXT}; font-size: 14px; }}
QLabel#section {{ font-size: 13px; }}
QLabel#empty {{ color: {LIGHT}; }}
QToolTip {{ background: white; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 6px; }}

QMenu {{ background: white; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 14px; background: transparent; }}
QMenu::item:selected {{ background: #f0f0f0; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 6px; }}

QPushButton#btn {{ background: white; border: 1px solid {TEXT}; padding: 5px 16px; }}
QPushButton#btn:hover {{ background: #f3f3f3; }}
QPushButton#btn:pressed {{ background: #e9e9e9; }}
QPushButton#btn:disabled {{ color: {LIGHT}; border-color: {LIGHT}; }}
QPushButton#link {{ background: transparent; border: none; padding: 2px 6px;
                    text-decoration: underline; font-size: 13px; }}
QPushButton#link:hover {{ color: #333333; }}
QPushButton#lang {{ background: white; border: 1px solid {LIGHT}; padding: 3px 12px; }}
QPushButton#lang:checked {{ background: {SCREEN_COLORS[0]}; border-color: {SCREEN_COLORS[0]};
                            color: white; }}

QLineEdit#search, QLineEdit#nick {{ background: white; border: 1px solid {TEXT};
        padding: 4px 8px; selection-background-color: {SCREEN_COLORS[0]};
        selection-color: white; }}

QComboBox {{ background: white; border: 1px solid {TEXT}; padding: 4px 30px 4px 10px;
             min-height: 20px; }}
QComboBox:hover {{ background: #fafafa; }}
QComboBox::drop-down {{ border: none; width: 0px; }}
QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
QComboBox QAbstractItemView {{ background: white; border: 1px solid {TEXT}; outline: 0;
        selection-background-color: #eef5f8; selection-color: {TEXT}; padding: 2px; }}
QComboBox QAbstractItemView::item {{ min-height: 26px; padding-left: 8px; }}

QToolButton {{ background: transparent; border: none; padding: 4px; }}
QToolButton:hover {{ background: #f0f0f0; }}

QFrame#libpanel {{ background: {PANEL}; border-radius: 20px; }}
QListWidget {{ background: transparent; border: none; outline: 0; }}
QScrollArea {{ background: white; border: none; }}
QWidget#screens_inner {{ background: white; }}
QFrame#popup {{ background: white; border: 1px solid {LINE}; }}
QWidget#root {{ background: white; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LIGHT}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LIGHT}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""


# ============================================================================
# Langues (français / anglais)
# ============================================================================
STRINGS = {
    "fr": {
        "screens": "Écrans", "identify": "Identifier les écrans",
        "library": "Bibliothèque", "search": "Rechercher…",
        "sort_az": "Nom (A → Z)", "sort_za": "Nom (Z → A)",
        "sort_type": "Type (vidéo, GIF, image)",
        "add": "Ajouter", "delete": "Supprimer", "screen": "Écran",
        "adjust": "Ajustement :", "fill": "Remplir", "fit": "Ajuster", "stretch": "Étirer",
        "playing": "lecture", "paused": "pause",
        "nick_ph": "Surnom d'écran", "nick_tip": "Renommer l'écran",
        "options": "Options",
        "opt_autopause": "Pause automatique",
        "opt_autopause_tip": "Met les fonds en pause quand une appli est en plein écran "
                             "ou cache le bureau",
        "opt_autostart": "Lancer avec Windows", "opt_language": "Langue",
        "tray_open": "Ouvrir Kinesis", "tray_pause": "Pause", "tray_resume": "Reprendre",
        "tray_quit": "Quitter",
        "ctx_apply": "Appliquer sur {name}", "ctx_apply_all": "Appliquer sur tous les écrans",
        "ctx_remove_from": "Retirer de {name}", "ctx_delete": "Supprimer de la bibliothèque",
        "ctx_remove_bg": "Retirer le fond d'écran",
        "empty_library": "Ta bibliothèque est vide.\nClique sur « Ajouter » ou glisse ici "
                         "des vidéos, GIF et images.",
        "empty_search": "Aucun résultat.",
        "dlg_add": "Ajouter des fonds", "dlg_media": "Médias",
        "tip_badge": "Clic : mettre en pause / reprendre",
        "reason_manual": "En pause (manuel)",
        "reason_fs": "En pause : une application est en plein écran",
        "reason_cover": "En pause : cet écran est entièrement masqué",
        "reason_sleep": "En pause : veille, verrouillage ou écran éteint",
        "tip_min": "Réduire", "tip_max": "Agrandir", "tip_restore": "Restaurer",
        "tip_close": "Fermer (Kinesis reste actif dans la barre système)",
        "video_pending": "VIDÉO\naperçu…", "video_label": "VIDÉO",
    },
    "en": {
        "screens": "Screens", "identify": "Identify screens",
        "library": "Library", "search": "Search…",
        "sort_az": "Name (A → Z)", "sort_za": "Name (Z → A)",
        "sort_type": "Type (video, GIF, image)",
        "add": "Add", "delete": "Delete", "screen": "Screen",
        "adjust": "Fit:", "fill": "Fill", "fit": "Fit", "stretch": "Stretch",
        "playing": "playing", "paused": "paused",
        "nick_ph": "Screen nickname", "nick_tip": "Rename screen",
        "options": "Options",
        "opt_autopause": "Auto-pause",
        "opt_autopause_tip": "Pauses wallpapers when an app is fullscreen "
                             "or hides the desktop",
        "opt_autostart": "Start with Windows", "opt_language": "Language",
        "tray_open": "Open Kinesis", "tray_pause": "Pause", "tray_resume": "Resume",
        "tray_quit": "Quit",
        "ctx_apply": "Apply to {name}", "ctx_apply_all": "Apply to all screens",
        "ctx_remove_from": "Remove from {name}", "ctx_delete": "Delete from library",
        "ctx_remove_bg": "Remove wallpaper",
        "empty_library": "Your library is empty.\nClick “Add” or drop videos, "
                         "GIFs and images here.",
        "empty_search": "No results.",
        "dlg_add": "Add wallpapers", "dlg_media": "Media",
        "tip_badge": "Click: pause / resume",
        "reason_manual": "Paused (manual)",
        "reason_fs": "Paused: an application is fullscreen",
        "reason_cover": "Paused: this screen is completely covered",
        "reason_sleep": "Paused: sleep, lock or screen off",
        "tip_min": "Minimize", "tip_max": "Maximize", "tip_restore": "Restore",
        "tip_close": "Close (Kinesis keeps running in the system tray)",
        "video_pending": "VIDEO\npreview…", "video_label": "VIDEO",
    },
}
_lang = "fr"


def set_language(lang):
    global _lang
    _lang = lang if lang in STRINGS else "en"


def tr(key, **kw):
    s = STRINGS[_lang].get(key) or STRINGS["en"].get(key, key)
    return s.format(**kw) if kw else s


def detect_language():
    try:
        name = QLocale.system().name()
    except Exception:
        name = ""
    return "fr" if name.lower().startswith("fr") else "en"


# ============================================================================
# API Windows (ctypes)
# ============================================================================
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
wtsapi32 = ctypes.windll.wtsapi32
HWND = wintypes.HWND

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NCCALCSIZE_PARAMS(ctypes.Structure):
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


# GUID_CONSOLE_DISPLAY_STATE : {6FE69556-704A-47A0-8F24-C28D936FDA47}
GUID_CONSOLE_DISPLAY_STATE = GUID(
    0x6FE69556, 0x704A, 0x47A0,
    (ctypes.c_ubyte * 8)(0x8F, 0x24, 0xC2, 0x8D, 0x93, 0x6F, 0xDA, 0x47))

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = HWND
user32.FindWindowExW.argtypes = [HWND, HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = HWND
user32.SendMessageTimeoutW.argtypes = [
    HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.SetParent.argtypes = [HWND, HWND]
user32.SetParent.restype = HWND
user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.ScreenToClient.argtypes = [HWND, ctypes.POINTER(wintypes.POINT)]
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [HWND]
user32.IsIconic.argtypes = [HWND]
user32.IsZoomed.argtypes = [HWND]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
user32.MonitorFromRect.restype = wintypes.HMONITOR
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT),
                                       MONITORENUMPROC, wintypes.LPARAM]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, wintypes.UINT]
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterPowerSettingNotification.argtypes = [wintypes.HANDLE, ctypes.POINTER(GUID),
                                                    wintypes.DWORD]
user32.RegisterPowerSettingNotification.restype = wintypes.HANDLE
dwmapi.DwmGetWindowAttribute.argtypes = [HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmExtendFrameIntoClientArea.argtypes = [HWND, ctypes.POINTER(MARGINS)]
wtsapi32.WTSRegisterSessionNotification.argtypes = [HWND, wintypes.DWORD]
wtsapi32.WTSUnRegisterSessionNotification.argtypes = [HWND]

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_MAXIMIZE = 0x01000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_DISPLAYCHANGE = 0x007E
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_POWERSETTINGCHANGE = 0x8013
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

IGNORED_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "SHELLDLL_DefView", "NotifyIconOverflowWindow",
}


class Monitor:
    def __init__(self, device, rect, work, primary):
        self.device = device      # ex : \\.\DISPLAY1
        self.rect = rect          # zone complète (pixels physiques)
        self.work = work          # zone sans barre des tâches
        self.primary = primary
        m = re.search(r"(\d+)$", device)
        self.number = int(m.group(1)) if m else 0

    def signature(self):
        return (self.device, self.rect.x(), self.rect.y(), self.rect.width(),
                self.rect.height())


def list_monitors():
    mons = []

    def cb(hmon, hdc, lprc, lparam):
        mi = MONITORINFOEXW()
        mi.cbSize = ctypes.sizeof(mi)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            r, w = mi.rcMonitor, mi.rcWork
            mons.append(Monitor(
                mi.szDevice,
                QRect(r.left, r.top, r.right - r.left, r.bottom - r.top),
                QRect(w.left, w.top, w.right - w.left, w.bottom - w.top),
                bool(mi.dwFlags & 1)))
        return True

    proc = MONITORENUMPROC(cb)
    user32.EnumDisplayMonitors(None, None, proc, 0)
    mons.sort(key=lambda m: (m.number or 99, m.rect.x()))
    nums = [m.number for m in mons]
    if len(set(nums)) != len(nums) or 0 in nums:
        for i, m in enumerate(mons):
            m.number = i + 1
    return mons


def _find_old_workerw():
    """Windows 10 / 11 avant 24H2."""
    found = []

    def cb(hwnd, lparam):
        if user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
            w = user32.FindWindowExW(None, hwnd, "WorkerW", None)
            if w:
                found.append(w)
        return True

    proc = WNDENUMPROC(cb)
    user32.EnumWindows(proc, 0)
    return found[0] if found else None


def attach_to_desktop(hwnd, rect):
    """Place `hwnd` derrière les icônes du bureau, sur la zone `rect` (pixels physiques)."""
    progman = user32.FindWindowW("Progman", None)
    res = ctypes.c_size_t(0)
    user32.SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, 0, 1000, ctypes.byref(res))
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ctypes.byref(res))

    defview = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None)
    insert_after = None  # HWND_TOP
    if defview:
        # Windows 11 24H2+ : ordre (haut -> bas) : icônes / NOTRE FENÊTRE / WorkerW (fond Windows)
        parent = progman
        insert_after = defview
    else:
        parent = _find_old_workerw() or progman

    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    style = (style & ~WS_POPUP) | WS_CHILD
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
    user32.SetParent(hwnd, parent)

    pt = wintypes.POINT(rect.x(), rect.y())
    user32.ScreenToClient(parent, ctypes.byref(pt))
    user32.SetWindowPos(hwnd, insert_after, pt.x, pt.y, rect.width(), rect.height(),
                        SWP_NOACTIVATE | SWP_SHOWWINDOW)


def enable_native_frame(hwnd):
    """Fenêtre sans cadre Windows mais avec redimensionnement, ombre et ancrage (snap)."""
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    style |= WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    margins = MARGINS(1, 1, 1, 1)
    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def collect_windows(own_pid):
    """Liste (QRect, est_maximisée) des fenêtres visibles qui peuvent cacher le bureau."""
    wins = []

    def cb(hwnd, lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            if _class_name(hwnd) in IGNORED_CLASSES:
                return True
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if ex & (WS_EX_TOOLWINDOW | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE):
                return True
            cloaked = wintypes.DWORD(0)
            dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked),
                                         ctypes.sizeof(cloaked))
            if cloaked.value:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == own_pid:
                return True
            r = wintypes.RECT()
            if dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS,
                                            ctypes.byref(r), ctypes.sizeof(r)) != 0:
                user32.GetWindowRect(hwnd, ctypes.byref(r))
            rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
            if rect.width() <= 0 or rect.height() <= 0:
                return True
            style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            wins.append((rect, bool(style & WS_MAXIMIZE)))
        except Exception:
            pass
        return True

    proc = WNDENUMPROC(cb)
    user32.EnumWindows(proc, 0)
    return wins


def analyze_desktop(monitors):
    """
    Retourne (plein_ecran_quelque_part, {écrans dont le bureau est entièrement caché}).
      - plein écran : une fenêtre non maximisée couvre tout un écran (jeu, vidéo, F11...)
      - écran caché : les fenêtres visibles recouvrent toute la zone de travail de l'écran
    """
    wins = collect_windows(os.getpid())
    fullscreen_any = False
    covered = set()
    for m in monitors:
        full = m.rect.adjusted(2, 2, -2, -2)
        work = m.work.adjusted(2, 2, -2, -2)
        for rect, maximized in wins:
            if not maximized and rect.contains(full):
                fullscreen_any = True
        region = QRegion()
        for rect, _ in wins:
            inter = rect.intersected(work)
            if not inter.isEmpty():
                region = region.united(QRegion(inter))
        if QRegion(work).subtracted(region).isEmpty():
            covered.add(m.device)
    return fullscreen_any, covered


def refresh_desktop_wallpaper():
    """Restaure le fond d'écran Windows normal (appelé à la fermeture)."""
    user32.SystemParametersInfoW(20, 0, None, 3)  # SPI_SETDESKWALLPAPER


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _remove_old_autostart():
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_READ | winreg.KEY_SET_VALUE)
        try:
            winreg.QueryValueEx(key, "UltraWall")
            winreg.DeleteValue(key, "UltraWall")
            return True
        except OSError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


def get_autostart():
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, "Kinesis")
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def set_autostart(enable):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" --tray'
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                cmd = f'"{pythonw}" "{Path(__file__).resolve()}" --tray'
            winreg.SetValueEx(key, "Kinesis", 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, "Kinesis")
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


class SystemEventFilter(QAbstractNativeEventFilter):
    """Écoute les messages Windows (verrouillage, veille, écrans) sans rien bloquer."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def nativeEventFilter(self, eventType, message):
        try:
            msg = wintypes.MSG.from_address(int(message))
            self.callback(msg.message, int(msg.wParam or 0), int(msg.lParam or 0))
        except Exception:
            pass
        return False, 0


# ============================================================================
# Icônes et logo
# ============================================================================
_icon_cache = {}


def _fallback_icon(name, pm, w, h, scale):
    """Dessin de secours (couleur du texte) si le fichier SVG est introuvable ou illisible."""
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(scale, scale)
    col = QColor(TEXT)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(col)
    if name == "dropdown":
        tri = QPainterPath()
        tri.moveTo(w * 0.1, h * 0.28)
        tri.lineTo(w * 0.9, h * 0.28)
        tri.lineTo(w * 0.5, h * 0.78)
        tri.closeSubpath()
        p.drawPath(tri)
    elif name == "pen":
        p.setPen(QPen(col, 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPoint(int(w * 0.2), int(h * 0.8)), QPoint(int(w * 0.8), int(h * 0.2)))
        p.drawLine(QPoint(int(w * 0.1), int(h * 0.92)), QPoint(int(w * 0.35), int(h * 0.92)))
    elif name == "gear":
        cx, cy = w / 2, h / 2
        p.translate(cx, cy)
        for _ in range(8):
            p.drawRect(QRectF(-1.2, -h * 0.5, 2.4, h * 0.2))
            p.rotate(45)
        p.drawEllipse(QRectF(-w * 0.34, -w * 0.34, w * 0.68, w * 0.68))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.drawEllipse(QRectF(-w * 0.14, -w * 0.14, w * 0.28, w * 0.28))
    p.end()


def svg_pixmap(name, w, h, scale=3):
    """Rend une icône SVG en pixmap net (haute résolution), avec dessin de secours."""
    key = (name, w, h)
    if key in _icon_cache:
        return _icon_cache[key]
    pm = QPixmap(w * scale, h * scale)
    pm.fill(Qt.GlobalColor.transparent)
    done = False
    f = find_asset(f"{name}.svg")
    if QSvgRenderer is not None and f is not None:
        r = QSvgRenderer(str(f))
        if r.isValid():
            p = QPainter(pm)
            r.render(p, QRectF(0, 0, w * scale, h * scale))
            p.end()
            done = True
    if not done:
        _fallback_icon(name, pm, w, h, scale)
    pm.setDevicePixelRatio(scale)
    _icon_cache[key] = pm
    return pm


def logo_pixmap(height=22, scale=3):
    f = find_asset("logo.png")
    pm = QPixmap(str(f)) if f else QPixmap()
    if pm.isNull():
        return pm
    pm = pm.scaledToHeight(height * scale, Qt.TransformationMode.SmoothTransformation)
    pm.setDevicePixelRatio(scale)
    return pm


def make_app_icon() -> QIcon:
    for f in (find_asset("kinesis.ico"), resource_path("kinesis.ico"),
              find_asset("kinesis.png"), resource_path("kinesis.png")):
        if f is not None and f.exists():
            icon = QIcon(str(f))
            if not icon.isNull():
                return icon
    pm = QPixmap(64, 64)
    pm.fill(QColor(SCREEN_COLORS[0]))
    p = QPainter(pm)
    p.setPen(QColor("white"))
    p.setFont(QFont(FONT_FAMILY, 28, QFont.Weight.Bold))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "K")
    p.end()
    return QIcon(pm)


def make_search_icon() -> QIcon:
    pm = QPixmap(48, 48)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(TEXT), 4))
    p.drawEllipse(7, 7, 22, 22)
    p.drawLine(26, 26, 40, 40)
    p.end()
    return QIcon(pm)


# ============================================================================
# Affichage du fond d'écran (une fenêtre par écran)
# ============================================================================
VIDEO_ASPECT = {
    "fill": Qt.AspectRatioMode.KeepAspectRatioByExpanding,
    "fit": Qt.AspectRatioMode.KeepAspectRatio,
    "stretch": Qt.AspectRatioMode.IgnoreAspectRatio,
}


def _frame_from_image_supported():
    try:
        QVideoFrame(QImage(2, 2, QImage.Format.Format_RGBA8888))
        return True
    except Exception:
        return False


FRAME_FROM_IMAGE = _frame_from_image_supported()


class ImageView(QWidget):
    """Solution de secours : image ou GIF dessinés directement."""

    def __init__(self, path: Path, mode: str):
        super().__init__()
        self.mode = mode
        self.movie = None
        self.pixmap = QPixmap()
        if path.suffix.lower() in GIF_EXT:
            self.movie = QMovie(str(path))
            self.movie.frameChanged.connect(lambda _=0: self.update())
            self.movie.start()
        else:
            self.pixmap = QPixmap(str(path))

    def stop(self):
        if self.movie:
            self.movie.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pm = self.movie.currentPixmap() if self.movie else self.pixmap
        if not pm.isNull():
            draw_pixmap_mode(p, QRect(0, 0, self.width(), self.height()), pm, self.mode)


class FrameView(QVideoWidget):
    """
    Image fixe ou GIF animé affiché via QVideoWidget (même chemin d'affichage que les vidéos,
    qui s'affiche correctement derrière les icônes du bureau sous Windows 11 24H2).
    """

    def __init__(self, path: Path, mode: str):
        super().__init__()
        self.setAspectRatioMode(VIDEO_ASPECT[mode])
        self.setStyleSheet("background-color: black;")
        self.movie = None
        self._image = QImage()
        if path.suffix.lower() in GIF_EXT:
            self.movie = QMovie(str(path))
            self.movie.frameChanged.connect(self._on_movie_frame)
            self.movie.start()
        else:
            self._image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
        for delay in (0, 300, 1500):       # le composant vidéo peut ne pas être prêt au premier
            QTimer.singleShot(delay, self.push)

    def _on_movie_frame(self, _=0):
        self._image = self.movie.currentImage().convertToFormat(QImage.Format.Format_RGBA8888)
        self.push()

    def push(self):
        if self._image.isNull():
            return
        try:
            self.videoSink().setVideoFrame(QVideoFrame(self._image))
        except Exception:
            pass

    def stop(self):
        if self.movie:
            self.movie.stop()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(200, self.push)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(100, self.push)


class WallpaperWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Tool
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("background-color: black;")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._view = None
        self._video = None
        self._player = None
        self.has_media = False

    def clear(self):
        if self._player:
            self._player.stop()
            self._player.setVideoOutput(None)
            self._player.deleteLater()
            self._player = None
        if isinstance(self._view, (ImageView, FrameView)):
            self._view.stop()
        if self._view:
            self._lay.removeWidget(self._view)
            self._view.deleteLater()
            self._view = None
        self._video = None
        self.has_media = False

    def set_media(self, path: Path, mode: str):
        self.clear()
        if path.suffix.lower() in VIDEO_EXT:
            vw = QVideoWidget()
            vw.setAspectRatioMode(VIDEO_ASPECT[mode])
            vw.setStyleSheet("background-color: black;")
            player = QMediaPlayer(self)   # pas de sortie audio : lecture muette
            player.setVideoOutput(vw)
            player.setLoops(QMediaPlayer.Loops.Infinite)
            player.setSource(QUrl.fromLocalFile(str(path)))
            player.play()
            self._video, self._player, self._view = vw, player, vw
        elif FRAME_FROM_IMAGE:
            vw = FrameView(path, mode)
            self._video, self._view = vw, vw
        else:
            self._view = ImageView(path, mode)   # solution de secours
        self._lay.addWidget(self._view)
        self.has_media = True

    def set_mode(self, mode: str):
        if self._video:
            self._video.setAspectRatioMode(VIDEO_ASPECT[mode])
        elif isinstance(self._view, ImageView):
            self._view.mode = mode
            self._view.update()

    def set_paused(self, paused: bool):
        if self._player:
            self._player.pause() if paused else self._player.play()
        elif isinstance(self._view, (ImageView, FrameView)) and self._view.movie:
            self._view.movie.setPaused(paused)

    def place(self, rect: QRect):
        self.resize(rect.size())
        self.show()
        attach_to_desktop(int(self.winId()), rect)
        if isinstance(self._view, FrameView):
            QTimer.singleShot(400, self._view.push)


def draw_pixmap_mode(p, target: QRect, pm: QPixmap, mode: str):
    """Dessine `pm` dans `target` selon le mode : fill (recadre), fit (bandes), stretch."""
    p.save()
    p.setClipRect(target)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    W, H = target.width(), target.height()
    pw, ph = pm.width(), pm.height()
    if pw <= 0 or ph <= 0 or W <= 0 or H <= 0:
        p.restore()
        return
    if mode == "stretch":
        p.drawPixmap(QRectF(target), pm, QRectF(0, 0, pw, ph))
    elif mode == "fit":
        p.fillRect(target, QColor("black"))
        s = min(W / pw, H / ph)
        w, h = pw * s, ph * s
        p.drawPixmap(QRectF(target.x() + (W - w) / 2, target.y() + (H - h) / 2, w, h),
                     pm, QRectF(0, 0, pw, ph))
    else:  # fill
        s = max(W / pw, H / ph)
        sw, sh = W / s, H / s
        p.drawPixmap(QRectF(target), pm, QRectF((pw - sw) / 2, (ph - sh) / 2, sw, sh))
    p.restore()


class ScreenSlot:
    """Un écran physique + son fond d'écran + ses réglages."""

    def __init__(self, mon: Monitor, index: int, saved: dict):
        self.mon = mon
        self.index = index
        self.win = WallpaperWindow()
        self.file = None              # nom du fichier de la bibliothèque
        self.mode = saved.get("mode", "fill")
        if self.mode not in VIDEO_ASPECT:
            self.mode = "fill"
        self.nick = saved.get("nick", "") or ""
        self.manual = False           # pause demandée par l'utilisateur
        self.paused = False           # état réel de lecture
        self.reason = None            # None / manual / fs / cover / sleep

    @property
    def color_hex(self):
        return SCREEN_COLORS[self.index % len(SCREEN_COLORS)]

    @property
    def color(self):
        return QColor(self.color_hex)

    def show_file(self, path: Path):
        self.win.set_media(path, self.mode)
        self.win.place(self.mon.rect)
        self.file = path.name
        self.paused = False           # un nouveau média démarre en lecture

    def clear(self):
        self.win.clear()
        self.win.hide()
        self.file = None
        self.paused = False

    def suspend(self):
        """Libère tout (lecture, mémoire graphique) mais garde le fichier choisi."""
        self.win.clear()
        self.win.hide()
        self.paused = False

    def reload(self):
        """Recrée entièrement la fenêtre (utile après veille / redémarrage de l'Explorateur)."""
        old = self.win
        self.win = WallpaperWindow()
        old.clear()
        old.close()
        old.deleteLater()
        self.paused = False
        if self.file and (LIB_DIR / self.file).exists():
            self.show_file(LIB_DIR / self.file)

    def destroy(self):
        self.win.clear()
        self.win.close()
        self.win.deleteLater()


# ============================================================================
# Aperçus (miniatures)
# ============================================================================
TW, TH = 256, 108                 # taille des vignettes (format ~21:9)
NAME_ROLE = Qt.ItemDataRole.UserRole
THUMB_ROLE = Qt.ItemDataRole.UserRole + 1


def cover_image(img: QImage, w: int, h: int) -> QImage:
    s = img.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                   Qt.TransformationMode.SmoothTransformation)
    return s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)


def placeholder_pixmap(text: str) -> QPixmap:
    out = QPixmap(TW * 2, TH * 2)
    out.fill(QColor("#e9e9e9"))
    p = QPainter(out)
    p.setPen(QColor(TEXT))
    f = QFont(FONT_FAMILY)
    f.setPixelSize(26)
    f.setBold(True)
    p.setFont(f)
    p.drawText(out.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return out


class VideoThumbnailer(QObject):
    """Extrait une image d'une vidéo (une à la fois, en arrière-plan)."""
    ready = Signal(str, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = []
        self.current = None
        self.target = 0
        self.seeked = False
        self.player = QMediaPlayer(self)
        self.sink = QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self.on_frame)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.player.errorOccurred.connect(lambda *a: self.finish(QImage()))
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.finish(QImage()))

    def request(self, path: Path):
        p = str(path)
        if p == self.current or p in self.queue:
            return
        self.queue.append(p)
        self.next()

    def next(self):
        if self.current or not self.queue:
            return
        self.current = self.queue.pop(0)
        self.seeked = False
        self.player.setSource(QUrl.fromLocalFile(self.current))
        self.timer.start(8000)

    def on_status(self, status):
        if not self.current or self.seeked:
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            self.seeked = True
            dur = self.player.duration()
            self.target = min(max(dur // 10, 0), 5000)   # ~10 % de la vidéo, max 5 s
            if self.target:
                self.player.setPosition(self.target)
            self.player.play()

    def on_frame(self, frame):
        if not self.current or not self.seeked or not frame.isValid():
            return
        st = frame.startTime()
        if self.target and st >= 0 and st / 1000 < self.target - 200:
            return
        img = frame.toImage()
        if not img.isNull():
            self.finish(img)

    def finish(self, img):
        if not self.current:
            return
        path, self.current = self.current, None
        self.timer.stop()
        self.player.stop()
        self.ready.emit(path, img)
        QTimer.singleShot(0, self.next)


# ============================================================================
# Widgets du design Kinesis
# ============================================================================
class CaptionButton(QAbstractButton):
    """Boutons de la barre de titre : roue crantée, réduire, agrandir, fermer."""

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._hover = False
        self.setFixedSize(46, TITLE_H - 1)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        r = self.rect()
        close = self.kind == "close"
        if self._hover:
            p.fillRect(r, QColor(SCREEN_COLORS[1]) if close else QColor("#f0f0f0"))
        color = QColor("white") if (close and self._hover) else QColor(TEXT)
        cx, cy = r.center().x(), r.center().y()
        if self.kind == "gear":
            pm = svg_pixmap("gear", 16, 17)
            p.drawPixmap(QPoint(cx - 8, cy - 8), pm)
            p.setPen(QPen(QColor(LINE), 1))
            p.drawLine(0, 0, 0, r.height())
            p.drawLine(r.width() - 1, 0, r.width() - 1, r.height())
            return
        pen = QPen(color, 1)
        p.setPen(pen)
        if self.kind == "min":
            p.drawLine(cx - 5, cy, cx + 5, cy)
        elif self.kind == "max":
            p.drawRect(cx - 5, cy - 5, 10, 10)
        elif self.kind == "restore":
            p.drawRect(cx - 5, cy - 2, 8, 8)
            p.drawLine(cx - 2, cy - 5, cx + 5, cy - 5)
            p.drawLine(cx + 5, cy - 5, cx + 5, cy + 2)
            p.drawLine(cx - 2, cy - 5, cx - 2, cy - 2)
        elif close:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawLine(cx - 5, cy - 5, cx + 5, cy + 5)
            p.drawLine(cx - 5, cy + 5, cx + 5, cy - 5)


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedHeight(TITLE_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 0, 1)
        lay.setSpacing(0)
        self.logo = QLabel()
        self.logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.logo.setPixmap(logo_pixmap(22))
        lay.addWidget(self.logo)
        lay.addStretch(1)
        self.btn_gear = CaptionButton("gear")
        self.btn_min = CaptionButton("min")
        self.btn_max = CaptionButton("max")
        self.btn_close = CaptionButton("close")
        for b in (self.btn_gear, self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("white"))
        p.setPen(QPen(QColor(LINE), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    # Solution de secours si le déplacement natif (Windows) n'est pas actif
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_maximize()


class ToggleSwitch(QAbstractButton):
    """Interrupteur ON / OFF."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(58, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(SCREEN_COLORS[0] if on else LIGHT))
        p.drawRoundedRect(QRectF(self.rect()), 13, 13)
        d = 20
        x = self.width() - d - 3 if on else 3
        p.setBrush(QColor("white"))
        p.drawEllipse(x, 3, d, d)
        f = QFont(FONT_FAMILY)
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        text_rect = QRect(6, 0, 30, self.height()) if on else QRect(self.width() - 36, 0, 30, self.height())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "ON" if on else "OFF")


class ArrowCombo(QComboBox):
    """Liste déroulante au design Kinesis (flèche issue de dropdown_icon_app.svg)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setView(QListView())
        self.setItemDelegate(QStyledItemDelegate(self))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        super().paintEvent(e)
        pm = svg_pixmap("dropdown", 12, 12)
        p = QPainter(self)
        p.drawPixmap(QPoint(self.width() - 12 - 11, (self.height() - 12) // 2), pm)


class NickEdit(QLineEdit):
    cancelled = Signal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class PreviewFrame(QWidget):
    """Rectangle représentant un écran : cadre coloré, aperçu du fond, badge lecture/pause."""
    badgeClicked = Signal()
    fileDropped = Signal(str)
    removeRequested = Signal()

    def __init__(self, slot, main):
        super().__init__()
        self.slot = slot
        self.main = main
        self._hover = False
        self._drop = False
        self._badge = QRect()
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_menu)

    def border(self):
        return max(5, round(8 * self.height() / PREVIEW_MAX))

    def paintEvent(self, e):
        p = QPainter(self)
        rect = self.rect()
        b = self.border()
        inner = rect.adjusted(b, b, -b, -b)
        p.fillRect(rect, QColor("white"))
        pm = self.main.previews.get(self.slot.file) if self.slot.file else None
        if pm is not None and not pm.isNull():
            draw_pixmap_mode(p, inner, pm, self.slot.mode)
        fc = QColor(self.slot.color_hex) if self._drop else blend(self.slot.color_hex, FRAME_OPACITY)
        w, h = rect.width(), rect.height()
        p.fillRect(0, 0, w, b, fc)
        p.fillRect(0, h - b, w, b, fc)
        p.fillRect(0, b, b, h - 2 * b, fc)
        p.fillRect(w - b, b, b, h - 2 * b, fc)

        self._badge = QRect()
        if self._hover and self.slot.file:
            paused = self.slot.reason is not None
            text = tr("paused" if paused else "playing")
            f = QFont(FONT_FAMILY)
            f.setPixelSize(12)
            p.setFont(f)
            bw = 32 + QFontMetrics(f).horizontalAdvance(text) + 12
            bh = 24
            x = inner.right() - 14 - bw + 1
            y = inner.bottom() - 13 - bh + 1
            col = QColor(self.slot.color_hex)
            p.fillRect(QRect(x + 3, y + 3, bw, bh), blend(self.slot.color_hex, 0.45))   # ombre
            p.fillRect(QRect(x, y, bw, bh), col)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("white"))
            if paused:
                p.drawRect(x + 12, y + 7, 3, 10)
                p.drawRect(x + 18, y + 7, 3, 10)
            else:
                tri = QPainterPath()
                tri.moveTo(x + 12, y + 6)
                tri.lineTo(x + 12, y + 18)
                tri.lineTo(x + 21, y + 12)
                tri.closeSubpath()
                p.drawPath(tri)
            p.setPen(QColor("white"))
            p.drawText(QRect(x + 28, y, bw - 30, bh),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            self._badge = QRect(x, y, bw, bh)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseMoveEvent(self, e):
        over = (not self._badge.isNull()) and self._badge.contains(e.position().toPoint())
        self.setCursor(Qt.CursorShape.PointingHandCursor if over else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        if (e.button() == Qt.MouseButton.LeftButton and not self._badge.isNull()
                and self._badge.contains(e.position().toPoint())):
            self.badgeClicked.emit()

    def show_menu(self, pos):
        if not self.slot.file:
            return
        menu = QMenu(self)
        act = menu.addAction(tr("ctx_remove_bg"))
        act.triggered.connect(lambda _=False: self.removeRequested.emit())
        menu.exec(self.mapToGlobal(pos))

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME_FILE):
            e.acceptProposedAction()
            self._drop = True
            self.update()

    def dragLeaveEvent(self, e):
        self._drop = False
        self.update()

    def dropEvent(self, e):
        self._drop = False
        self.update()
        if e.mimeData().hasFormat(MIME_FILE):
            e.acceptProposedAction()
            self.fileDropped.emit(bytes(e.mimeData().data(MIME_FILE)).decode("utf-8"))


class ScreenCard(QWidget):
    """Un écran : aperçu, nom (modifiable) et ajustement."""

    def __init__(self, slot, main):
        super().__init__()
        self.slot = slot
        self.main = main
        self._editing = False
        self.aspect = max(0.5, slot.mon.rect.width() / max(1, slot.mon.rect.height()))

        self.frame = PreviewFrame(slot, main)
        self.frame.badgeClicked.connect(lambda: main.toggle_slot(slot))
        self.frame.fileDropped.connect(lambda name: main.apply_to_slots([slot], name))
        self.frame.removeRequested.connect(lambda: main.remove_from_slot(slot))

        self.num_label = QLabel()
        self.val_label = QLabel()
        self.nick_edit = NickEdit()
        self.nick_edit.setObjectName("nick")
        self.nick_edit.setFixedWidth(170)
        self.nick_edit.hide()
        self.nick_edit.editingFinished.connect(self.commit_edit)
        self.nick_edit.cancelled.connect(self.cancel_edit)
        self.edit_btn = QToolButton()
        self.edit_btn.setIcon(QIcon(svg_pixmap("pen", 10, 10)))
        self.edit_btn.setIconSize(QSize(11, 11))
        self.edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.edit_btn.clicked.connect(self.begin_edit)

        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name_row.addStretch(1)
        name_row.addWidget(self.num_label)
        name_row.addWidget(self.val_label)
        name_row.addWidget(self.nick_edit)
        name_row.addWidget(self.edit_btn)
        name_row.addStretch(1)

        self.adj_label = QLabel()
        self.combo = ArrowCombo()
        self.combo.setFixedWidth(198)
        self.fill_modes()
        self.combo.currentIndexChanged.connect(
            lambda _=0: main.on_mode(slot, self.combo.currentData()))
        adj_row = QHBoxLayout()
        adj_row.setSpacing(10)
        adj_row.addStretch(1)
        adj_row.addWidget(self.adj_label)
        adj_row.addWidget(self.combo)
        adj_row.addStretch(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.frame, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(name_row)
        lay.addLayout(adj_row)
        self.retranslate()

    def fill_modes(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        for key in ("fill", "fit", "stretch"):
            self.combo.addItem(tr(key), key)
        self.combo.setCurrentIndex(max(0, self.combo.findData(self.slot.mode)))
        self.combo.blockSignals(False)

    def set_height(self, h):
        pw = round(h * self.aspect)
        self.frame.setFixedSize(pw, h)
        self.setFixedWidth(max(pw, CARD_MIN_W))

    def retranslate(self):
        self.fill_modes()
        self.adj_label.setText(tr("adjust"))
        self.edit_btn.setToolTip(tr("nick_tip"))
        self.nick_edit.setPlaceholderText(tr("nick_ph"))
        self.refresh()

    def resolution_text(self):
        r = self.slot.mon.rect
        return f"{r.width()} x {r.height()}"

    def refresh(self):
        self.num_label.setText(f"<b>{tr('screen')} {self.slot.mon.number} :</b>")
        self.val_label.setText(self.slot.nick or self.resolution_text())
        self.val_label.setToolTip(self.resolution_text() if self.slot.nick else "")
        reason = self.slot.reason
        tip = ""
        if self.slot.file:
            tip = (tr("reason_" + reason) + "\n" if reason else "") + tr("tip_badge")
        self.frame.setToolTip(tip)
        self.frame.update()

    # --- surnom
    def begin_edit(self):
        self._editing = True
        self.val_label.hide()
        self.edit_btn.hide()
        self.nick_edit.setText(self.slot.nick)
        self.nick_edit.show()
        self.nick_edit.setFocus()
        self.nick_edit.selectAll()

    def _end_edit(self):
        self._editing = False
        self.nick_edit.hide()
        self.val_label.show()
        self.edit_btn.show()

    def commit_edit(self):
        if not self._editing:
            return
        self.slot.nick = self.nick_edit.text().strip()
        self._end_edit()
        self.main.save_state()
        self.main.refresh_views()

    def cancel_edit(self):
        if not self._editing:
            return
        self._end_edit()
        self.refresh()


class ScreensPanel(QScrollArea):
    """Zone qui affiche les écrans côte à côte (défilement horizontal si trop nombreux)."""

    def __init__(self, main):
        super().__init__()
        self.main = main
        self.cards = []
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner.setObjectName("screens_inner")
        self.setWidget(self.inner)
        self.lay = QHBoxLayout(self.inner)
        self.lay.setContentsMargins(0, 6, 0, 6)
        self.lay.setSpacing(70)
        self.setFixedHeight(PREVIEW_MAX + 10 + 24 + 10 + 34 + 24)

    def rebuild(self, slots):
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cards = []
        self.lay.addStretch(1)
        for s in slots:
            card = ScreenCard(s, self.main)
            self.cards.append(card)
            self.lay.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)
        self.lay.addStretch(1)
        self.relayout()

    def relayout(self):
        n = len(self.cards)
        if not n:
            return
        avail = self.viewport().width() - 10
        gap = self.lay.spacing()
        h = PREVIEW_MAX
        while h > PREVIEW_MIN:
            total = sum(max(round(h * c.aspect), CARD_MIN_W) for c in self.cards) + gap * (n - 1)
            if total <= avail:
                break
            h -= 6
        for c in self.cards:
            c.set_height(h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def refresh(self):
        for c in self.cards:
            c.refresh()

    def retranslate(self):
        for c in self.cards:
            c.retranslate()


class LibraryDelegate(QStyledItemDelegate):
    """Dessine chaque fond avec un cadre (et une pastille) par écran qui l'utilise."""
    PAD = 16

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner

    def sizeHint(self, option, index):
        return QSize(TW + 2 * self.PAD, TH + 2 * self.PAD + 26)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = option.rect
        name = index.data(NAME_ROLE)

        if option.state & QStyle.StateFlag.State_Selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#ececec"))
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 10, 10)

        thumb = QRect(r.x() + self.PAD, r.y() + self.PAD, TW, TH)
        pm = index.data(THUMB_ROLE)
        if pm:
            p.drawPixmap(thumb, pm)
        else:
            p.fillRect(thumb, QColor("#e9e9e9"))

        users = self.owner.users_of(name)   # [(numéro, couleur_hex), ...]

        # Cadres : un par écran, emboîtés si plusieurs écrans utilisent ce fond
        p.setBrush(Qt.BrushStyle.NoBrush)
        for i, (num, col) in enumerate(users):
            p.setPen(QPen(QBrush(blend(col, FRAME_OPACITY)), 4, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.FlatCap, Qt.PenJoinStyle.MiterJoin))
            d = 2 + 4 * i
            p.drawRect(QRectF(thumb).adjusted(-d, -d, d, d))

        # Pastilles numérotées en haut à gauche de l'aperçu
        f = QFont(FONT_FAMILY)
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        for i, (num, col) in enumerate(users):
            chip = QRect(thumb.x() + 8 + i * 30, thumb.y() + 8, 26, 26)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QBrush(QColor(col)))
            p.drawRoundedRect(chip, 6, 6)
            p.setPen(QColor("white"))
            p.drawText(chip, Qt.AlignmentFlag.AlignCenter, str(num))

        # Nom du fichier
        f2 = QFont(FONT_FAMILY)
        f2.setPixelSize(12)
        p.setFont(f2)
        p.setPen(QColor(TEXT))
        text = QFontMetrics(f2).elidedText(Path(name).stem, Qt.TextElideMode.ElideMiddle,
                                           r.width() - 16)
        p.drawText(QRect(r.x() + 8, thumb.bottom() + 14, r.width() - 16, 20),
                   Qt.AlignmentFlag.AlignCenter, text)
        p.restore()


class LibraryList(QListWidget):
    """Liste de la bibliothèque : les fonds peuvent être glissés sur un écran."""

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        name = item.data(NAME_ROLE)
        mime = QMimeData()
        mime.setData(MIME_FILE, name.encode("utf-8"))
        mime.setText(name)
        drag = QDrag(self)
        drag.setMimeData(mime)
        pm = item.data(THUMB_ROLE)
        if pm:
            small = pm.scaled(160, 68, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            drag.setPixmap(small)
            drag.setHotSpot(QPoint(small.width() // 2, small.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)


class IdentifyOverlay(QLabel):
    """Affiche brièvement le numéro de l'écran au milieu de celui-ci."""

    def __init__(self, slot: ScreenSlot):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background:{slot.color_hex}; color:white; border-radius:24px;")
        m = slot.mon
        self.setText(f"<div style='font-size:90pt; font-weight:bold'>{m.number}</div>"
                     f"<div style='font-size:16pt'>{m.rect.width()} x {m.rect.height()}</div>")
        w, h = 420, 320
        self.resize(w, h)
        self.show()
        x = m.rect.x() + (m.rect.width() - w) // 2
        y = m.rect.y() + (m.rect.height() - h) // 2
        user32.SetWindowPos(int(self.winId()), -1, x, y, w, h, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        QTimer.singleShot(2500, self.close)


class OptionsPopup(QFrame):
    """Panneau des options, ouvert par la roue crantée."""

    def __init__(self, main):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.main = main
        self.setObjectName("popup")

        self.lbl_auto = QLabel()
        self.tg_auto = ToggleSwitch()
        self.tg_auto.clicked.connect(main.on_auto_pause_opt)
        self.lbl_start = QLabel()
        self.tg_start = ToggleSwitch()
        self.tg_start.clicked.connect(main.on_autostart)
        self.lbl_lang = QLabel()
        self.b_fr = QPushButton("FR")
        self.b_en = QPushButton("EN")
        for b, code in ((self.b_fr, "fr"), (self.b_en, "en")):
            b.setObjectName("lang")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=code: main.change_language(c))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(16)
        for lbl, widgets in ((self.lbl_auto, [self.tg_auto]), (self.lbl_start, [self.tg_start]),
                             (self.lbl_lang, [self.b_fr, self.b_en])):
            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(lbl)
            row.addSpacing(30)
            row.addStretch(1)
            for w in widgets:
                row.addWidget(w)
            lay.addLayout(row)
        self.retranslate()

    def retranslate(self):
        self.lbl_auto.setText(tr("opt_autopause"))
        self.lbl_auto.setToolTip(tr("opt_autopause_tip"))
        self.lbl_start.setText(tr("opt_autostart"))
        self.lbl_lang.setText(tr("opt_language"))

    def refresh_state(self):
        self.tg_auto.setChecked(bool(self.main.cfg.get("pause_fullscreen", True)))
        try:
            self.tg_start.setChecked(get_autostart())
        except Exception:
            pass
        self.b_fr.setChecked(self.main.lang == "fr")
        self.b_en.setChecked(self.main.lang == "en")

    def open_below(self, anchor: QWidget):
        self.refresh_state()
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(anchor.width() - self.width(), anchor.height()))
        self.move(pos)
        self.show()


# ============================================================================
# Fenêtre principale
# ============================================================================
class MainWindow(QWidget):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.lang = cfg.get("language") or detect_language()
        set_language(self.lang)

        self.setObjectName("root")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowTitle("Kinesis")
        self.setWindowIcon(make_app_icon())
        self.resize(1000, 760)
        self.setMinimumSize(820, 640)
        self.setAcceptDrops(True)

        # --- État
        self.monitors = list_monitors()
        self.slots = [ScreenSlot(m, i, cfg["screens"].get(m.device, {}))
                      for i, m in enumerate(self.monitors)]
        self.fullscreen_any = False
        self.covered = set()
        self.suspended = False
        self.suspend_reasons = set()
        self.overlays = []
        self.files = []
        self.previews = {}     # nom -> QPixmap (aperçu complet, proportions d'origine)
        self.thumbs = {}       # nom -> QPixmap (vignette recadrée de la bibliothèque)
        self.items = {}
        self.thumbnailer = VideoThumbnailer(self)
        self.thumbnailer.ready.connect(self.on_thumb_ready)

        self.build_ui()
        self.build_tray()

        # --- Minuteries
        self.desktop_timer = QTimer(self)
        self.desktop_timer.timeout.connect(self.check_desktop)
        self.desktop_timer.start(1500)
        self.resume_timer = QTimer(self)
        self.resume_timer.setSingleShot(True)
        self.resume_timer.timeout.connect(self.finish_resume)
        self.display_timer = QTimer(self)
        self.display_timer.setSingleShot(True)
        self.display_timer.timeout.connect(lambda: self.refresh_monitors(force_reload=False))
        self.reattach_timer = QTimer(self)
        self.reattach_timer.setSingleShot(True)
        self.reattach_timer.timeout.connect(self.reload_wallpapers)

        self.screens_panel.rebuild(self.slots)
        self.retranslate()
        self.scan_library()
        self.rebuild_list()
        self.restore_wallpapers()
        self.update_pause()

        # --- Fenêtre sans cadre Windows (redimensionnable) + veille / verrouillage
        try:
            enable_native_frame(int(self.winId()))
        except Exception as e:
            print("Cadre natif :", e)
        self.register_system_events()

    # ---------------------------------------------------------------- Interface
    def build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.titlebar = TitleBar(self)
        self.titlebar.btn_gear.clicked.connect(self.open_options)
        self.titlebar.btn_min.clicked.connect(self.showMinimized)
        self.titlebar.btn_max.clicked.connect(self.toggle_maximize)
        self.titlebar.btn_close.clicked.connect(self.close)
        root.addWidget(self.titlebar)

        body = QVBoxLayout()
        body.setContentsMargins(24, 14, 24, 24)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # --- Écrans
        head1 = QHBoxLayout()
        self.lbl_screens = QLabel()
        self.lbl_screens.setObjectName("section")
        self.lbl_screens.setContentsMargins(6, 0, 0, 0)
        self.btn_identify = QPushButton()
        self.btn_identify.setObjectName("link")
        self.btn_identify.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_identify.clicked.connect(self.identify)
        head1.addWidget(self.lbl_screens)
        head1.addStretch(1)
        head1.addWidget(self.btn_identify)
        body.addLayout(head1)
        body.addSpacing(4)
        self.screens_panel = ScreensPanel(self)
        body.addWidget(self.screens_panel)
        body.addSpacing(18)

        # --- Bibliothèque : titre, recherche, tri, boutons
        head2 = QHBoxLayout()
        head2.setSpacing(8)
        self.lbl_library = QLabel()
        self.lbl_library.setObjectName("section")
        self.lbl_library.setContentsMargins(6, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setFixedWidth(210)
        self.search.addAction(make_search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(lambda _=None: self.rebuild_list())
        self.sort_combo = ArrowCombo()
        self.sort_combo.setFixedWidth(230)
        for key in ("az", "za", "type"):
            self.sort_combo.addItem(key, key)
        self.sort_combo.currentIndexChanged.connect(lambda _=0: self.rebuild_list())
        self.btn_add = QPushButton()
        self.btn_add.setObjectName("btn")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.clicked.connect(self.add_files)
        self.btn_del = QPushButton()
        self.btn_del.setObjectName("btn")
        self.btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del.clicked.connect(self.delete_selected)
        head2.addWidget(self.lbl_library)
        head2.addStretch(1)
        head2.addWidget(self.search)
        head2.addWidget(self.sort_combo)
        head2.addWidget(self.btn_add)
        head2.addWidget(self.btn_del)
        body.addLayout(head2)
        body.addSpacing(10)

        panel = QFrame()
        panel.setObjectName("libpanel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 14, 8, 14)
        self.list = LibraryList()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setGridSize(QSize(TW + 2 * LibraryDelegate.PAD + 8,
                                    TH + 2 * LibraryDelegate.PAD + 34))
        self.list.setItemDelegate(LibraryDelegate(self, self.list))
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.on_library_menu)
        self.list.itemDoubleClicked.connect(
            lambda it: self.apply_to_slots(self.slots, it.data(NAME_ROLE)))
        self.empty_label = QLabel()
        self.empty_label.setObjectName("empty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        pl.addWidget(self.list, 1)
        pl.addWidget(self.empty_label, 1)
        body.addWidget(panel, 1)

        self.popup = OptionsPopup(self)

    def retranslate(self):
        self.lbl_screens.setText(tr("screens"))
        self.btn_identify.setText(tr("identify"))
        self.lbl_library.setText(tr("library"))
        self.search.setPlaceholderText(tr("search"))
        self.sort_combo.blockSignals(True)
        for i, key in enumerate(("az", "za", "type")):
            self.sort_combo.setItemText(i, tr("sort_" + key))
        self.sort_combo.blockSignals(False)
        self.btn_add.setText(tr("add"))
        self.btn_del.setText(tr("delete"))
        self.titlebar.btn_gear.setToolTip(tr("options"))
        self.titlebar.btn_min.setToolTip(tr("tip_min"))
        self.titlebar.btn_close.setToolTip(tr("tip_close"))
        self.update_max_button()
        self.popup.retranslate()
        self.screens_panel.retranslate()
        if hasattr(self, "tray_open"):
            self.tray_open.setText(tr("tray_open"))
            self.tray_quit.setText(tr("tray_quit"))
        self.update_pause_texts()
        self.update_empty_state()

    def change_language(self, lang):
        self.lang = lang
        set_language(lang)
        self.cfg["language"] = lang
        save_config(self.cfg)
        self.retranslate()
        self.popup.refresh_state()

    # ---------------------------------------------------------------- Fenêtre
    def toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def update_max_button(self):
        b = self.titlebar.btn_max
        b.kind = "restore" if self.isMaximized() else "max"
        b.setToolTip(tr("tip_restore") if self.isMaximized() else tr("tip_max"))
        b.update()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:
            self.update_max_button()

    def open_options(self):
        self.popup.open_below(self.titlebar.btn_gear)

    def nativeEvent(self, eventType, message):
        """Cadre personnalisé : zone de déplacement, bords de redimensionnement, maximisation."""
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_NCCALCSIZE:
                if msg.wParam:
                    params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
                    if user32.IsZoomed(msg.hWnd):
                        mon = user32.MonitorFromRect(ctypes.byref(params.rgrc[0]), 2)
                        mi = MONITORINFOEXW()
                        mi.cbSize = ctypes.sizeof(mi)
                        if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                            wa, r0 = mi.rcWork, params.rgrc[0]
                            r0.left, r0.top, r0.right, r0.bottom = wa.left, wa.top, wa.right, wa.bottom
                return True, 0
            if msg.message == WM_NCHITTEST:
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                r = wintypes.RECT()
                user32.GetWindowRect(msg.hWnd, ctypes.byref(r))
                dpr = self.devicePixelRatioF()
                if not user32.IsZoomed(msg.hWnd):
                    bw = max(5, round(6 * dpr))
                    left, right = x - r.left < bw, r.right - x <= bw
                    top, bottom = y - r.top < bw, r.bottom - y <= bw
                    code = (HTTOPLEFT if top and left else HTTOPRIGHT if top and right else
                            HTBOTTOMLEFT if bottom and left else HTBOTTOMRIGHT if bottom and right else
                            HTLEFT if left else HTRIGHT if right else HTTOP if top else
                            HTBOTTOM if bottom else 0)
                    if code:
                        return True, code
                lx, ly = int((x - r.left) / dpr), int((y - r.top) / dpr)
                if 0 <= ly < TITLE_H:
                    child = self.childAt(QPoint(lx, ly))
                    if child is None or child is self.titlebar:
                        return True, HTCAPTION
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event):
        event.ignore()
        self.hide()   # reste actif dans la barre système

    def show_window(self):
        self.show()
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- Barre système
    def build_tray(self):
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        menu = QMenu()
        self.tray_open = QAction("", self)
        self.tray_open.triggered.connect(self.show_window)
        self.tray_pause = QAction("", self)
        self.tray_pause.triggered.connect(self.toggle_all)
        self.tray_quit = QAction("", self)
        self.tray_quit.triggered.connect(self.quit_app)
        menu.addAction(self.tray_open)
        menu.addAction(self.tray_pause)
        menu.addSeparator()
        menu.addAction(self.tray_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda r: self.show_window() if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.setToolTip("Kinesis")
        self.tray.show()
        self._tray_menu = menu

    # ---------------------------------------------------------------- Écrans
    def slot_label(self, slot):
        s = f"{tr('screen')} {slot.mon.number}"
        return f"{s} ({slot.nick})" if slot.nick else s

    def users_of(self, name):
        return [(s.mon.number, s.color_hex) for s in self.slots if s.file == name]

    def identify(self):
        self.overlays = [IdentifyOverlay(s) for s in self.slots]

    def on_mode(self, slot, mode):
        slot.mode = mode
        slot.win.set_mode(mode)
        self.save_state()
        self.refresh_views()

    def refresh_views(self):
        self.screens_panel.refresh()
        self.list.viewport().update()

    # ---------------------------------------------------------------- Configuration
    def save_state(self):
        for s in self.slots:
            self.cfg["screens"][s.mon.device] = {"file": s.file, "mode": s.mode, "nick": s.nick}
        save_config(self.cfg)

    def restore_wallpapers(self):
        for s in self.slots:
            name = self.cfg["screens"].get(s.mon.device, {}).get("file")
            if name and (LIB_DIR / name).exists():
                s.show_file(LIB_DIR / name)
        self.refresh_views()

    # ---------------------------------------------------------------- Bibliothèque
    def scan_library(self):
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        self.files = [f for f in LIB_DIR.iterdir() if f.suffix.lower() in ALL_EXT]

    @staticmethod
    def type_rank(path):
        ext = path.suffix.lower()
        return 0 if ext in VIDEO_EXT else 1 if ext in GIF_EXT else 2

    def preview_cache_file(self, path: Path) -> Path:
        st = path.stat()
        key = hashlib.md5(f"v3|{path.name}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
        return THUMB_DIR / f"{key}.png"

    def set_visuals(self, name, img, pending=False):
        if img.isNull():
            self.previews.pop(name, None)
            self.thumbs[name] = placeholder_pixmap(
                tr("video_pending" if pending else "video_label"))
            return
        prev = img if img.width() <= 640 else img.scaledToWidth(
            640, Qt.TransformationMode.SmoothTransformation)
        self.previews[name] = QPixmap.fromImage(prev)
        self.thumbs[name] = QPixmap.fromImage(cover_image(prev, TW * 2, TH * 2))

    def load_visuals(self, path: Path):
        ext = path.suffix.lower()
        img = QImage()
        if ext in IMAGE_EXT:
            img = QImage(str(path))
        elif ext in GIF_EXT:
            m = QMovie(str(path))
            m.jumpToFrame(0)
            img = m.currentImage()
        else:  # vidéo : aperçu en cache, sinon généré en arrière-plan
            cache = self.preview_cache_file(path)
            if cache.exists():
                img = QImage(str(cache))
            else:
                self.thumbnailer.request(path)
        self.set_visuals(path.name, img, pending=(ext in VIDEO_EXT and img.isNull()))

    def on_thumb_ready(self, path_str, img):
        path = Path(path_str)
        if img.isNull():
            self.set_visuals(path.name, QImage())
        else:
            prev = img if img.width() <= 640 else img.scaledToWidth(
                640, Qt.TransformationMode.SmoothTransformation)
            try:
                THUMB_DIR.mkdir(parents=True, exist_ok=True)
                prev.save(str(self.preview_cache_file(path)), "PNG")
            except OSError:
                pass
            self.set_visuals(path.name, prev)
        item = self.items.get(path.name)
        if item:
            item.setData(THUMB_ROLE, self.thumbs[path.name])
        self.refresh_views()

    def selected_name(self):
        it = self.list.currentItem()
        return it.data(NAME_ROLE) if it else None

    def rebuild_list(self):
        query = self.search.text().strip().lower()
        mode = self.sort_combo.currentData() or "az"
        files = [f for f in self.files if query in f.stem.lower()]
        if mode == "za":
            files.sort(key=lambda f: f.stem.lower(), reverse=True)
        elif mode == "type":
            files.sort(key=lambda f: (self.type_rank(f), f.stem.lower()))
        else:
            files.sort(key=lambda f: f.stem.lower())
        selected = self.selected_name()
        self.list.clear()
        self.items = {}
        for f in files:
            if f.name not in self.thumbs:
                self.load_visuals(f)
            it = QListWidgetItem()
            it.setData(NAME_ROLE, f.name)
            it.setData(THUMB_ROLE, self.thumbs[f.name])
            it.setToolTip(f.name)
            self.list.addItem(it)
            self.items[f.name] = it
            if f.name == selected:
                self.list.setCurrentItem(it)
        self.update_empty_state()

    def update_empty_state(self):
        has_items = self.list.count() > 0
        self.list.setVisible(has_items)
        self.empty_label.setVisible(not has_items)
        self.empty_label.setText(tr("empty_library") if not self.files else tr("empty_search"))

    def import_files(self, paths):
        LIB_DIR.mkdir(parents=True, exist_ok=True)
        for src in paths:
            src = Path(src)
            if src.suffix.lower() not in ALL_EXT or not src.is_file():
                continue
            dst = LIB_DIR / src.name
            n = 1
            while dst.exists():
                dst = LIB_DIR / f"{src.stem}_{n}{src.suffix}"
                n += 1
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass
        self.scan_library()
        self.rebuild_list()

    def add_files(self):
        exts = " ".join(f"*{e}" for e in sorted(ALL_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, tr("dlg_add"), "",
                                                f"{tr('dlg_media')} ({exts})")
        self.import_files(files)

    def delete_selected(self):
        name = self.selected_name()
        if name:
            self.delete_file(name)

    def delete_file(self, name):
        for s in self.slots:
            if s.file == name:
                s.clear()
        try:
            (LIB_DIR / name).unlink()
        except OSError:
            pass
        self.thumbs.pop(name, None)
        self.previews.pop(name, None)
        self.save_state()
        self.scan_library()
        self.rebuild_list()
        self.refresh_views()

    def on_library_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        self.list.setCurrentItem(item)
        name = item.data(NAME_ROLE)
        menu = QMenu(self)
        for s in self.slots:
            act = menu.addAction(tr("ctx_apply", name=self.slot_label(s)))
            act.triggered.connect(lambda _=False, s=s: self.apply_to_slots([s], name))
        if len(self.slots) > 1:
            act = menu.addAction(tr("ctx_apply_all"))
            act.triggered.connect(lambda _=False: self.apply_to_slots(self.slots, name))
        used = [s for s in self.slots if s.file == name]
        if used:
            menu.addSeparator()
            for s in used:
                act = menu.addAction(tr("ctx_remove_from", name=self.slot_label(s)))
                act.triggered.connect(lambda _=False, s=s: self.remove_from_slot(s))
        menu.addSeparator()
        act = menu.addAction(tr("ctx_delete"))
        act.triggered.connect(lambda _=False: self.delete_file(name))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Delete and self.list.hasFocus():
            self.delete_selected()
            return
        super().keyPressEvent(e)

    # Glisser-déposer de fichiers depuis l'Explorateur Windows
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.import_files([u.toLocalFile() for u in e.mimeData().urls()])

    # ---------------------------------------------------------------- Application des fonds
    def apply_to_slots(self, slots, name):
        path = LIB_DIR / name
        if not path.exists() or not slots:
            return
        for s in slots:
            if self.suspended:
                s.file = name
            else:
                s.show_file(path)
        self.save_state()
        self.update_pause(force=True)

    def remove_from_slot(self, slot):
        slot.clear()
        self.save_state()
        self.update_pause()

    # ---------------------------------------------------------------- Options
    def on_auto_pause_opt(self, checked):
        self.cfg["pause_fullscreen"] = bool(checked)
        save_config(self.cfg)
        if not checked:
            self.fullscreen_any = False
            self.covered = set()
        self.update_pause()

    def on_autostart(self, checked):
        try:
            set_autostart(bool(checked))
        except Exception as e:
            print("Autostart :", e)
            self.popup.tg_start.setChecked(not checked)

    # ---------------------------------------------------------------- Pause
    def toggle_slot(self, slot):
        slot.manual = not slot.manual
        self.update_pause()

    def toggle_all(self):
        active = [s for s in self.slots if s.file]
        make_manual = not all(s.manual for s in active) if active else False
        for s in self.slots:
            s.manual = make_manual
        self.update_pause()

    def check_desktop(self):
        if self.suspended or not self.cfg.get("pause_fullscreen", True):
            return
        if not any(s.win.has_media for s in self.slots):
            return
        fs, covered = analyze_desktop(self.monitors)
        if fs != self.fullscreen_any or covered != self.covered:
            self.fullscreen_any, self.covered = fs, covered
            self.update_pause()

    def update_pause(self, force=False):
        """
        Règles :
          - veille / verrouillage / écran éteint : tous les écrans (tout est libéré)
          - pause manuelle : l'écran concerné
          - une appli en plein écran sur un écran : tous les écrans
          - un écran entièrement caché par des fenêtres : cet écran seulement
        """
        for s in self.slots:
            if self.suspended:
                s.reason = "sleep"
            elif s.manual:
                s.reason = "manual"
            elif self.fullscreen_any:
                s.reason = "fs"
            elif s.mon.device in self.covered:
                s.reason = "cover"
            else:
                s.reason = None
            paused = s.reason is not None
            if s.win.has_media and (force or paused != s.paused):
                s.win.set_paused(paused)
                s.paused = paused
        self.update_pause_texts()
        self.refresh_views()

    def update_pause_texts(self):
        active = [s for s in self.slots if s.file]
        all_manual = bool(active) and all(s.manual for s in active)
        self.tray_pause.setText(tr("tray_resume") if all_manual else tr("tray_pause"))

    # ---------------------------------------------------------------- Veille / verrouillage
    def register_system_events(self):
        hwnd = int(self.winId())
        try:
            wtsapi32.WTSRegisterSessionNotification(hwnd, 0)       # verrouillage / déverrouillage
        except Exception as e:
            print("Notification de session :", e)
        try:                                                        # écran éteint / allumé
            user32.RegisterPowerSettingNotification(
                hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), 0)
        except Exception as e:
            print("Notification d'alimentation :", e)
        self.taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")  # Explorateur relancé
        self.event_filter = SystemEventFilter(self.on_native_message)
        QApplication.instance().installNativeEventFilter(self.event_filter)

    def on_native_message(self, msg, wparam, lparam):
        if msg == WM_WTSSESSION_CHANGE:
            if wparam == WTS_SESSION_LOCK:
                self.system_off("lock")
            elif wparam == WTS_SESSION_UNLOCK:
                self.system_on("lock")
        elif msg == WM_POWERBROADCAST:
            if wparam == PBT_APMSUSPEND:
                self.system_off("sleep")
            elif wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND):
                self.system_on("sleep")
            elif wparam == PBT_POWERSETTINGCHANGE and lparam:
                guid = ctypes.string_at(lparam, 16)
                if guid == bytes(GUID_CONSOLE_DISPLAY_STATE):
                    state = ctypes.c_ubyte.from_address(lparam + 20).value
                    if state == 0:
                        self.system_off("display")
                    else:
                        self.system_on("display")
        elif msg == WM_DISPLAYCHANGE:
            self.display_timer.start(1500)
        elif self.taskbar_msg and msg == self.taskbar_msg:
            self.reattach_timer.start(1500)

    def system_off(self, reason):
        """Verrouillage, veille ou écran éteint : on arrête tout et on libère les ressources."""
        self.suspend_reasons.add(reason)
        self.resume_timer.stop()
        if not self.suspended:
            self.suspended = True
            self.desktop_timer.stop()
            for s in self.slots:
                s.suspend()
            self.update_pause()

    def system_on(self, reason):
        """Retour : on attend que l'affichage soit stable, puis on reconstruit tout."""
        self.suspend_reasons.discard(reason)
        if not self.suspend_reasons:
            self.resume_timer.start(2500)

    def finish_resume(self):
        if self.suspend_reasons or not self.suspended:
            return
        self.suspended = False
        self.fullscreen_any = False
        self.covered = set()
        self.refresh_monitors(force_reload=True)
        self.desktop_timer.start(1500)
        self.update_pause(force=True)

    def reload_wallpapers(self):
        """Recrée toutes les fenêtres de fond (après veille ou redémarrage de l'Explorateur)."""
        if self.suspended:
            return
        for s in self.slots:
            s.reload()
        self.update_pause(force=True)

    def refresh_monitors(self, force_reload):
        """Détecte un changement d'écrans (branchement, résolution...) et s'adapte."""
        if self.suspended:
            return
        new = list_monitors()
        if [m.signature() for m in new] == [m.signature() for m in self.monitors]:
            if force_reload:
                self.reload_wallpapers()
            return
        self.save_state()
        old = {s.mon.device: s for s in self.slots}
        slots = []
        for i, m in enumerate(new):
            s = old.pop(m.device, None)
            if s is None:
                s = ScreenSlot(m, i, self.cfg["screens"].get(m.device, {}))
                s.file = self.cfg["screens"].get(m.device, {}).get("file")
            else:
                s.mon, s.index = m, i
            slots.append(s)
        for s in old.values():
            s.destroy()
        self.monitors, self.slots = new, slots
        self.screens_panel.rebuild(self.slots)
        self.reload_wallpapers()
        self.rebuild_list()

    # ---------------------------------------------------------------- Quitter
    def quit_app(self):
        self.desktop_timer.stop()
        try:
            wtsapi32.WTSUnRegisterSessionNotification(int(self.winId()))
        except Exception:
            pass
        for s in self.slots:
            s.destroy()
        self.tray.hide()
        refresh_desktop_wallpaper()
        QApplication.quit()


def main():
    if sys.platform != "win32":
        print("Kinesis fonctionne uniquement sous Windows.")
        sys.exit(1)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Kinesis")
    app.setStyle("Fusion")
    load_fonts()
    base_font = QFont(FONT_FAMILY)
    base_font.setPixelSize(14)
    app.setFont(base_font)
    app.setStyleSheet(build_qss())
    app.setWindowIcon(make_app_icon())

    migrate_from_ultrawall()
    if _remove_old_autostart():      # l'utilisateur avait "Lancer avec Windows" activé
        try:
            set_autostart(True)
        except Exception:
            pass
    win = MainWindow(load_config())
    if "--tray" not in sys.argv:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
