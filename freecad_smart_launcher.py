#!/usr/bin/env python3
"""
FreeCAD Smart Launcher (PySide6)

Manage FreeCAD AppImages, test GitHub pull requests, and browse local projects.
Linux desktop helper — not affiliated with the FreeCAD project.
"""

# Optional runtime deps for 3D view: f3d (recommended), vtk, cadquery-ocp
# Package as AppImage with PySide6 and system libraries as needed for your base distro.

import os
import sys
import json
import time
import atexit
import struct
import math
import tempfile
import shutil
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import ssl
import zipfile
import xml.etree.ElementTree as ET
import threading
import webbrowser
import re
import signal
from pathlib import Path

_SSL_CTX = ssl.create_default_context()


def _github_get(url, timeout=12):
    """GET JSON from the GitHub API."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "FreeCAD-Smart-Launcher/2.1",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as response:
        return json.loads(response.read().decode())

from PySide6.QtCore import (
    Qt, QSize, QTimer, QThread, Signal, Slot, QObject, QRect, QPointF, QEvent
)
from PySide6.QtGui import (
    QFont, QColor, QPalette, QIcon, QPixmap, QImage, QPainter, QPen, QBrush,
    QAction, QCursor, QFontDatabase, QPolygonF
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QListWidget, QListWidgetItem, QComboBox, QLineEdit,
    QCheckBox, QFrame, QTabWidget, QScrollArea, QTextEdit, QTextBrowser, QMessageBox,
    QInputDialog, QFileDialog, QDialog, QDialogButtonBox, QTreeWidget,
    QTreeWidgetItem, QHeaderView, QProgressBar, QSplitter, QSizePolicy,
    QAbstractItemView, QStyleFactory, QGraphicsDropShadowEffect, QLayout, QStackedWidget
)


USER_HOME = os.path.expanduser("~")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_INSTALL_DIR = os.path.join(USER_HOME, "Applications", "FreeCAD")
# Legacy locations (migrated once into the AppImage install folder)
LEGACY_CONFIG_FILE = os.path.join(USER_HOME, ".freecad_launcher_config.json")
LEGACY_STATS_FILE = os.path.join(USER_HOME, ".freecad_time_tracker.json")
LOCK_FILE = os.path.join(USER_HOME, ".freecad_launcher.lock")
BUILD_LOG_FILE = os.path.join(USER_HOME, ".freecad_launcher_build.log")
CONFIG_BASENAME = "launcher_config.json"
STATS_BASENAME = "time_tracker.json"


def config_path_for(install_dir):
    return os.path.join(install_dir, CONFIG_BASENAME)


def stats_path_for(install_dir):
    return os.path.join(install_dir, STATS_BASENAME)

SUPPORTED_3D_EXTENSIONS = {".fcstd", ".step", ".stp", ".iges", ".igs", ".stl", ".brep"}
STEP_LIKE_EXTENSIONS = {".step", ".stp", ".iges", ".igs", ".brep"}


class BuildCancelled(Exception):
    """Raised when the user stops a PR build."""
    pass


class ElidedLabel(QLabel):
    """QLabel that elides each line with "…" instead of widening its column.

    A plain QLabel's minimum width is the width of its text, so a long status
    message would push the layout wider than the window and make columns overlap.
    text() still returns the full text and the tooltip shows it.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(1)
        self.setText(text)

    def text(self):
        return self._full

    def setText(self, text):
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply_elision()

    def _apply_elision(self):
        fm = self.fontMetrics()
        avail = max(10, self.width() - 2 * self.margin() - 2)
        lines = [fm.elidedText(l, Qt.ElideRight, avail) for l in self._full.split("\n")]
        QLabel.setText(self, "\n".join(lines))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_elision()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._apply_elision()

    def minimumSizeHint(self):
        return QSize(1, super().minimumSizeHint().height())


def _download_image_data_uri(url, timeout=12):
    """Download an image and return a data URI, or None."""
    try:
        if not url or not url.startswith(("http://", "https://")):
            return None
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "FreeCAD-Smart-Launcher/2.1",
                "Accept": "image/*,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
            data = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not data or len(data) < 32:
            return None
        if not ctype.startswith("image/"):
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                ctype = "image/png"
            elif data[:2] == b"\xff\xd8":
                ctype = "image/jpeg"
            elif data[:4] == b"GIF8":
                ctype = "image/gif"
            elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                ctype = "image/webp"
            else:
                ctype = "image/png"
        import base64
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{ctype};base64,{b64}"
    except Exception as e:
        print(f"[img] failed {url}: {e}", flush=True)
        return None


def _extract_media_urls(md_text):
    """Collect image and video URLs from markdown or HTML."""
    if not md_text:
        return []
    urls = []
    for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", md_text):
        urls.append(m.group(1).strip())
    for m in re.finditer(
        r'<img[^>]+src=["\']([^"\']+)["\']', md_text, flags=re.I
    ):
        urls.append(m.group(1).strip())
    for m in re.finditer(
        r"(?m)^(https://(?:user-images\.githubusercontent\.com|private-user-images\.githubusercontent\.com|"
        r"github\.com/user-attachments/assets/)[^\s]+)$",
        md_text,
    ):
        urls.append(m.group(1).strip())
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _md_to_html(md_text, is_dark=True, image_map=None):
    """Convert simple markdown to HTML. image_map maps URL to data URI."""
    if not md_text:
        return "<p><i>(empty)</i></p>"
    import html as _html
    image_map = image_map or {}
    text = md_text.replace("\r\n", "\n")

    text = re.sub(
        r"(?m)^(https://(?:user-images\.githubusercontent\.com|private-user-images\.githubusercontent\.com|"
        r"github\.com/user-attachments/assets/)[^\s]+)$",
        r"![image](\1)",
        text,
    )

    text = _html.escape(text)

    def code_block(m):
        code = m.group(1)
        return (
            '<pre style="background:#0d0e12;border:1px solid #333;border-radius:6px;'
            'padding:10px;overflow-x:auto;font-family:monospace;font-size:12px;">'
            f"{code}</pre>"
        )

    text = re.sub(r"```(?:\w+)?\n([\s\S]*?)```", code_block, text)
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#2a2b30;padding:1px 5px;border-radius:3px;font-family:monospace;">\1</code>',
        text,
    )

    def img_repl(m):
        alt, url = m.group(1), m.group(2)
        url_raw = _html.unescape(url)
        low = url_raw.lower()
        if any(low.endswith(ext) for ext in (".mp4", ".webm", ".mov")) or "youtube.com" in low or "youtu.be" in low:
            return (
                f'<p style="margin:8px 0;"><b>🎬 Video</b><br/>'
                f'<a href="{url_raw}">{url_raw}</a><br/>'
                f'<span style="color:#888;font-size:11px;">Open the link to play the video</span></p>'
            )
        src = image_map.get(url_raw) or image_map.get(url) or url_raw
        return (
            f'<p style="margin:10px 0;text-align:center;">'
            f'<img src="{src}" alt="{alt}" '
            f'style="max-width:100%;max-height:420px;border-radius:6px;border:1px solid #333;"/></p>'
        )

    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", img_repl, text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:#6BA3F7;">\1</a>',
        text,
    )
    text = re.sub(
        r'(?<!["\'=])(https?://[^\s<]+)',
        r'<a href="\1" style="color:#6BA3F7;">\1</a>',
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"^### (.+)$", r'<h3 style="margin:12px 0 6px;">\1</h3>', text, flags=re.M)
    text = re.sub(r"^## (.+)$", r'<h2 style="margin:14px 0 6px;">\1</h2>', text, flags=re.M)
    text = re.sub(r"^# (.+)$", r'<h2 style="margin:14px 0 6px;">\1</h2>', text, flags=re.M)
    text = re.sub(
        r"^&gt; (.+)$",
        r'<blockquote style="border-left:3px solid #3B82F6;margin:8px 0;padding:4px 10px;color:#aaa;">\1</blockquote>',
        text,
        flags=re.M,
    )
    text = re.sub(r"^- (.+)$", r"<div>• \1</div>", text, flags=re.M)

    parts = re.split(r"\n\n+", text)
    html_parts = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if p.startswith(("<h", "<pre", "<p", "<blockquote", "<div")):
            html_parts.append(p.replace("\n", "<br/>"))
        else:
            html_parts.append(
                '<p style="margin:8px 0;line-height:1.45;">' + p.replace("\n", "<br/>") + "</p>"
            )
    bg = "#121316" if is_dark else "#f7f8f9"
    fg = "#E8E8EC" if is_dark else "#1A1B1E"
    return (
        f'<div style="color:{fg};background:{bg};font-family:sans-serif;font-size:13px;">'
        + "".join(html_parts)
        + "</div>"
    )


def tessellate_step_with_ocp(filepath, max_triangles=8000, deflection=0.8):
    """Tessellate STEP with OCP if installed; otherwise return None."""
    try:
        from OCP.STEPControl import STEPControl_Reader
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.TopExp import TopExp_Explorer
        from OCP.TopAbs import TopAbs_FACE
        from OCP.BRep import BRep_Tool
        from OCP.TopLoc import TopLoc_Location
    except ImportError:
        return None
    try:
        reader = STEPControl_Reader()
        status = reader.ReadFile(str(filepath))
        if status != IFSelect_RetDone:
            return None
        reader.TransferRoots()
        shape = reader.OneShape()
        BRepMesh_IncrementalMesh(shape, deflection)
        triangles = []
        exp = TopExp_Explorer(shape, TopAbs_FACE)
        while exp.More() and len(triangles) < max_triangles:
            face = exp.Current()
            loc = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation(face, loc)
            if triangulation is not None:
                trsf = loc.Transformation()
                nodes = []
                for i in range(1, triangulation.NbNodes() + 1):
                    p = triangulation.Node(i)
                    p.Transform(trsf)
                    nodes.append((p.X(), p.Y(), p.Z()))
                for i in range(1, triangulation.NbTriangles() + 1):
                    if len(triangles) >= max_triangles:
                        break
                    t = triangulation.Triangle(i)
                    i1, i2, i3 = t.Get()
                    triangles.append((nodes[i1 - 1], nodes[i2 - 1], nodes[i3 - 1]))
            exp.Next()
        return triangles or None
    except Exception as e:
        print(f"[OCP STEP] {e}", flush=True)
        return None


def open_vtk_mesh_viewer(triangles, title="3D Preview"):
    """Open an interactive VTK window when vtk is available."""
    try:
        import vtk
    except ImportError:
        return False
    if not triangles:
        return False
    try:
        points = vtk.vtkPoints()
        cells = vtk.vtkCellArray()
        vert_index = {}
        def add_pt(pt):
            key = (round(float(pt[0]), 6), round(float(pt[1]), 6), round(float(pt[2]), 6))
            if key in vert_index:
                return vert_index[key]
            idx = points.InsertNextPoint(key[0], key[1], key[2])
            vert_index[key] = idx
            return idx

        for tri in triangles[:30000]:
            try:
                i0 = add_pt(tri[0])
                i1 = add_pt(tri[1])
                i2 = add_pt(tri[2])
            except Exception:
                continue
            tri_ids = vtk.vtkIdList()
            tri_ids.InsertNextId(i0)
            tri_ids.InsertNextId(i1)
            tri_ids.InsertNextId(i2)
            cells.InsertNextCell(tri_ids)

        poly = vtk.vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(cells)

        clean = vtk.vtkCleanPolyData()
        clean.SetInputData(poly)
        clean.Update()

        normals = vtk.vtkPolyDataNormals()
        normals.SetInputConnection(clean.GetOutputPort())
        normals.ComputePointNormalsOn()
        normals.ComputeCellNormalsOn()
        normals.SplittingOff()
        normals.ConsistencyOn()
        normals.AutoOrientNormalsOn()
        normals.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(normals.GetOutputPort())
        mapper.ScalarVisibilityOff()

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(0.40, 0.70, 0.95)
        prop.SetAmbient(0.25)
        prop.SetDiffuse(0.85)
        prop.SetSpecular(0.35)
        prop.SetSpecularPower(25)
        prop.SetInterpolationToPhong()
        prop.BackfaceCullingOff()
        prop.FrontfaceCullingOff()
        prop.EdgeVisibilityOff()

        ren = vtk.vtkRenderer()
        ren.AddActor(actor)
        ren.SetBackground(0.12, 0.13, 0.15)
        ren.ResetCamera()

        rw = vtk.vtkRenderWindow()
        rw.AddRenderer(ren)
        rw.SetSize(900, 700)
        rw.SetWindowName(title)

        iren = vtk.vtkRenderWindowInteractor()
        iren.SetRenderWindow(rw)
        style = vtk.vtkInteractorStyleTrackballCamera()
        iren.SetInteractorStyle(style)
        rw.Render()
        iren.Start()
        return True
    except Exception as e:
        print(f"[VTK] {e}", flush=True)
        return False


# Theme colors
DARK = {
    "bg": "#121316",
    "card": "#1C1D21",
    "input": "#16171A",
    "accent": "#3B82F6",
    "accent_dk": "#2563EB",
    "success": "#22C55E",
    "success_dk": "#16A34A",
    "danger": "#EF4444",
    "danger_dk": "#DC2626",
    "warning": "#EAB308",
    "warning_dk": "#CA8A04",
    "neutral": "#2A2B30",
    "neutral_dk": "#3A3B41",
    "text": "#E8E8EC",
    "muted": "#8B8B96",
    "link": "#6BA3F7",
    "error": "#F87171",
    "footer": "#6B6B76",
    "border": "#2E2F35",
    "hover": "#32333A",
    "text_area_bg": "#0E0F12",
    "text_area_fg": "#D4D4D8",
}

LIGHT = {
    "bg": "#F0F1F3",
    "card": "#FFFFFF",
    "input": "#F7F8F9",
    "accent": "#2563EB",
    "accent_dk": "#1D4ED8",
    "success": "#16A34A",
    "success_dk": "#15803D",
    "danger": "#DC2626",
    "danger_dk": "#B91C1C",
    "warning": "#CA8A04",
    "warning_dk": "#A16207",
    "neutral": "#E8E9EC",
    "neutral_dk": "#D5D6DB",
    "text": "#1A1B1E",
    "muted": "#6B6B76",
    "link": "#2563EB",
    "error": "#DC2626",
    "footer": "#6B6B76",
    "border": "#D8D9DE",
    "hover": "#ECEDEF",
    "text_area_bg": "#FAFBFC",
    "text_area_fg": "#1A1B1E",
}


def get_theme(is_dark: bool) -> dict:
    return DARK if is_dark else LIGHT


def _ensure_chevron_icon() -> str:
    """Return path to a small chevron SVG icon, creating it if needed."""
    candidates = [
        os.path.join(SCRIPT_DIR, "assets", "chevron_down.svg"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "chevron_down.svg"),
        os.path.join(tempfile.gettempdir(), "freecad_launcher_chevron_down.svg"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    path = candidates[-1]
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8" viewBox="0 0 12 8">'
        '<path d="M1 1.5 L6 6.5 L11 1.5" fill="none" stroke="#C4C4C8" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
        "</svg>"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
    except Exception:
        return ""
    return path


_CHEVRON_PATH = _ensure_chevron_icon()


def _ensure_evolventa_font() -> str:
    """Return the Evolventa font family name, or empty string."""
    script_assets = os.path.join(SCRIPT_DIR, "assets", "Evolventa-Bold.ttf")
    candidates = [
        script_assets,
        os.path.join(SCRIPT_DIR, "Evolventa-Bold.ttf"),
        "/usr/share/fonts/truetype/evolventa/Evolventa-Bold.ttf",
        "/usr/share/fonts/opentype/evolventa/Evolventa-Bold.otf",
        os.path.join(USER_HOME, ".local", "share", "fonts", "Evolventa-Bold.ttf"),
        os.path.join(tempfile.gettempdir(), "Evolventa-Bold.ttf"),
    ]
    for path in candidates:
        if os.path.exists(path):
            fid = QFontDatabase.addApplicationFont(path)
            if fid != -1:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    return families[0]
    # Optional download of Evolventa Bold next to the script
    try:
        os.makedirs(os.path.dirname(script_assets), exist_ok=True)
        url = "https://raw.githubusercontent.com/evolventa/evolventa/master/ttf/Evolventa-Bold.ttf"
        urllib.request.urlretrieve(url, script_assets)
        if os.path.exists(script_assets):
            fid = QFontDatabase.addApplicationFont(script_assets)
            if fid != -1:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    return families[0]
    except Exception:
        pass
    if "Evolventa" in QFontDatabase.families():
        return "Evolventa"
    return ""


_EVOLVENTA_FAMILY = None  # resolved lazily after QApplication exists


def get_evolventa_family() -> str:
    global _EVOLVENTA_FAMILY
    if _EVOLVENTA_FAMILY is None:
        _EVOLVENTA_FAMILY = _ensure_evolventa_font() or ""
    return _EVOLVENTA_FAMILY


def make_qss(is_dark: bool) -> str:
    t = get_theme(is_dark)
    chevron = _CHEVRON_PATH.replace("\\", "/") if os.path.exists(_CHEVRON_PATH) else ""
    arrow_rule = f'image: url("{chevron}");' if chevron else "width: 0; height: 0;"
    btn_fg = "#FFFFFF" if is_dark else t["text"]
    return f"""
    * {{
        font-family: "Inter", "Noto Sans", "Segoe UI", system-ui, sans-serif;
    }}
    QMainWindow, QDialog {{
        background-color: {t['bg']};
        color: {t['text']};
        font-size: 12.5px;
    }}
    QWidget {{
        color: {t['text']};
        font-size: 12.5px;
    }}
    QFrame#card {{
        background-color: {t['card']};
        border-radius: 8px;
        border: 1px solid {t['border']};
    }}
    QLabel {{
        color: {t['text']};
        background: transparent;
    }}
    QLabel#sectionTitle {{
        font-size: 10.5px;
        font-weight: 700;
        color: {t['muted']};
        letter-spacing: 1.1px;
        text-transform: uppercase;
    }}
    QLabel#muted {{
        color: {t['muted']};
        font-size: 11.5px;
    }}
    QLabel#statusOk {{
        color: {t['success']};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#statusWarn {{
        color: {t['danger']};
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#footer {{
        color: {t['footer']};
        font-style: italic;
        font-size: 11.5px;
    }}
    QLabel#powered {{
        color: {t['accent']};
        font-weight: 700;
        font-size: 10px;
        letter-spacing: 0.8px;
    }}
    QPushButton {{
        background-color: {t['neutral']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        padding: 4px 11px;
        font-weight: 600;
        font-size: 11.5px;
        min-height: 22px;
        max-height: 28px;
    }}
    QPushButton:hover {{
        background-color: {t['hover']};
        border-color: {t['muted']};
    }}
    QPushButton:pressed {{
        background-color: {t['neutral_dk']};
    }}
    QPushButton:disabled {{
        background-color: {t['bg']};
        color: {t['muted']};
        border-color: {t['border']};
    }}
    /* Action buttons */
    QPushButton#accent {{
        background-color: {"#3A5F8A" if is_dark else "#C5D4E8"};
        color: {"#FFFFFF" if is_dark else "#1A2A3A"};
        border: 1px solid {"#2E4D70" if is_dark else "#9AB0C8"};
    }}
    QPushButton#accent:hover {{
        background-color: {"#4A6F9A" if is_dark else "#B0C4DC"};
        border: 1px solid {"#6BA3F7" if is_dark else "#3B82F6"};
    }}
    QPushButton#success {{
        background-color: {"#3D6B4F" if is_dark else "#C5D9C8"};
        color: {"#FFFFFF" if is_dark else "#1A2A1A"};
        border: 1px solid {"#325A42" if is_dark else "#9AB89A"};
    }}
    QPushButton#success:hover {{
        background-color: {"#4A7A5C" if is_dark else "#B0C8B4"};
        border: 1px solid {"#4ADE80" if is_dark else "#16A34A"};
    }}
    QPushButton#danger {{
        background-color: {"#8A4545" if is_dark else "#E8C8C8"};
        color: {"#FFFFFF" if is_dark else "#3A1A1A"};
        border: 1px solid {"#703838" if is_dark else "#C8A0A0"};
    }}
    QPushButton#danger:hover {{
        background-color: {"#9A5555" if is_dark else "#D8B0B0"};
        border: 1px solid {"#F87171" if is_dark else "#DC2626"};
    }}
    QPushButton#warning {{
        background-color: {"#8A7040" if is_dark else "#E8DCC0"};
        color: {"#F5F0E0" if is_dark else "#2A2418"};
        border: 1px solid {"#705830" if is_dark else "#C8B890"};
    }}
    QPushButton#warning:hover {{
        background-color: {"#9A8050" if is_dark else "#D8CCB0"};
        border: 1px solid {"#FBBF24" if is_dark else "#CA8A04"};
    }}
    QPushButton#linkBtn {{
        background-color: {t['neutral']};
        color: {t['text']};
        border: 1px solid {t['border']};
        font-weight: 600;
    }}
    QPushButton#linkBtn:hover {{
        background-color: {t['hover']};
        border-color: {t['accent']};
    }}
    QLineEdit {{
        background-color: {t['input']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        padding: 5px 10px;
        min-height: 24px;
        selection-background-color: {t['accent']};
    }}
    QLineEdit:focus {{
        border-color: {t['accent']};
    }}
    QComboBox {{
        background-color: {t['input']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        padding: 4px 8px;
        min-height: 24px;
        selection-background-color: {t['accent']};
    }}
    QComboBox:hover {{
        border-color: {t['muted']};
    }}
    QComboBox:focus {{
        border-color: {t['accent']};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 26px;
        border: none;
        border-left: 1px solid {t['border']};
        background-color: {t['neutral']};
        border-top-right-radius: 5px;
        border-bottom-right-radius: 5px;
    }}
    QComboBox::drop-down:hover {{
        background-color: {t['hover']};
    }}
    QComboBox::down-arrow {{
        {arrow_rule}
        width: 11px;
        height: 7px;
        margin-right: 2px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t['card']};
        color: {t['text']};
        selection-background-color: {t['accent']};
        border: 1px solid {t['border']};
        outline: none;
        padding: 3px;
    }}
    QListWidget {{
        background-color: {t['input']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        outline: none;
        padding: 3px;
    }}
    QListWidget::item {{
        padding: 5px 8px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {t['accent']};
        color: white;
    }}
    QListWidget::item:hover {{
        background-color: {t['hover']};
    }}
    QCheckBox {{
        color: {t['text']};
        spacing: 8px;
        background: transparent;
        font-size: 12px;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 3px;
        border: 1px solid {t['border']};
        background: {t['input']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {t['accent']};
        border-color: {t['accent']};
    }}
    QTabWidget::pane {{
        border: 1px solid {t['border']};
        border-radius: 6px;
        background: {t['card']};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {t['muted']};
        padding: 6px 14px;
        margin-right: 1px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
        font-weight: 600;
        font-size: 11.5px;
        border: 1px solid transparent;
    }}
    QTabBar::tab:selected {{
        background: {t['card']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-bottom-color: {t['card']};
    }}
    QTabBar::tab:hover:!selected {{
        color: {t['text']};
        background: {t['hover']};
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t['border']};
        border-radius: 4px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {t['muted']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QTreeWidget {{
        background-color: {t['input']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        outline: none;
    }}
    QTreeWidget::item:selected {{
        background-color: {t['accent']};
        color: white;
    }}
    QHeaderView::section {{
        background-color: {t['card']};
        color: {t['muted']};
        padding: 6px;
        border: none;
        font-weight: 700;
        font-size: 10.5px;
        letter-spacing: 0.5px;
    }}
    QTextEdit {{
        background-color: {t['text_area_bg']};
        color: {t['text_area_fg']};
        border: 1px solid {t['border']};
        border-radius: 5px;
        font-family: "JetBrains Mono", "Noto Sans Mono", "Consolas", monospace;
        font-size: 12px;
    }}
    QProgressBar {{
        border: 1px solid {t['border']};
        border-radius: 5px;
        background: {t['input']};
        text-align: center;
        color: {t['text']};
        font-size: 11px;
        font-weight: 600;
    }}
    QProgressBar::chunk {{
        background: {t['accent']};
        border-radius: 4px;
    }}
    """


# ---------- Helpers (unchanged logic) ----------

def acquire_single_instance_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if os.path.exists(f"/proc/{old_pid}"):
                return False
        except Exception:
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

    def release_lock():
        try:
            with open(LOCK_FILE, "r") as f:
                if int(f.read().strip()) == os.getpid():
                    os.remove(LOCK_FILE)
        except Exception:
            pass

    atexit.register(release_lock)
    return True


def pick_existing_directory(parent, start_dir, title="Select Directory"):
    """
    Open the desktop's native folder picker when possible.
    On KDE this uses kdialog (same stack as Dolphin); otherwise the Qt native
    dialog / xdg-desktop-portal, then zenity on GNOME-like desktops.
    """
    start = start_dir if start_dir and os.path.isdir(start_dir) else USER_HOME

    # KDE / Plasma — kdialog provides the native folder selector (Dolphin-like)
    if shutil.which("kdialog"):
        try:
            result = subprocess.run(
                ["kdialog", "--getexistingdirectory", start, "--title", title],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                chosen = (result.stdout or "").strip()
                if chosen and os.path.isdir(chosen):
                    return chosen
            # Non-zero without output = user cancelled
            if result.returncode != 0:
                return None
        except Exception:
            pass

    # GNOME / others — zenity
    if shutil.which("zenity"):
        try:
            result = subprocess.run(
                [
                    "zenity",
                    "--file-selection",
                    "--directory",
                    f"--filename={start}/",
                    f"--title={title}",
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                chosen = (result.stdout or "").strip()
                if chosen and os.path.isdir(chosen):
                    return chosen
            if result.returncode != 0:
                return None
        except Exception:
            pass

    # Qt native dialog (no DontUseNativeDialog → portal / platform theme)
    chosen = QFileDialog.getExistingDirectory(
        parent,
        title,
        start,
        QFileDialog.Option.ShowDirsOnly,
    )
    return chosen if chosen else None


def extract_version_key(filename):
    match = re.search(r"(\d+\.\d+\.\d+(?:\.\d+)?)", filename)
    if match:
        return match.group(1)
    match_date = re.search(r"(\d{4}[.-]\d{2}[.-]\d{2})", filename)
    if match_date:
        return match_date.group(1).replace("-", ".")
    return None


def version_sort_key(filename):
    key = extract_version_key(filename)
    if not key:
        return (0, 0, 0, 0, filename)
    parts = []
    for p in key.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4]) + (filename,)


def disable_freecad_start_page():
    cfg_path = os.path.join(USER_HOME, ".config", "FreeCAD", "user.cfg")
    if not os.path.exists(cfg_path):
        return
    try:
        tree = ET.parse(cfg_path)
        group = tree.getroot()
        for name in ("BaseApp", "Preferences", "Mod", "Start"):
            child = group.find(f"./FCParamGroup[@Name='{name}']")
            if child is None:
                child = ET.SubElement(group, "FCParamGroup", {"Name": name})
            group = child
        param = group.find("./FCBool[@Name='ShowOnStartup']")
        if param is None:
            param = ET.SubElement(group, "FCBool", {"Name": "ShowOnStartup"})
        param.set("Value", "0")
        tree.write(cfg_path, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass


def parse_stl_triangles(filepath, max_triangles=8000):
    triangles = []
    with open(filepath, "rb") as f:
        header = f.read(80)
        count_bytes = f.read(4)
        if len(count_bytes) == 4:
            count = struct.unpack("<I", count_bytes)[0]
            expected_size = 80 + 4 + count * 50
            actual_size = os.path.getsize(filepath)
            if count > 0 and abs(expected_size - actual_size) < 4:
                for _ in range(min(count, max_triangles)):
                    data = f.read(50)
                    if len(data) < 50:
                        break
                    floats = struct.unpack("<12f", data[:48])
                    v1, v2, v3 = floats[3:6], floats[6:9], floats[9:12]
                    triangles.append((v1, v2, v3))
                return triangles
    current = []
    with open(filepath, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if line.startswith("vertex"):
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        current.append((float(parts[1]), float(parts[2]), float(parts[3])))
                    except ValueError:
                        continue
                    if len(current) == 3:
                        triangles.append(tuple(current))
                        current = []
                        if len(triangles) >= max_triangles:
                            break
    return triangles


def draw_stl_wireframe_pixmap(triangles, width=285, height=165, line_color="#4FC3F7"):
    """Draw a shaded isometric mesh preview."""
    pixmap = QPixmap(width, height)
    bg = QColor("#1E1F23")
    pixmap.fill(bg)
    if not triangles:
        painter = QPainter(pixmap)
        painter.setPen(QColor("#A0A0A0"))
        painter.drawText(QRect(0, 0, width, height), Qt.AlignCenter, "Empty or unreadable mesh")
        painter.end()
        return pixmap

    tris = triangles[:12000]
    cos30 = math.cos(math.radians(30))
    sin30 = math.sin(math.radians(30))
    cos_t = math.cos(math.radians(18))
    sin_t = math.sin(math.radians(18))

    def project(x, y, z):
        yr = y * cos_t - z * sin_t
        zr = y * sin_t + z * cos_t
        u = (x - yr) * cos30
        v = (x + yr) * sin30 - zr
        return u, v, zr

    projected_tris = []
    all_u, all_v = [], []
    for tri in tris:
        try:
            pts = [project(float(p[0]), float(p[1]), float(p[2])) for p in tri]
        except Exception:
            continue
        depth = sum(p[2] for p in pts) / 3.0
        ax, ay, az = (float(tri[0][0]), float(tri[0][1]), float(tri[0][2]))
        bx, by, bz = (float(tri[1][0]), float(tri[1][1]), float(tri[1][2]))
        cx, cy, cz = (float(tri[2][0]), float(tri[2][1]), float(tri[2][2]))
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        nlen = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        nx, ny, nz = nx / nlen, ny / nlen, nz / nlen
        lx, ly, lz = -0.25, 0.55, 0.80
        # Two-sided lighting so back faces are not black holes
        ndot = abs(nx * lx + ny * ly + nz * lz)
        projected_tris.append((depth, pts, ndot))
        all_u.extend(p[0] for p in pts)
        all_v.extend(p[1] for p in pts)

    if not projected_tris:
        painter = QPainter(pixmap)
        painter.setPen(QColor("#A0A0A0"))
        painter.drawText(QRect(0, 0, width, height), Qt.AlignCenter, "Empty mesh")
        painter.end()
        return pixmap

    span_u = max(max(all_u) - min(all_u), 1e-6)
    span_v = max(max(all_v) - min(all_v), 1e-6)
    min_u, min_v = min(all_u), min(all_v)
    margin = 12
    scale = min((width - 2 * margin) / span_u, (height - 2 * margin) / span_v)

    def to_canvas(u, v):
        return margin + (u - min_u) * scale, height - margin - (v - min_v) * scale

    projected_tris.sort(key=lambda item: item[0])  # far → near
    base = QColor(line_color)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)

    for _depth, pts, ndot in projected_tris:
        canvas = [to_canvas(p[0], p[1]) for p in pts]
        shade = 0.30 + 0.70 * ndot
        r = int(min(255, base.red() * shade * 0.65 + 45))
        g = int(min(255, base.green() * shade * 0.80 + 55))
        b = int(min(255, base.blue() * shade + 70))
        painter.setBrush(QBrush(QColor(r, g, b)))
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in canvas]))

    painter.end()
    return pixmap


def run_freecad_console_script(app_path, script_path, timeout=60):
    """Run a Python script with FreeCAD in console mode."""
    script_path = os.path.abspath(script_path)
    attempts = (
        [app_path, "-c", script_path],
        [app_path, "--console", script_path],
        [app_path, "--console", "-c", script_path],
        [app_path, "--appimage-extract-and-run", "-c", script_path],
        [app_path, "--appimage-extract-and-run", "--console", script_path],
    )
    last_err = b""
    for cmd in attempts:
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
            )
            if result.returncode == 0:
                return True
            last_err = result.stderr or result.stdout or b""
        except (subprocess.TimeoutExpired, OSError) as e:
            last_err = str(e).encode()
            continue
    if last_err:
        try:
            print(f"[FreeCAD console] {last_err.decode(errors='replace')[:500]}", flush=True)
        except Exception:
            pass
    return False


def export_fcstd_to_temp_cad(app_path, filepath, timeout=120):
    """Export a .FCStd to STEP, IGES, or STL for F3D. Return path or None."""
    if not app_path or not os.path.isfile(app_path):
        return None
    if not filepath or not os.path.isfile(filepath):
        return None

    filepath = os.path.abspath(filepath)
    cache_root = os.path.join(USER_HOME, ".cache", "freecad_smart_launcher", "f3d_exports")
    os.makedirs(cache_root, exist_ok=True)
    stamp = abs(hash((filepath, os.path.getmtime(filepath)))) % (10**10)
    base = os.path.splitext(os.path.basename(filepath))[0]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base)[:40] or "export"
    step_path = os.path.join(cache_root, f"{safe}_{stamp}.step")
    iges_path = os.path.join(cache_root, f"{safe}_{stamp}.iges")
    stl_path = os.path.join(cache_root, f"{safe}_{stamp}.stl")
    macro_path = os.path.join(cache_root, f"{safe}_{stamp}_export_cad.py")

    for p in (step_path, iges_path, stl_path):
        if os.path.isfile(p) and os.path.getsize(p) > 80:
            return p

    lines = [
        "import sys",
        "import os",
        "import FreeCAD as App",
        "import Part",
        "fcstd = %r" % filepath,
        "out_step = %r" % step_path,
        "out_iges = %r" % iges_path,
        "out_stl = %r" % stl_path,
        "doc = None",
        "written = None",
        "try:",
        "    doc = App.open(fcstd)",
        "    shapes = []",
        "    objs = []",
        "    for o in doc.Objects:",
        "        shape = getattr(o, 'Shape', None)",
        "        if shape is None or shape.isNull():",
        "            continue",
        "        # Skip empty construction geometry when possible",
        "        try:",
        "            if hasattr(shape, 'isNull') and shape.isNull():",
        "                continue",
        "        except Exception:",
        "            pass",
        "        shapes.append(shape)",
        "        objs.append(o)",
        "    if not shapes:",
        "        raise RuntimeError('No shapes found in document')",
        "    compound = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)",
        "    # 1) STEP (best for F3D solid view)",
        "    try:",
        "        compound.exportStep(out_step)",
        "        if os.path.isfile(out_step) and os.path.getsize(out_step) > 80:",
        "            written = out_step",
        "    except Exception as e:",
        "        sys.stderr.write('STEP export failed: %s\\n' % e)",
        "    if written is None:",
        "        try:",
        "            Part.export(objs, out_step)",
        "            if os.path.isfile(out_step) and os.path.getsize(out_step) > 80:",
        "                written = out_step",
        "        except Exception as e:",
        "            sys.stderr.write('Part.export STEP failed: %s\\n' % e)",
        "    # 2) IGES fallback",
        "    if written is None:",
        "        try:",
        "            compound.exportIges(out_iges)",
        "            if os.path.isfile(out_iges) and os.path.getsize(out_iges) > 80:",
        "                written = out_iges",
        "        except Exception as e:",
        "            sys.stderr.write('IGES export failed: %s\\n' % e)",
        "    if written is None:",
        "        try:",
        "            Part.export(objs, out_iges)",
        "            if os.path.isfile(out_iges) and os.path.getsize(out_iges) > 80:",
        "                written = out_iges",
        "        except Exception as e:",
        "            sys.stderr.write('Part.export IGES failed: %s\\n' % e)",
        "    # 3) STL last resort",
        "    if written is None:",
        "        try:",
        "            import Mesh",
        "            Mesh.export(objs, out_stl)",
        "            if os.path.isfile(out_stl) and os.path.getsize(out_stl) > 80:",
        "                written = out_stl",
        "        except Exception as e:",
        "            sys.stderr.write('STL export failed: %s\\n' % e)",
        "    if not written:",
        "        raise RuntimeError('All CAD exports failed')",
        "    # marker file for host process",
        "    with open(out_step + '.ok', 'w') as mf:",
        "        mf.write(written)",
        "except Exception as e:",
        "    sys.stderr.write('FCStd CAD export failed: %s\\n' % e)",
        "    try:",
        "        if doc is not None:",
        "            App.closeDocument(doc.Name)",
        "    except Exception:",
        "        pass",
        "    raise",
        "else:",
        "    try:",
        "        App.closeDocument(doc.Name)",
        "    except Exception:",
        "        pass",
        "",
    ]
    try:
        with open(macro_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        run_freecad_console_script(app_path, macro_path, timeout=timeout)
        ok_marker = step_path + ".ok"
        if os.path.isfile(ok_marker):
            try:
                with open(ok_marker, "r", encoding="utf-8") as mf:
                    written = mf.read().strip()
                if written and os.path.isfile(written) and os.path.getsize(written) > 80:
                    return written
            except Exception:
                pass
        for p in (step_path, iges_path, stl_path):
            if os.path.isfile(p) and os.path.getsize(p) > 80:
                return p
        print(f"[FCStd-CAD] export missing after FreeCAD run", flush=True)
    except Exception as e:
        print(f"[FCStd-CAD] {e}", flush=True)
    return None


def export_fcstd_to_temp_stl(app_path, filepath, timeout=120):
    """Backward-compatible alias — prefers STEP/IGES via export_fcstd_to_temp_cad. """
    return export_fcstd_to_temp_cad(app_path, filepath, timeout=timeout)


def tessellate_step_file(app_path, filepath, max_triangles=8000):
    tmp_dir = tempfile.mkdtemp(prefix="fc_preview_")
    macro_path = os.path.join(tmp_dir, "preview_macro.py")
    output_path = os.path.join(tmp_dir, "triangles.json")

    macro_code = (
        "import json\n"
        "import FreeCAD as App\n"
        "import Part\n"
        "triangles = []\n"
        "doc = App.newDocument('preview')\n"
        "try:\n"
        f"    Part.insert({filepath!r}, doc.Name)\n"
        "    for obj in doc.Objects:\n"
        "        shape = getattr(obj, 'Shape', None)\n"
        "        if shape and not shape.isNull():\n"
        "            try:\n"
        "                vertices, facets = shape.tessellate(0.8)\n"
        "            except Exception:\n"
        "                continue\n"
        "            for tri in facets:\n"
        "                triangles.append([list(vertices[i]) for i in tri])\n"
        "finally:\n"
        f"    with open({output_path!r}, 'w') as out_f:\n"
        f"        json.dump(triangles[:{max_triangles}], out_f)\n"
        "    App.closeDocument(doc.Name)\n"
    )
    try:
        with open(macro_path, "w") as f:
            f.write(macro_code)
        run_freecad_console_script(app_path, macro_path)
        if os.path.exists(output_path):
            with open(output_path, "r") as f:
                data = json.load(f)
            return [tuple(tuple(pt) for pt in tri) for tri in data]
    except Exception:
        pass
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None


class StatsDialog(QDialog):
    def __init__(self, parent, stats_data, is_dark=True, on_reset=None):
        super().__init__(parent)
        self.setWindowTitle("Statistics")
        self.setMinimumSize(480, 360)
        self.resize(520, 400)
        self.setStyleSheet(make_qss(is_dark))
        self._on_reset = on_reset
        self._tot_label = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("FreeCAD Usage Statistics")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Version / File", "Time", "Launches"])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 80)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        layout.addWidget(self.tree, 1)

        self._populate_tree(stats_data)

        tot_hours = sum(d.get("time_sec", 0) for d in stats_data.values()) // 3600
        tot_minutes = (sum(d.get("time_sec", 0) for d in stats_data.values()) % 3600) // 60
        tot_launches = sum(d.get("launches", 0) for d in stats_data.values())
        tot_str = f"Total: {tot_hours}h {tot_minutes:02d}m ({tot_launches} launches)"

        bottom = QHBoxLayout()
        self._tot_label = QLabel(tot_str)
        bottom.addWidget(self._tot_label)
        bottom.addStretch()
        btn_reset = QPushButton("Reset")
        btn_reset.setObjectName("danger")
        btn_reset.setToolTip("Clear all usage times and launch history")
        btn_reset.clicked.connect(self._reset_stats)
        bottom.addWidget(btn_reset)
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("accent")
        btn_ok.clicked.connect(self.accept)
        bottom.addWidget(btn_ok)
        layout.addLayout(bottom)

    def _populate_tree(self, stats_data):
        self.tree.clear()
        for ver_name, data in stats_data.items():
            sec = data.get("time_sec", 0)
            launches = data.get("launches", 0)
            hours = sec // 3600
            minutes = (sec % 3600) // 60
            time_str = f"{hours}h {minutes:02d}m"
            clean_name = ver_name.replace(".AppImage", "")
            item = QTreeWidgetItem([f"• {clean_name}", time_str, str(launches)])
            self.tree.addTopLevelItem(item)

    def _reset_stats(self):
        reply = QMessageBox.question(
            self,
            "Reset statistics",
            "Clear all usage times and version history?\nThis cannot be undone.",
        )
        if reply != QMessageBox.Yes:
            return
        if self._on_reset:
            self._on_reset()
        self._populate_tree({})
        if self._tot_label:
            self._tot_label.setText("Total: 0h 00m (0 launches)")


class CustomFolderDialog(QDialog):
    def __init__(self, parent, initial_dir, title="Select Directory", is_dark=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(520, 480)
        self.setStyleSheet(make_qss(is_dark))
        self.selected_folder = None
        self.current_path = os.path.abspath(initial_dir)
        if not os.path.isdir(self.current_path):
            self.current_path = USER_HOME

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.path_edit = QLineEdit(self.current_path)
        layout.addWidget(self.path_edit)

        btn_row = QHBoxLayout()
        btn_back = QPushButton("⬆ Parent")
        btn_back.clicked.connect(self.go_back)
        btn_new = QPushButton("➕ New Folder")
        btn_new.clicked.connect(self.create_folder)
        btn_home = QPushButton("Home")
        btn_home.clicked.connect(lambda: self.load_dir(USER_HOME))
        btn_row.addWidget(btn_back)
        btn_row.addWidget(btn_new)
        btn_row.addStretch()
        btn_row.addWidget(btn_home)
        layout.addLayout(btn_row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_double_click)
        layout.addWidget(self.list_widget, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_select = QPushButton("Select Folder")
        btn_select.setObjectName("accent")
        btn_select.clicked.connect(self.confirm)
        bottom.addWidget(btn_cancel)
        bottom.addWidget(btn_select)
        layout.addLayout(bottom)

        self.load_dir(self.current_path)

    def load_dir(self, path):
        try:
            path = os.path.abspath(path)
            if not os.path.isdir(path):
                return
            self.current_path = path
            self.path_edit.setText(path)
            self.list_widget.clear()
            for item in sorted(os.listdir(path)):
                full = os.path.join(path, item)
                if os.path.isdir(full):
                    self.list_widget.addItem(f"📁 {item}")
        except Exception:
            pass

    def go_back(self):
        parent = os.path.dirname(self.current_path)
        if parent != self.current_path:
            self.load_dir(parent)

    def create_folder(self):
        name, ok = QInputDialog.getText(self, "New Folder", "Enter new folder name:")
        if ok and name.strip():
            new_path = os.path.join(self.current_path, name.strip())
            try:
                os.makedirs(new_path, exist_ok=True)
                self.load_dir(new_path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create directory:\n{e}")

    def on_double_click(self, item):
        text = item.text()
        if text.startswith("📁 "):
            folder = text[2:].strip()
            self.load_dir(os.path.join(self.current_path, folder))

    def confirm(self):
        typed = self.path_edit.text().strip()
        if os.path.isdir(typed):
            self.current_path = os.path.abspath(typed)
        sel = self.list_widget.currentItem()
        if sel:
            text = sel.text()
            if text.startswith("📁 "):
                self.current_path = os.path.join(self.current_path, text[2:].strip())
        self.selected_folder = self.current_path
        self.accept()


class PixiFullBuildDialog(QDialog):
    """Progress UI for a full FreeCAD source build via pixi."""

    sig_log = Signal(str)
    sig_progress = Signal(int)
    sig_status = Signal(str)
    sig_finished = Signal(bool, str)
    # title, message — handled on the GUI thread; result stored on the dialog
    sig_confirm = Signal(str, str)

    def __init__(self, parent, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("Compile FreeCAD with pixi")
        self.setMinimumSize(640, 420)
        self.setStyleSheet(make_qss(is_dark))
        self._cancel = False
        self._proc = None
        self._confirm_ok = False
        self._confirm_event = None

        lay = QVBoxLayout(self)
        self.lbl_status = QLabel("Preparing…")
        self.lbl_status.setObjectName("muted")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QTextEdit.NoWrap)
        lay.addWidget(self.log, 1)

        row = QHBoxLayout()
        row.addStretch()
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_close = QPushButton("Close")
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.sig_log.connect(self._append_log)
        self.sig_progress.connect(self.progress.setValue)
        self.sig_status.connect(self.lbl_status.setText)
        self.sig_finished.connect(self._on_finished)
        self.sig_confirm.connect(self._on_confirm)

    def _on_confirm(self, title, message):
        """Always runs on the GUI thread (queued from the worker)."""
        self._confirm_ok = QMessageBox.question(self, title, message) == QMessageBox.Yes
        ev = self._confirm_event
        if ev is not None:
            ev.set()

    def _append_log(self, text):
        self.log.moveCursor(self.log.textCursor().End)
        self.log.insertPlainText(text)
        self.log.moveCursor(self.log.textCursor().End)

    def _on_cancel(self):
        self._cancel = True
        self.lbl_status.setText("Cancelling…")
        proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _on_finished(self, ok, message):
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.lbl_status.setText(message)
        if ok:
            self.progress.setValue(100)

    def reject(self):
        if self.btn_close.isEnabled():
            super().reject()
        else:
            self._on_cancel()


class DownloadDialog(QDialog):
    def __init__(self, parent, app, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("Download FreeCAD Versions")
        self.setFixedSize(540, 360)
        self.setStyleSheet(make_qss(is_dark))
        self.app = app
        self.app.active_download_dialog = self
        self.is_dark = is_dark
        t = get_theme(is_dark)
        self.finished.connect(lambda _=None: setattr(self.app, "active_download_dialog", None))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Install Folder:"))
        row = QHBoxLayout()
        self.install_dir_edit = QLineEdit(self.app.get_install_dir())
        row.addWidget(self.install_dir_edit, 1)
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.change_install_folder)
        row.addWidget(btn_browse)
        layout.addLayout(row)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {t['border']};")
        layout.addWidget(line)

        layout.addWidget(QLabel("Stable Version:"))
        row_s = QHBoxLayout()
        self.combo_stable = QComboBox()
        row_s.addWidget(self.combo_stable, 1)
        self.btn_dl_s = QPushButton("Download")
        self.btn_dl_s.setObjectName("accent")
        self.btn_dl_s.clicked.connect(lambda: self._start_download(self.combo_stable.currentText()))
        row_s.addWidget(self.btn_dl_s)
        layout.addLayout(row_s)

        layout.addWidget(QLabel("Weekly Version:"))
        row_w = QHBoxLayout()
        self.combo_weekly = QComboBox()
        row_w.addWidget(self.combo_weekly, 1)
        self.btn_dl_w = QPushButton("Download")
        self.btn_dl_w.setObjectName("accent")
        self.btn_dl_w.clicked.connect(lambda: self._start_download(self.combo_weekly.currentText()))
        row_w.addWidget(self.btn_dl_w)
        layout.addLayout(row_w)

        layout.addStretch()

        # Progress area at the bottom
        self.lbl_status = QLabel(self.app.lbl_status.text())
        self.lbl_status.setObjectName("muted")
        layout.addWidget(self.lbl_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedHeight(22)
        self.progress.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {t['border']}; border-radius: 6px; "
            f"background: {t['input']}; text-align: center; color: {t['text']}; }}"
            f"QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}"
        )
        layout.addWidget(self.progress)

        cancel_row = QHBoxLayout()
        cancel_row.addStretch()
        self.btn_cancel = QPushButton("Cancel download")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setToolTip("Stop the current download")
        self.btn_cancel.clicked.connect(self._cancel_download)
        cancel_row.addWidget(self.btn_cancel)
        layout.addLayout(cancel_row)

        self.update_combos(self.app.stables_values, self.app.weeklys_values)

    def _cancel_download(self):
        self.app.cancel_download()
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText("Cancelling download...")

    def _start_download(self, filename):
        if not filename:
            return
        install_dir = self.app.get_install_dir()
        target_path = os.path.join(install_dir, filename)
        if os.path.exists(target_path):
            QMessageBox.information(self, "Info", "This version is already installed!")
            return
        self.progress.setValue(0)
        self.btn_dl_s.setEnabled(False)
        self.btn_dl_w.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.app.download_version(filename, from_download_dialog=True)

    def change_install_folder(self):
        folder = pick_existing_directory(
            self, self.install_dir_edit.text(), "Select Installation Folder"
        )
        if folder:
            self.install_dir_edit.setText(folder)
            self.app.set_install_dir(folder)

    def update_combos(self, stables, weeklys):
        self.combo_stable.clear()
        self.combo_stable.addItems(stables)
        self.combo_weekly.clear()
        self.combo_weekly.addItems(weeklys)

    def update_status(self, text):
        self.lbl_status.setText(text or "")
        m = re.search(r"(\d{1,3})\s*%", text or "")
        if m:
            self.progress.setValue(min(100, int(m.group(1))))
        if text and "Download complete" in text:
            self.progress.setValue(100)
            self.lbl_status.setText("Download complete.")
            self.btn_dl_s.setEnabled(True)
            self.btn_dl_w.setEnabled(True)
            self.btn_cancel.setEnabled(False)
            QTimer.singleShot(400, self.accept)
        elif text and (
            "Download error" in text
            or "Already installed" in text
            or "Download cancelled" in text
        ):
            self.btn_dl_s.setEnabled(True)
            self.btn_dl_w.setEnabled(True)
            self.btn_cancel.setEnabled(False)

    def closeEvent(self, event):
        self.app.active_download_dialog = None
        super().closeEvent(event)


class InfoDialog(QDialog):
    def __init__(self, parent, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle("About / Infos")
        self.setMinimumSize(480, 420)
        self.resize(500, 440)
        self.setStyleSheet(make_qss(is_dark))
        t = get_theme(is_dark)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        top = QLabel(
            "FreeCAD Smart Launcher\n\n"
            "• Automatic detection and management of FreeCAD weekly and stable AppImages.\n"
            "• Built-in Pull Request compiler & tester support.\n"
            "• Requires a FreeCAD source folder compiled with cmake/ninja\n"
            "   (see the link below)."
        )
        top.setWordWrap(True)
        layout.addWidget(top)

        link = QLabel('<a href="https://wiki.freecad.org/Compile_on_Linux">https://wiki.freecad.org/Compile_on_Linux</a>')
        link.setOpenExternalLinks(True)
        link.setStyleSheet(f"color: {t['link']};")
        layout.addWidget(link)

        preview = QLabel(
            "• Project library: use 3D view or double-click to open a file in F3D.\n"
            "   Formats: STL, STEP/STP, IGES, BREP, FCStd.\n"
            "   Requires F3D (https://f3d.app/). FCStd files are exported to STEP/IGES first."
        )
        preview.setWordWrap(True)
        layout.addWidget(preview)

        bottom = QLabel(
            "• Unofficial launcher developed by Deltahedra. The AppImages are\n"
            "   extracted from the FreeCAD GitHub."
        )
        bottom.setWordWrap(True)
        layout.addWidget(bottom)
        layout.addStretch()

        btn = QPushButton("OK")
        btn.setObjectName("accent")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, 0, Qt.AlignCenter)


class CopyableErrorDialog(QDialog):
    def __init__(self, parent, title, message, is_dark=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 480)
        self.setStyleSheet(make_qss(is_dark))
        t = get_theme(is_dark)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {t['error']}; font-weight: 700; font-size: 14px;")
        layout.addWidget(lbl)

        self.text = QTextEdit()
        self.text.setPlainText(message)
        self.text.setReadOnly(False)
        layout.addWidget(self.text, 1)

        row = QHBoxLayout()
        btn_copy = QPushButton("Copy to clipboard")
        btn_copy.setObjectName("accent")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_copy)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)


class PRRowWidget(QWidget):
    def __init__(self, pr, app, parent=None):
        super().__init__(parent)
        self.pr = pr
        self.app = app
        t = get_theme(app.var_dark_mode)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 4)
        layout.setSpacing(3)

        # Line 1: #number + date + status
        top = QHBoxLayout()
        top.setSpacing(6)
        num = pr.get("number")
        created = (pr.get("created_at") or "")[:10]  # YYYY-MM-DD
        lbl_num = QLabel(f"#{num}")
        lbl_num.setStyleSheet(f"color: {t['accent']}; font-weight: 700; font-size: 12px;")
        top.addWidget(lbl_num)
        if created:
            lbl_date = QLabel(created)
            lbl_date.setStyleSheet(
                f"color: {t['text']}; font-weight: 600; font-size: 11px;"
            )
            top.addWidget(lbl_date)
        top.addStretch()
        status_text, status_color = app._pr_status_info(pr)
        lbl_status = QLabel(status_text)
        lbl_status.setStyleSheet(f"color: {status_color}; font-size: 11px; font-weight: 600;")
        top.addWidget(lbl_status)
        layout.addLayout(top)

        # Line 2: title
        title = pr.get("title", "Unknown")
        lbl_title = QLabel(title)
        lbl_title.setWordWrap(True)
        lbl_title.setStyleSheet(f"color: {t['text']}; font-size: 12px;")
        layout.addWidget(lbl_title)

        # Line 3: author + compact action buttons
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        bottom.setContentsMargins(0, 2, 0, 0)
        author = pr.get("user", {}).get("login", "unknown")
        lbl_author = QLabel(f"@{author}")
        lbl_author.setStyleSheet(f"color: {t['muted']}; font-size: 11px;")
        bottom.addWidget(lbl_author)
        bottom.addStretch()

        is_fav = any(f.get("number") == num for f in app.pr_favorites)
        star_text = "★" if is_fav else "☆"
        star_color = "#FFD700" if is_fav else t["muted"]

        def icon_btn_style(color):
            return (
                f"QPushButton {{ background: {t['neutral']}; color: {color}; "
                f"border: 1px solid {t['border']}; border-radius: 4px; "
                f"font-size: 13px; font-weight: 700; padding: 0; }}"
                f"QPushButton:hover {{ background: {t['hover']}; }}"
            )

        btn_star = QPushButton(star_text)
        btn_star.setFixedSize(26, 22)
        btn_star.setCursor(QCursor(Qt.PointingHandCursor))
        btn_star.setToolTip("Add/remove favorite")
        btn_star.setStyleSheet(icon_btn_style(star_color))
        btn_star.clicked.connect(lambda: app.toggle_pr_favorite(pr, btn_star))
        bottom.addWidget(btn_star)

        btn_open = QPushButton("↗")
        btn_open.setFixedSize(26, 22)
        btn_open.setCursor(QCursor(Qt.PointingHandCursor))
        btn_open.setToolTip("Open PR on GitHub")
        btn_open.setStyleSheet(icon_btn_style(t["link"]))
        btn_open.clicked.connect(
            lambda: webbrowser.open(f"https://github.com/FreeCAD/FreeCAD/pull/{num}")
        )
        bottom.addWidget(btn_open)

        btn_test = QPushButton("Test")
        btn_test.setFixedSize(44, 22)
        btn_test.setCursor(QCursor(Qt.PointingHandCursor))
        warn_bg = "#8A7040" if app.var_dark_mode else "#C4A86A"
        warn_fg = "#F5F0E0" if app.var_dark_mode else "#2A2418"
        warn_bd = "#705830" if app.var_dark_mode else "#B09858"
        warn_bd_hover = "#FBBF24" if app.var_dark_mode else "#CA8A04"
        btn_test.setStyleSheet(
            f"QPushButton {{ background: {warn_bg}; color: {warn_fg}; "
            f"border: 1px solid {warn_bd}; border-radius: 4px; "
            f"font-size: 11px; font-weight: 600; padding: 0 6px; }}"
            f"QPushButton:hover {{ background: {warn_bd}; border: 1px solid {warn_bd_hover}; }}"
        )
        btn_test.clicked.connect(lambda: app.use_pr_for_testing(pr))
        bottom.addWidget(btn_test)

        layout.addLayout(bottom)

        # Visible separator between PR rows
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {t['border']}; border: none; max-height: 1px;")
        layout.addWidget(sep)


class PRConversationDialog(QDialog):
    """Show pull request description and comments in-app."""

    sig_loaded = Signal(str)  # HTML content

    def __init__(self, parent, pr, is_dark=True):
        super().__init__(parent)
        self.pr = pr or {}
        self.pr_num = self.pr.get("number")
        self.is_dark = is_dark
        self.setWindowTitle(f"PR #{self.pr_num} — Conversation")
        self.setMinimumSize(700, 560)
        self.resize(780, 640)
        self.setStyleSheet(make_qss(is_dark))
        t = get_theme(is_dark)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = self.pr.get("title") or "Pull request"
        hdr = QLabel(f"#{self.pr_num}  —  {title}")
        hdr.setWordWrap(True)
        hdr.setStyleSheet(f"font-weight: 700; font-size: 14px; color: {t['text']};")
        layout.addWidget(hdr)

        author = (self.pr.get("user") or {}).get("login", "unknown")
        meta = QLabel(f"@{author}  ·  {(self.pr.get('created_at') or '')[:10]}")
        meta.setObjectName("muted")
        layout.addWidget(meta)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setOpenLinks(True)
        self.body.setHtml("<p style='color:#888;'>Loading conversation…</p>")
        layout.addWidget(self.body, 1)

        row = QHBoxLayout()
        btn_browser = QPushButton("Open on GitHub")
        btn_browser.setObjectName("linkBtn")
        btn_browser.clicked.connect(
            lambda: webbrowser.open(f"https://github.com/FreeCAD/FreeCAD/pull/{self.pr_num}")
        )
        row.addWidget(btn_browser)
        row.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setObjectName("accent")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_close)
        layout.addLayout(row)

        self.sig_loaded.connect(self._apply_html)
        threading.Thread(target=self._load, daemon=True).start()

    def _section(self, title_html, md_body, image_map=None):
        return (
            f'<div style="border:1px solid #2E2F35;border-radius:8px;padding:12px 14px;'
            f'margin:0 0 14px 0;background:#1C1D21;">'
            f'<div style="font-weight:700;margin-bottom:8px;color:#6BA3F7;">{title_html}</div>'
            f"{_md_to_html(md_body, self.is_dark, image_map=image_map)}"
            f"</div>"
        )

    def _load(self):
        num = self.pr_num
        parts = []
        try:
            pr = _github_get(
                f"https://api.github.com/repos/FreeCAD/FreeCAD/pulls/{num}", timeout=15
            )
            if not isinstance(pr, dict) or pr.get("message"):
                raise RuntimeError(
                    pr.get("message") if isinstance(pr, dict) else "Invalid PR response"
                )
            body = (pr.get("body") or "").strip() or "(no description)"
            author = (pr.get("user") or {}).get("login", "unknown")
            created = (pr.get("created_at") or "")[:19].replace("T", " ")

            comments = _github_get(
                f"https://api.github.com/repos/FreeCAD/FreeCAD/issues/{num}/comments"
                f"?per_page=100&sort=created&direction=asc",
                timeout=15,
            )
            if isinstance(comments, dict) and comments.get("message"):
                raise RuntimeError(comments.get("message"))
            if not isinstance(comments, list):
                comments = []
            comments.sort(key=lambda c: c.get("created_at") or "")

            # Collect and download all images once
            all_md = [body] + [(c.get("body") or "") for c in comments]
            image_map = {}
            urls = []
            for md in all_md:
                urls.extend(_extract_media_urls(md))
            # unique
            seen = set()
            uniq = []
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    uniq.append(u)
            for u in uniq[:40]:
                low = u.lower()
                if any(low.endswith(ext) for ext in (".mp4", ".webm", ".mov")):
                    continue
                if "youtube.com" in low or "youtu.be" in low:
                    continue
                data_uri = _download_image_data_uri(u)
                if data_uri:
                    image_map[u] = data_uri

            parts.append(
                self._section(
                    f"Description — @{author} · {created}", body, image_map=image_map
                )
            )
            if comments:
                for c in comments:
                    c_author = (c.get("user") or {}).get("login", "unknown")
                    c_date = (c.get("created_at") or "")[:19].replace("T", " ")
                    c_body = (c.get("body") or "").strip() or "(empty)"
                    parts.append(
                        self._section(f"@{c_author} · {c_date}", c_body, image_map=image_map)
                    )
            else:
                parts.append(self._section("Conversation", "(no comments yet)", image_map=image_map))
        except Exception as e:
            parts = [f"<p style='color:#F87171;'>Could not load conversation:<br/>{e}</p>"]

        html = (
            "<html><body style='margin:0;padding:8px;background:#121316;color:#E8E8EC;'>"
            + "".join(parts)
            + "</body></html>"
        )
        self.sig_loaded.emit(html)

    def _apply_html(self, html):
        try:
            self.body.setHtml(html)
        except Exception:
            try:
                self.body.setPlainText(html)
            except Exception:
                pass


class UpdateAvailableDialog(QDialog):
    """Startup dialog for first run or available updates."""

    def __init__(self, parent, updates, is_dark=True, welcome=False):
        """
        updates: list of dicts {kind: 'stable'|'weekly', filename: str, label: str}
        choice: None | "both" | "stable" | "weekly"
        """
        super().__init__(parent)
        self.updates = updates
        self.choice = None
        self.welcome = welcome
        self.setMinimumWidth(520)
        self.setStyleSheet(make_qss(is_dark))

        has_stable = any(u.get("kind") == "stable" for u in updates)
        has_weekly = any(u.get("kind") == "weekly" for u in updates)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        if welcome:
            self.setWindowTitle("Welcome")
            title = QLabel("Welcome to FreeCAD Launcher")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            body = QLabel(
                "No FreeCAD version was found on this computer.\n\n"
                "Get started by downloading a stable version, a weekly/dev build, or both."
            )
            body.setWordWrap(True)
            layout.addWidget(body)

            # Show which remote builds will be fetched
            lines = []
            for u in updates:
                kind = "Stable" if u.get("kind") == "stable" else "Weekly / Dev"
                lines.append(f"• {kind}: {u.get('label') or u.get('filename')}")
            if lines:
                detail = QLabel("\n".join(lines))
                detail.setObjectName("muted")
                detail.setWordWrap(True)
                layout.addWidget(detail)

            hint = QLabel("Choose what to download, or Close to explore the launcher first.")
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)

            lbl_stable, lbl_weekly, lbl_both = (
                "Download stable",
                "Download weekly",
                "Download both",
            )
        else:
            self.setWindowTitle("Updates available")
            title = QLabel("New FreeCAD version(s) available")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            lines = []
            for u in updates:
                kind = "Stable" if u.get("kind") == "stable" else "Weekly / Dev"
                lines.append(f"• {kind}: {u.get('label') or u.get('filename')}")
            body = QLabel("\n".join(lines) if lines else "A newer version is available.")
            body.setWordWrap(True)
            layout.addWidget(body)

            hint = QLabel(
                "Choose which version(s) to download, or Close to dismiss this window."
            )
            hint.setObjectName("muted")
            hint.setWordWrap(True)
            layout.addWidget(hint)

            lbl_stable, lbl_weekly, lbl_both = (
                "Update stable",
                "Update weekly",
                "Update both",
            )

        row = QHBoxLayout()
        row.setSpacing(8)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        row.addWidget(btn_close)
        row.addStretch()

        if has_stable:
            btn_stable = QPushButton(lbl_stable)
            btn_stable.setObjectName("accent")
            btn_stable.clicked.connect(lambda: self._choose("stable"))
            row.addWidget(btn_stable)

        if has_weekly:
            btn_weekly = QPushButton(lbl_weekly)
            btn_weekly.setObjectName("warning")
            btn_weekly.clicked.connect(lambda: self._choose("weekly"))
            row.addWidget(btn_weekly)

        if has_stable and has_weekly:
            btn_both = QPushButton(lbl_both)
            btn_both.setObjectName("success")
            btn_both.clicked.connect(lambda: self._choose("both"))
            row.addWidget(btn_both)

        layout.addLayout(row)

    def _choose(self, choice):
        self.choice = choice
        self.accept()


class FreeCADLauncher(QMainWindow):
    # Thread-safe signals for UI updates from worker threads
    sig_releases = Signal(list, list)          # stables, weeklys
    sig_releases_error = Signal(str)
    sig_recent_prs = Signal(list)
    sig_recent_prs_error = Signal(str)
    sig_search_results = Signal(list)
    sig_search_error = Signal(str)
    sig_pr_info = Signal(str)
    sig_status = Signal(str)
    sig_pr_status = Signal(str)
    sig_build_finished = Signal()             # re-enable build buttons
    sig_launch_pr = Signal(str, object)       # exe_path, pr_num — UI-thread launch
    sig_show_error = Signal(str, str)         # title, message
    sig_step_preview = Signal(object, object) # token, triangles
    sig_footer = Signal()
    sig_refresh_versions = Signal()
    sig_download_status = Signal(str)  # progress text for main + download dialog
    sig_download_finished = Signal(str)  # filename after successful download
    sig_milestone = Signal(dict)          # next stable milestone info
    sig_updates_available = Signal(list, bool)  # updates, is_welcome

    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreeCAD Smart Launcher")
        self.setMinimumSize(1000, 640)
        self.resize(1280, 820)

        self.config_data = self.load_config()
        self.stats_data = self.load_stats()
        self.pr_history = self.config_data.get("pr_history", [])
        self.pr_favorites = self.config_data.get("pr_favorites", [])

        self.var_dark_mode = self.config_data.get("dark_mode", True)
        self.var_autoclose = self.config_data.get("auto_close", True)
        self.var_custom_script_env = self.config_data.get("use_custom_script_env", False)
        self.var_vanilla_launch = self.config_data.get("vanilla_launch", False)
        self.var_use_pixi_build = self.config_data.get("use_pixi_build", False)
        self.var_disable_update_reminder = self.config_data.get(
            "disable_update_reminder", False
        )
        self._update_prompt_shown = False
        # filename -> meta for post-update desktop migration / old version cleanup
        self._pending_update_meta = {}
        self._download_cancel = False
        self._download_from_dialog = set()  # filenames started from Download dialog

        os.makedirs(self.get_install_dir(), exist_ok=True)

        # Window icon
        icon_path = self._resolve_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))

        self.recent_files_map = {}
        self.stable_versions = []
        self.weekly_versions = []
        self.stables_values = []
        self.weeklys_values = []
        self.active_download_dialog = None
        self.download_urls = {}
        self.download_sizes = {}
        self.step_preview_cache = {}
        self._preview_token = None
        self._build_in_progress = False
        self._pixi_full_build_in_progress = False
        self._build_cancel_requested = False
        self._current_build_proc = None

        # Connect signals (always on main thread)
        self.sig_releases.connect(self.update_release_combos)
        self.sig_releases_error.connect(lambda msg: self.lbl_status.setText(msg))
        self.sig_recent_prs.connect(self.render_recent_prs)
        self.sig_recent_prs_error.connect(self.render_recent_prs_error)
        self.sig_search_results.connect(self.render_pr_search_results)
        self.sig_search_error.connect(self.render_pr_search_error)
        self.sig_pr_info.connect(lambda text: self.lbl_pr_info.setText(text))
        self.sig_status.connect(lambda text: self.lbl_status.setText(text))
        self.sig_pr_status.connect(lambda text: self.lbl_pr_status.setText(text))
        self.sig_build_finished.connect(self._on_build_finished)
        self.sig_launch_pr.connect(self.launch_compiled_pr_instance)
        self.sig_show_error.connect(self.show_copyable_error)
        self.sig_step_preview.connect(self._apply_step_preview)
        self.sig_footer.connect(self.update_footer_text)
        self.sig_refresh_versions.connect(self.refresh_local_versions)
        self.sig_download_status.connect(self._on_download_status)
        self.sig_download_finished.connect(self._on_update_download_finished)
        self.sig_download_finished.connect(self._on_manual_download_finished)
        self.sig_milestone.connect(self._apply_milestone)
        self.sig_updates_available.connect(self._show_update_available_dialog)

        disable_freecad_start_page()

        self.apply_theme()
        self.build_ui()
        self.refresh_local_versions()
        self.refresh_recent_files()
        self.update_footer_text()

        last_pr = self.config_data.get("last_pr", "")
        if last_pr:
            threading.Thread(target=self.fetch_pr_metadata, args=(str(last_pr),), daemon=True).start()

        threading.Thread(target=self.fetch_github_releases, daemon=True).start()
        threading.Thread(target=self.fetch_recent_prs, daemon=True).start()
        threading.Thread(target=self.fetch_next_milestone, daemon=True).start()

    # ----- Theme -----
    def apply_theme(self):
        t = get_theme(self.var_dark_mode)
        pal = QPalette()
        bg = QColor(t["bg"])
        card = QColor(t["card"])
        text = QColor(t["text"])
        muted = QColor(t["muted"])
        accent = QColor(t["accent"])
        pal.setColor(QPalette.Window, bg)
        pal.setColor(QPalette.WindowText, text)
        pal.setColor(QPalette.Base, QColor(t["input"]))
        pal.setColor(QPalette.AlternateBase, card)
        pal.setColor(QPalette.Text, text)
        pal.setColor(QPalette.Button, card)
        pal.setColor(QPalette.ButtonText, text)
        pal.setColor(QPalette.Highlight, accent)
        pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        pal.setColor(QPalette.ToolTipBase, card)
        pal.setColor(QPalette.ToolTipText, text)
        pal.setColor(QPalette.PlaceholderText, muted)
        app = QApplication.instance()
        if app:
            app.setPalette(pal)
        self.setPalette(pal)
        self.setStyleSheet(make_qss(self.var_dark_mode))

    def toggle_dark_mode(self, checked):
        self.var_dark_mode = checked
        self.config_data["dark_mode"] = checked
        self.save_config()
        # Remember selection across rebuild
        last_pr = ""
        try:
            last_pr = self.combo_pr.currentText().strip()
        except Exception:
            last_pr = self.config_data.get("last_pr", "")
        if last_pr:
            self.config_data["last_pr"] = last_pr
            self.save_config()

        self.apply_theme()
        # Rebuild UI to refresh all colors properly
        central = self.centralWidget()
        if central:
            central.deleteLater()
        self.build_ui()
        self.refresh_local_versions()
        self.refresh_recent_files()
        self.update_footer_text()

        # Restore PR selection + metadata
        if last_pr and hasattr(self, "combo_pr"):
            self.combo_pr.blockSignals(True)
            self.combo_pr.setCurrentText(str(last_pr))
            self.combo_pr.blockSignals(False)
            threading.Thread(
                target=self.fetch_pr_metadata, args=(str(last_pr),), daemon=True
            ).start()

        # Restore milestone bar (cached) or refetch
        cached = getattr(self, "_milestone_data", None)
        if cached:
            self._apply_milestone(cached)
        else:
            threading.Thread(target=self.fetch_next_milestone, daemon=True).start()

        # Refresh PR lists for current theme colors
        threading.Thread(target=self.fetch_recent_prs, daemon=True).start()
        if hasattr(self, "render_favorites"):
            self.render_favorites()

    # ----- Config / Stats -----
    def _resolve_icon_path(self):
        """Locate the launcher icon next to the script or in common user paths."""
        candidates = [
            os.path.join(SCRIPT_DIR, "icon.png"),
            os.path.join(SCRIPT_DIR, "assets", "icon.png"),
            os.path.join(USER_HOME, ".local", "share", "freecad_launcher", "icon.png"),
            os.path.join(self.get_install_dir(), "icon.png"),
        ]
        for p in candidates:
            if p and os.path.isfile(p):
                return p
        return None

    def get_install_dir(self):
        return self.config_data.get("install_dir", DEFAULT_INSTALL_DIR)

    def set_install_dir(self, path):
        path = os.path.abspath(path)
        old_dir = self.get_install_dir()
        os.makedirs(path, exist_ok=True)
        self.config_data["install_dir"] = path
        self.save_config()
        # Move stats next to the new AppImage folder when the install dir changes
        if old_dir != path:
            old_stats = stats_path_for(old_dir)
            new_stats = stats_path_for(path)
            try:
                if os.path.isfile(old_stats) and not os.path.isfile(new_stats):
                    shutil.move(old_stats, new_stats)
            except OSError:
                pass
            try:
                old_cfg = config_path_for(old_dir)
                if os.path.isfile(old_cfg) and os.path.abspath(old_cfg) != os.path.abspath(
                    config_path_for(path)
                ):
                    os.remove(old_cfg)
            except OSError:
                pass
        self.refresh_local_versions()

    def load_config(self):
        default_cfg = {
            "install_dir": DEFAULT_INSTALL_DIR,
            "scan_folder": os.path.join(USER_HOME, "Documents"),
            "src_folder": os.path.join(USER_HOME, "FreeCAD-src"),
            "auto_close": True,
            "use_custom_script_env": False,
            "dark_mode": True,
            "last_pr": "",
            "pr_history": [],
            "pr_favorites": [],
            "last_selected_version": "",
            "vanilla_launch": False,
            "use_pixi_build": False,
            "pixi_build_folder": "",
            "disable_update_reminder": False,
        }
        loaded_from = None
        # Prefer config already stored in the default AppImage folder, then legacy home files
        probe = [
            config_path_for(DEFAULT_INSTALL_DIR),
            LEGACY_CONFIG_FILE,
        ]
        for path in probe:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    default_cfg.update(data)
                    loaded_from = path
                    break
            except Exception:
                pass
        install_dir = default_cfg.get("install_dir") or DEFAULT_INSTALL_DIR
        # If install_dir points elsewhere, also try that folder's config
        alt = config_path_for(install_dir)
        if alt not in probe and os.path.isfile(alt):
            try:
                with open(alt, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    default_cfg.update(data)
                    loaded_from = alt
                    install_dir = default_cfg.get("install_dir") or install_dir
            except Exception:
                pass
        default_cfg["install_dir"] = install_dir
        # Migrate away from ~/.freecad_launcher_config.json when possible
        try:
            os.makedirs(install_dir, exist_ok=True)
            target = config_path_for(install_dir)
            with open(target, "w", encoding="utf-8") as f:
                json.dump(default_cfg, f, indent=2)
            if loaded_from == LEGACY_CONFIG_FILE and os.path.isfile(LEGACY_CONFIG_FILE):
                try:
                    os.remove(LEGACY_CONFIG_FILE)
                except OSError:
                    pass
        except Exception:
            pass
        return default_cfg

    def save_config(self):
        install_dir = self.get_install_dir()
        os.makedirs(install_dir, exist_ok=True)
        path = config_path_for(install_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.config_data, f, indent=2)

    def load_stats(self):
        install_dir = self.get_install_dir()
        candidates = [
            stats_path_for(install_dir),
            stats_path_for(DEFAULT_INSTALL_DIR),
            LEGACY_STATS_FILE,
        ]
        seen = set()
        for path in candidates:
            if not path or path in seen or not os.path.isfile(path):
                continue
            seen.add(path)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                # Migrate into the AppImage install folder
                target = stats_path_for(install_dir)
                if os.path.abspath(path) != os.path.abspath(target):
                    try:
                        os.makedirs(install_dir, exist_ok=True)
                        with open(target, "w", encoding="utf-8") as out:
                            json.dump(data, out, indent=2)
                        if path == LEGACY_STATS_FILE:
                            try:
                                os.remove(LEGACY_STATS_FILE)
                            except OSError:
                                pass
                    except Exception:
                        pass
                return data
            except Exception:
                continue
        return {}

    def save_stats(self):
        install_dir = self.get_install_dir()
        os.makedirs(install_dir, exist_ok=True)
        path = stats_path_for(install_dir)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.stats_data, f, indent=2)

    def get_stat_key(self, filename):
        if "weekly" in filename.lower() or "dev" in filename.lower():
            return f"FreeCAD {self.format_version_name(filename, is_weekly=True)}"
        return filename

    def open_link(self, url):
        webbrowser.open(url)

    def update_footer_text(self):
        total_sec = sum(d.get("time_sec", 0) for d in self.stats_data.values())
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        self.lbl_footer.setText(f"You used FreeCAD for {hours}h {minutes}m. Keep pushing")

    def format_version_name(self, filename, is_weekly):
        base = filename[:-9] if filename.endswith(".AppImage") else filename
        if is_weekly:
            match = re.search(r"(weekly-[\d.]+)", base, re.IGNORECASE)
            if match:
                return match.group(1)
            match_date = re.search(r"(\d{4}[.-]\d{2}[.-]\d{2})", base)
            if match_date:
                return f"weekly-{match_date.group(1)}"
            return base.replace("FreeCAD_", "")
        else:
            clean = base.replace("FreeCAD_", "").replace("FreeCAD-", "")
            parts = clean.split("-")
            if parts:
                return parts[0]
            return clean

    # ----- UI Construction -----
    def _card(self):
        f = QFrame()
        f.setObjectName("card")
        return f

    def build_ui(self):
        central = QWidget()
        t = get_theme(self.var_dark_mode)
        central.setStyleSheet(f"background-color: {t['bg']};")
        self.setCentralWidget(central)

        # Outer vertical layout: header + main content + footer
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 12, 16, 8)
        outer.setSpacing(8)

        # Global header so the 3 columns share the same top edge
        header = QHBoxLayout()
        header.setSpacing(10)
        icon_path = self._resolve_icon_path()
        if icon_path:
            icon_lbl = QLabel()
            pix = QPixmap(icon_path)
            if not pix.isNull():
                icon_lbl.setPixmap(
                    pix.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                icon_lbl.setFixedSize(32, 32)
                header.addWidget(icon_lbl)
        title = QLabel("FreeCAD Launcher")
        evo = get_evolventa_family()
        if evo:
            title.setFont(QFont(evo, 20, QFont.Bold))
            title.setStyleSheet("font-size: 22px; font-weight: 700; letter-spacing: 0.2px;")
        else:
            title.setStyleSheet(
                'font-family: "Evolventa", "Noto Sans", "Segoe UI", sans-serif; '
                "font-size: 22px; font-weight: 700; letter-spacing: 0.2px;"
            )
        header.addWidget(title)
        header.addStretch()
        outer.addLayout(header)

        # Main 3-column content (aligned tops)
        content = QWidget()
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.setAlignment(Qt.AlignTop)
        outer.addWidget(content, 1)

        # ========== LEFT COLUMN (scrollable so blocks never overlap when shrunk) ==========
        left_inner = QWidget()
        left = QVBoxLayout(left_inner)
        left.setContentsMargins(0, 0, 4, 0)
        left.setSpacing(10)
        left.setAlignment(Qt.AlignTop)

        # --- Block 1: Installed Versions ---
        b1 = self._card()
        b1.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        b1_lay = QVBoxLayout(b1)
        b1_lay.setContentsMargins(14, 12, 14, 12)
        b1_lay.setSpacing(8)
        b1_lay.setSizeConstraint(QLayout.SetMinimumSize)
        self._active_version_kind = "stable"  # "stable" or "weekly"

        # Stable header + combo
        stable_hdr = QHBoxLayout()
        stable_hdr.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel("STABLE")
        lbl.setObjectName("sectionTitle")
        stable_hdr.addWidget(lbl)
        stable_hdr.addStretch()
        self.lbl_stable_status = QLabel("Checking…")
        self.lbl_stable_status.setObjectName("muted")
        self.lbl_stable_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        stable_hdr.addWidget(self.lbl_stable_status)
        b1_lay.addLayout(stable_hdr)

        self.stable_combo = QComboBox()
        self.stable_combo.setFixedHeight(32)
        self.stable_combo.setMinimumWidth(120)
        self.stable_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.stable_combo.currentIndexChanged.connect(lambda: self.on_version_combo_changed("stable"))
        self.stable_combo.activated.connect(lambda: self.on_version_combo_changed("stable"))
        b1_lay.addWidget(self.stable_combo)

        # Weekly header + combo
        weekly_hdr = QHBoxLayout()
        weekly_hdr.setContentsMargins(0, 4, 0, 0)
        lbl = QLabel("WEEKLY / DEV")
        lbl.setObjectName("sectionTitle")
        weekly_hdr.addWidget(lbl)
        weekly_hdr.addStretch()
        self.lbl_weekly_status = QLabel("Checking…")
        self.lbl_weekly_status.setObjectName("muted")
        self.lbl_weekly_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        weekly_hdr.addWidget(self.lbl_weekly_status)
        b1_lay.addLayout(weekly_hdr)

        self.weekly_combo = QComboBox()
        self.weekly_combo.setFixedHeight(32)
        self.weekly_combo.setMinimumWidth(120)
        self.weekly_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.weekly_combo.currentIndexChanged.connect(lambda: self.on_version_combo_changed("weekly"))
        self.weekly_combo.activated.connect(lambda: self.on_version_combo_changed("weekly"))
        b1_lay.addWidget(self.weekly_combo)

        # One row: Download, Desktop entry, Delete, Launch (aligned)
        btn_wrap = QWidget()
        btn_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn_row = QHBoxLayout(btn_wrap)
        btn_row.setContentsMargins(0, 4, 0, 4)
        btn_row.setSpacing(6)
        btn_dl = QPushButton("Download")
        btn_dl.setObjectName("accent")
        btn_dl.setFixedHeight(28)
        btn_dl.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn_dl.clicked.connect(self.open_download_dialog)
        btn_menu = QPushButton("Desktop entry")
        btn_menu.setObjectName("accent")
        btn_menu.setFixedHeight(28)
        btn_menu.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn_menu.setToolTip(
            "Create a .desktop entry in the start menu for the selected version"
        )
        btn_menu.clicked.connect(self.create_desktop_entry)
        btn_del = QPushButton("Delete")
        btn_del.setObjectName("danger")
        btn_del.setFixedHeight(28)
        btn_del.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn_del.clicked.connect(self.delete_local)
        btn_launch = QPushButton("Launch")
        btn_launch.setObjectName("success")
        btn_launch.setFixedHeight(28)
        btn_launch.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        btn_launch.clicked.connect(self.launch_local)
        btn_row.addWidget(btn_dl)
        btn_row.addWidget(btn_menu)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_del)
        btn_row.addWidget(btn_launch)
        b1_lay.addWidget(btn_wrap)

        left.addWidget(b1)

        # --- Block 3: Community ---
        b3 = self._card()
        b3_lay = QVBoxLayout(b3)
        b3_lay.setContentsMargins(14, 12, 14, 12)
        b3_lay.setSpacing(8)

        lbl = QLabel("FREECAD COMMUNITY")
        lbl.setObjectName("sectionTitle")
        b3_lay.addWidget(lbl)

        links = QHBoxLayout()
        for text, url in [
            ("🌐 Website", "https://www.freecad.org/"),
            ("💬 Forum", "https://forum.freecad.org/"),
            ("💻 GitHub", "https://github.com/FreeCAD/FreeCAD"),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked=False, u=url: self.open_link(u))
            links.addWidget(btn)
        b3_lay.addLayout(links)

        # Next stable milestone progress
        self.lbl_milestone = QLabel("Next stable: loading…")
        self.lbl_milestone.setObjectName("muted")
        self.lbl_milestone.setWordWrap(True)
        self.lbl_milestone.setCursor(QCursor(Qt.PointingHandCursor))
        self.lbl_milestone.setToolTip("Open milestone on GitHub")
        self._milestone_url = "https://github.com/FreeCAD/FreeCAD/milestones"
        self.lbl_milestone.mousePressEvent = lambda e: webbrowser.open(self._milestone_url)
        b3_lay.addWidget(self.lbl_milestone)

        t = get_theme(self.var_dark_mode)
        self.milestone_bar = QProgressBar()
        self.milestone_bar.setRange(0, 100)
        self.milestone_bar.setValue(0)
        self.milestone_bar.setTextVisible(True)
        self.milestone_bar.setFixedHeight(16)
        self.milestone_bar.setFormat("%p%")
        self.milestone_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {t['border']}; border-radius: 4px; "
            f"background: {t['input']}; text-align: center; color: {t['text']}; "
            f"font-size: 10px; font-weight: 600; }}"
            f"QProgressBar::chunk {{ background: {t['accent']}; border-radius: 3px; }}"
        )
        b3_lay.addWidget(self.milestone_bar)

        self.lbl_milestone_detail = QLabel("")
        self.lbl_milestone_detail.setObjectName("muted")
        self.lbl_milestone_detail.setStyleSheet("font-size: 10.5px;")
        b3_lay.addWidget(self.lbl_milestone_detail)

        left.addWidget(b3)

        # --- Block 4: Options ---
        b4 = self._card()
        b4_lay = QVBoxLayout(b4)
        b4_lay.setContentsMargins(14, 12, 14, 12)
        b4_lay.setSpacing(4)

        lbl = QLabel("LAUNCHER OPTIONS")
        lbl.setObjectName("sectionTitle")
        b4_lay.addWidget(lbl)

        self.chk_autoclose = QCheckBox("Close launcher on launch")
        self.chk_autoclose.setChecked(self.var_autoclose)
        self.chk_autoclose.toggled.connect(self.toggle_autoclose)
        b4_lay.addWidget(self.chk_autoclose)

        self.chk_hidpi = QCheckBox("Launch with HiDPI scale (Tutorial Mode)")
        self.chk_hidpi.setChecked(self.var_custom_script_env)
        self.chk_hidpi.toggled.connect(self.toggle_custom_script_env)
        b4_lay.addWidget(self.chk_hidpi)

        self.chk_dark = QCheckBox("Dark mode")
        self.chk_dark.setChecked(self.var_dark_mode)
        self.chk_dark.toggled.connect(self.toggle_dark_mode)
        b4_lay.addWidget(self.chk_dark)

        self.chk_vanilla = QCheckBox("Vanilla launch (empty profile, like first run)")
        self.chk_vanilla.setChecked(self.var_vanilla_launch)
        self.chk_vanilla.toggled.connect(self.toggle_vanilla_launch)
        b4_lay.addWidget(self.chk_vanilla)

        self.chk_no_update_reminder = QCheckBox("Turn off update reminder")
        self.chk_no_update_reminder.setChecked(self.var_disable_update_reminder)
        self.chk_no_update_reminder.setToolTip(
            "Do not show the startup window when a newer FreeCAD version is available"
        )
        self.chk_no_update_reminder.toggled.connect(self.toggle_disable_update_reminder)
        b4_lay.addWidget(self.chk_no_update_reminder)
        left.addWidget(b4)

        left.addStretch()
        left_scroll = QScrollArea()
        self._left_scroll = left_scroll
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setWidget(left_inner)
        left_scroll.setMinimumWidth(400)
        left_scroll.setMaximumWidth(560)
        left_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        root.addWidget(left_scroll, 0)

        # ========== CENTER: PR Panel ==========
        pr_panel = self._card()
        pr_lay = QVBoxLayout(pr_panel)
        pr_lay.setContentsMargins(12, 12, 12, 12)
        pr_lay.setSpacing(8)

        pr_header = QHBoxLayout()
        lbl = QLabel("PULL REQUESTS")
        lbl.setObjectName("sectionTitle")
        pr_header.addWidget(lbl)
        pr_header.addStretch()
        btn_refresh = QPushButton("↻")
        btn_refresh.setFixedSize(32, 28)
        btn_refresh.setToolTip("Refresh pull requests")
        btn_refresh.setStyleSheet(
            f"QPushButton {{ font-size: 16px; font-weight: 700; padding: 0; }}"
        )
        btn_refresh.clicked.connect(lambda: threading.Thread(target=self.fetch_recent_prs, daemon=True).start())
        pr_header.addWidget(btn_refresh)
        pr_lay.addLayout(pr_header)

        self.pr_tabs = QTabWidget()
        # Recent
        self.pr_recent_scroll = QScrollArea()
        self.pr_recent_scroll.setWidgetResizable(True)
        self.pr_recent_inner = QWidget()
        self.pr_recent_layout = QVBoxLayout(self.pr_recent_inner)
        self.pr_recent_layout.setAlignment(Qt.AlignTop)
        self.pr_recent_scroll.setWidget(self.pr_recent_inner)
        self.pr_tabs.addTab(self.pr_recent_scroll, "Recent")

        # Search
        search_page = QWidget()
        search_lay = QVBoxLayout(search_page)
        search_lay.setContentsMargins(4, 4, 4, 4)
        search_bar = QHBoxLayout()
        self.pr_search_edit = QLineEdit()
        self.pr_search_edit.setPlaceholderText("PR title, developer login, or PR number...")
        self.pr_search_edit.returnPressed.connect(self.search_prs)
        search_bar.addWidget(self.pr_search_edit, 1)
        btn_search = QPushButton("Search")
        btn_search.setObjectName("accent")
        btn_search.clicked.connect(self.search_prs)
        search_bar.addWidget(btn_search)
        search_lay.addLayout(search_bar)

        self.pr_search_scroll = QScrollArea()
        self.pr_search_scroll.setWidgetResizable(True)
        self.pr_search_inner = QWidget()
        self.pr_search_layout = QVBoxLayout(self.pr_search_inner)
        self.pr_search_layout.setAlignment(Qt.AlignTop)
        self.pr_search_scroll.setWidget(self.pr_search_inner)
        search_lay.addWidget(self.pr_search_scroll, 1)
        self.pr_tabs.addTab(search_page, "Search")

        # Favorites
        self.pr_fav_scroll = QScrollArea()
        self.pr_fav_scroll.setWidgetResizable(True)
        self.pr_fav_inner = QWidget()
        self.pr_fav_layout = QVBoxLayout(self.pr_fav_inner)
        self.pr_fav_layout.setAlignment(Qt.AlignTop)
        self.pr_fav_scroll.setWidget(self.pr_fav_inner)
        self.pr_tabs.addTab(self.pr_fav_scroll, "Favoris")

        pr_lay.addWidget(self.pr_tabs, 1)

        btn_more = QPushButton("VIEW MORE ON GITHUB")
        btn_more.setObjectName("accent")
        btn_more.clicked.connect(lambda: webbrowser.open("https://github.com/FreeCAD/FreeCAD/pulls"))
        pr_lay.addWidget(btn_more)

        # --- Test a GitHub PR (under the PR list) ---
        b2 = self._card()
        b2.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        b2_lay = QVBoxLayout(b2)
        b2_lay.setContentsMargins(14, 12, 14, 12)
        b2_lay.setSpacing(8)

        lbl = QLabel("TEST A GITHUB PULL REQUEST")
        lbl.setObjectName("sectionTitle")
        b2_lay.addWidget(lbl)

        self.pr_setup_stack = QStackedWidget()
        b2_lay.addWidget(self.pr_setup_stack)

        # Page 0 — no source configured yet
        onboard = QWidget()
        on_lay = QVBoxLayout(onboard)
        on_lay.setContentsMargins(0, 4, 0, 0)
        on_lay.setSpacing(10)
        on_msg = QLabel(
            "Want to try a PR?\nYou need a compiled FreeCAD source tree first."
        )
        on_msg.setObjectName("muted")
        on_msg.setWordWrap(True)
        on_lay.addWidget(on_msg)
        on_btns = QHBoxLayout()
        on_btns.setSpacing(8)
        self.btn_pr_already = QPushButton("FreeCAD already compiled")
        self.btn_pr_already.setObjectName("accent")
        self.btn_pr_already.setFixedHeight(28)
        self.btn_pr_already.setToolTip(
            "Select an existing FreeCAD source folder (with CMakeLists.txt)."
        )
        self.btn_pr_already.clicked.connect(self._pick_existing_pr_source)
        on_btns.addWidget(self.btn_pr_already)
        self.btn_pr_compile_pixi = QPushButton("Compile FreeCAD (pixi)")
        self.btn_pr_compile_pixi.setObjectName("warning")
        self.btn_pr_compile_pixi.setFixedHeight(28)
        self.btn_pr_compile_pixi.setToolTip(
            "Clone FreeCAD if needed and compile it with pixi."
        )
        self.btn_pr_compile_pixi.clicked.connect(self.compile_freecad_with_pixi)
        on_btns.addWidget(self.btn_pr_compile_pixi)
        on_lay.addLayout(on_btns)
        self.pr_setup_stack.addWidget(onboard)

        # Page 1 — normal PR test controls
        ready = QWidget()
        ready_lay = QVBoxLayout(ready)
        ready_lay.setContentsMargins(0, 0, 0, 0)
        ready_lay.setSpacing(8)

        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Source:"))
        self.src_folder_edit = QLineEdit(self.config_data.get("src_folder", ""))
        self.src_folder_edit.editingFinished.connect(self._on_src_folder_edited)
        src_row.addWidget(self.src_folder_edit, 1)
        btn_src = QPushButton("Browse...")
        btn_src.clicked.connect(self.change_src_folder)
        src_row.addWidget(btn_src)
        ready_lay.addLayout(src_row)

        pr_row = QHBoxLayout()
        pr_row.setSpacing(8)
        pr_row.addWidget(QLabel("PR #:"))
        self.combo_pr = QComboBox()
        self.combo_pr.setEditable(True)
        self.combo_pr.addItems(self.pr_history)
        self.combo_pr.setFixedWidth(100)
        self.combo_pr.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        last_pr = self.config_data.get("last_pr", "")
        if last_pr:
            self.combo_pr.setCurrentText(str(last_pr))
        self.combo_pr.currentTextChanged.connect(self.on_pr_changed)
        pr_row.addWidget(self.combo_pr)

        self.btn_view_github = QPushButton("GitHub")
        self.btn_view_github.setObjectName("linkBtn")
        self.btn_view_github.setFixedHeight(26)
        self.btn_view_github.setMinimumWidth(64)
        self.btn_view_github.clicked.connect(self.open_pr_on_github)
        pr_row.addWidget(self.btn_view_github)
        pr_row.addStretch()
        ready_lay.addLayout(pr_row)

        pr_row2 = QHBoxLayout()
        pr_row2.setSpacing(8)

        self.btn_compile_pr = QPushButton("Build")
        self.btn_compile_pr.setObjectName("warning")
        self.btn_compile_pr.setFixedHeight(26)
        self.btn_compile_pr.clicked.connect(self.build_and_run_pr)
        pr_row2.addWidget(self.btn_compile_pr, 1)

        self.btn_stop_pr = QPushButton("Stop")
        self.btn_stop_pr.setObjectName("danger")
        self.btn_stop_pr.setFixedHeight(26)
        self.btn_stop_pr.setEnabled(False)
        self.btn_stop_pr.clicked.connect(self.stop_build)
        pr_row2.addWidget(self.btn_stop_pr, 1)

        self.btn_just_launch_pr = QPushButton("Launch")
        self.btn_just_launch_pr.setObjectName("success")
        self.btn_just_launch_pr.setFixedHeight(26)
        self.btn_just_launch_pr.clicked.connect(self.just_launch_pr)
        pr_row2.addWidget(self.btn_just_launch_pr, 1)
        ready_lay.addLayout(pr_row2)

        self.chk_pixi = QCheckBox("Use pixi to build PRs (not system cmake)")
        self.chk_pixi.setToolTip(
            "Checked: PR builds use pixi (pixi run configure / build).\n"
            "Unchecked: PR builds use system cmake/ninja.\n\n"
            "Enable this if you compiled FreeCAD with the pixi button.\n"
            "Leave it off if you use a normal system cmake build.\n\n"
            "FreeCAD always ships a pixi.toml — that file alone does not mean "
            "you must use pixi."
        )
        self.chk_pixi.setChecked(self.var_use_pixi_build)
        self.chk_pixi.toggled.connect(self.toggle_use_pixi_build)
        ready_lay.addWidget(self.chk_pixi)

        pixi_full_row = QHBoxLayout()
        self.btn_pixi_full = QPushButton("Compile FreeCAD with pixi…")
        self.btn_pixi_full.setObjectName("warning")
        self.btn_pixi_full.setFixedHeight(26)
        self.btn_pixi_full.setToolTip(
            "Clone or update FreeCAD sources and build with pixi "
            "(downloads dependencies automatically)."
        )
        self.btn_pixi_full.clicked.connect(self.compile_freecad_with_pixi)
        pixi_full_row.addWidget(self.btn_pixi_full)
        pixi_full_row.addStretch()
        ready_lay.addLayout(pixi_full_row)

        self.lbl_pr_info = ElidedLabel("Title: -\nAuthor: -")
        self.lbl_pr_info.setObjectName("muted")
        ready_lay.addWidget(self.lbl_pr_info)
        self.lbl_pr_status = ElidedLabel("Ready.")
        self.lbl_pr_status.setObjectName("muted")
        ready_lay.addWidget(self.lbl_pr_status)

        self.pr_setup_stack.addWidget(ready)
        pr_lay.addWidget(b2)
        self._update_pr_setup_panel()

        root.addWidget(pr_panel, 1)  # grows with window
        self.render_favorites()

        # ========== RIGHT: Project Library ==========
        right = self._card()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 12, 12, 12)
        right_lay.setSpacing(8)

        lbl = QLabel("PROJECT LIBRARY")
        lbl.setObjectName("sectionTitle")
        right_lay.addWidget(lbl)

        # Project preview and F3D button
        preview_wrap = QWidget()
        preview_wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        preview_lay = QVBoxLayout(preview_wrap)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        preview_lay.setSpacing(4)

        self.thumb_label = QLabel()
        self.thumb_label.setMinimumSize(140, 90)
        self.thumb_label.setMaximumHeight(180)
        self.thumb_label.setFixedHeight(150)
        self.thumb_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet(
            f"background: {get_theme(self.var_dark_mode)['input']}; border-radius: 6px;"
        )
        self.thumb_label.setText("No project selected")
        self.thumb_label.installEventFilter(self)
        self._preview_base_pixmap = None
        self._preview_triangles = None
        self._preview_mode = "none"
        self._preview_resize_timer = QTimer(self)
        self._preview_resize_timer.setSingleShot(True)
        self._preview_resize_timer.setInterval(50)
        self._preview_resize_timer.timeout.connect(self._scale_preview_to_label)
        preview_lay.addWidget(self.thumb_label)

        view3d_row = QHBoxLayout()
        view3d_row.setContentsMargins(0, 0, 0, 0)
        view3d_row.addStretch()
        self.btn_view_3d = QPushButton("3D view")
        self.btn_view_3d.setObjectName("accent")
        self.btn_view_3d.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_view_3d.setToolTip(
            "Open the selected file in F3D (FCStd is exported to STEP/IGES first)"
        )
        self.btn_view_3d.setFixedHeight(26)
        self.btn_view_3d.setEnabled(False)
        self.btn_view_3d.clicked.connect(self.open_interactive_mesh_preview)
        view3d_row.addWidget(self.btn_view_3d)
        preview_lay.addLayout(view3d_row)
        right_lay.addWidget(preview_wrap, 0)

        self.lbl_file_info = QLabel("No project selected")
        self.lbl_file_info.setObjectName("muted")
        self.lbl_file_info.setWordWrap(True)
        right_lay.addWidget(self.lbl_file_info)

        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(120)
        self.recent_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.recent_list.itemSelectionChanged.connect(self.on_project_select)
        self.recent_list.itemDoubleClicked.connect(self.open_interactive_mesh_preview)
        right_lay.addWidget(self.recent_list, 1)

        scan_row = QHBoxLayout()
        btn_scan = QPushButton("Scan Folder...")
        btn_scan.clicked.connect(self.change_scan_folder)
        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_recent_files)
        scan_row.addWidget(btn_scan)
        scan_row.addWidget(btn_refresh)
        right_lay.addLayout(scan_row)

        btn_launch_proj = QPushButton("LAUNCH PROJECT")
        btn_launch_proj.setObjectName("success")
        btn_launch_proj.setFixedHeight(28)
        btn_launch_proj.clicked.connect(self.launch_project)
        right_lay.addWidget(btn_launch_proj)

        btn_open_running = QPushButton("OPEN IN RUNNING INSTANCE")
        btn_open_running.setObjectName("accent")
        btn_open_running.clicked.connect(self.launch_project_in_current_instance)
        right_lay.addWidget(btn_open_running)

        btn_launch_pr = QPushButton("LAUNCH PROJECT WITH PR")
        btn_launch_pr.setObjectName("warning")
        btn_launch_pr.clicked.connect(self.launch_project_with_pr)
        right_lay.addWidget(btn_launch_pr)

        root.addWidget(right, 1)  # grows with window

        # ========== FOOTER ==========
        # Status line (GitHub / downloads) just above the usage footer
        self.lbl_status = ElidedLabel("Searching for updates on GitHub...")
        self.lbl_status.setObjectName("muted")
        outer.addWidget(self.lbl_status)

        footer_widget = QWidget()
        footer_lay = QHBoxLayout(footer_widget)
        footer_lay.setContentsMargins(0, 2, 0, 0)
        footer_lay.setSpacing(8)
        self.lbl_footer = QLabel("")
        self.lbl_footer.setObjectName("footer")
        footer_lay.addWidget(self.lbl_footer)
        footer_lay.addStretch()
        t_footer = get_theme(self.var_dark_mode)
        powered = QLabel(
            "POWERED BY "
            f'<a href="https://www.youtube.com/@deltahedra3D" '
            f'style="color: {t_footer["accent"]}; text-decoration: underline; '
            f'font-weight: 800; letter-spacing: 0.8px;">DELTAHEDRA</a>'
        )
        powered.setObjectName("powered")
        powered.setOpenExternalLinks(True)
        powered.setToolTip("Open Deltahedra on YouTube")
        powered.setCursor(QCursor(Qt.PointingHandCursor))
        footer_lay.addWidget(powered)
        btn_info = QPushButton("Infos")
        btn_info.clicked.connect(self.show_info)
        btn_stats = QPushButton("Statistics")
        btn_stats.clicked.connect(self.show_stats)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        footer_lay.addWidget(btn_info)
        footer_lay.addWidget(btn_stats)
        footer_lay.addWidget(btn_close)
        outer.addWidget(footer_widget)

        # Loading placeholder for recent PRs
        self._clear_layout(self.pr_recent_layout)
        ph = QLabel("Loading recent PRs...")
        ph.setObjectName("muted")
        ph.setAlignment(Qt.AlignCenter)
        self.pr_recent_layout.addWidget(ph)

        self._clear_layout(self.pr_search_layout)
        ph2 = QLabel("Type a keyword or PR number\nand press Enter or Search.")
        ph2.setObjectName("muted")
        ph2.setAlignment(Qt.AlignCenter)
        ph2.setWordWrap(True)
        self.pr_search_layout.addWidget(ph2)

        # Once the window is shown (widgets polished), size the minimums from content
        QTimer.singleShot(0, self._fit_minimum_size)

    def _fit_minimum_size(self):
        """Make the minimum sizes match what the columns really need.

        A window minimum smaller than the layout minimum makes Qt squeeze the
        columns below their content: buttons get clipped and cards overlap.
        """
        try:
            sc = self._left_scroll
            need = (
                sc.widget().minimumSizeHint().width()
                + sc.verticalScrollBar().sizeHint().width()
                + 6
            )
            sc.setMinimumWidth(max(380, need))
            sc.setMaximumWidth(max(480, need))
            lay = self.centralWidget().layout()
            lay.activate()
            hint = lay.minimumSize()
            w, h = max(1000, hint.width()), max(640, hint.height())
            screen = self.screen()
            if screen is not None:
                avail = screen.availableGeometry()
                w, h = min(w, avail.width()), min(h, avail.height())
            self.setMinimumSize(w, h)
            if self.width() < w or self.height() < h:
                self.resize(max(self.width(), w), max(self.height(), h))
        except Exception as e:
            print(f"[ui] could not fit minimum size: {e}", flush=True)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ----- PR helpers -----
    def parse_pr_number(self, text):
        text = (text or "").strip()
        if not text:
            return ""
        if text.isdigit():
            return text
        m = re.search(r"#(\d+)", text)
        if m:
            return m.group(1)
        m = re.search(r"/pull[s]?/(\d+)", text)
        if m:
            return m.group(1)
        m = re.search(r"(\d{2,7})", text)
        if m:
            return m.group(1)
        return ""

    def get_pr_number(self):
        return self.parse_pr_number(self.combo_pr.currentText())

    def on_pr_changed(self, text=None):
        pr_num = self.get_pr_number()
        if not pr_num:
            self.lbl_pr_info.setText("Title: -\nAuthor: -")
            return
        raw = self.combo_pr.currentText().strip()
        if raw != pr_num and (not raw.isdigit()):
            self.combo_pr.setCurrentText(pr_num)
        threading.Thread(target=self.fetch_pr_metadata, args=(pr_num,), daemon=True).start()

    def fetch_pr_metadata(self, pr_num):
        try:
            data = _github_get(f"https://api.github.com/repos/FreeCAD/FreeCAD/pulls/{pr_num}", timeout=8)
            title = data.get("title", "Unknown")
            if len(title) > 40:
                title = title[:37] + "..."
            author = data.get("user", {}).get("login", "Unknown")
            self.sig_pr_info.emit(f"Title: {title}\nAuthor: @{author}")
        except Exception:
            self.sig_pr_info.emit("Title: Not found (GitHub API)\nAuthor: -")

    def open_pr_on_github(self):
        pr_num = self.get_pr_number()
        if pr_num:
            webbrowser.open(f"https://github.com/FreeCAD/FreeCAD/pull/{pr_num}")

    def open_pr_conversation(self, pr):
        """Open PR conversation in an in-app window (no browser)."""
        if not pr or not pr.get("number"):
            return
        PRConversationDialog(self, pr, is_dark=self.var_dark_mode).exec()

    def fetch_recent_prs(self):
        try:
            url = (
                "https://api.github.com/repos/FreeCAD/FreeCAD/pulls"
                "?state=all&sort=created&direction=desc&per_page=15"
            )
            data = _github_get(url, timeout=12)
            self.sig_recent_prs.emit(data)
        except Exception as e:
            print(f"[GitHub PRs] error: {e}", flush=True)
            self.sig_recent_prs_error.emit(str(e))

    def render_recent_prs_error(self, err):
        self._clear_layout(self.pr_recent_layout)
        lbl = QLabel(f"Could not load PRs:\n{err}")
        lbl.setObjectName("muted")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        self.pr_recent_layout.addWidget(lbl)

    def render_recent_prs(self, prs_data):
        self._clear_layout(self.pr_recent_layout)
        if not prs_data:
            lbl = QLabel("No pull requests found.")
            lbl.setObjectName("muted")
            lbl.setAlignment(Qt.AlignCenter)
            self.pr_recent_layout.addWidget(lbl)
            return
        for pr in prs_data:
            row = PRRowWidget(pr, self)
            self.pr_recent_layout.addWidget(row)
        self.pr_recent_layout.addStretch()

    def search_prs(self):
        query = self.pr_search_edit.text().strip()
        if not query:
            return
        self._clear_layout(self.pr_search_layout)
        lbl = QLabel("Searching...")
        lbl.setObjectName("muted")
        lbl.setAlignment(Qt.AlignCenter)
        self.pr_search_layout.addWidget(lbl)
        threading.Thread(target=self.perform_pr_search, args=(query,), daemon=True).start()

    def perform_pr_search(self, query):
        try:
            query = (query or "").strip()
            if not query:
                self.sig_search_results.emit([])
                return
            if query.isdigit():
                data = _github_get(
                    f"https://api.github.com/repos/FreeCAD/FreeCAD/pulls/{query}", timeout=10
                )
                results = [data] if isinstance(data, dict) and data.get("number") else []
                self.sig_search_results.emit(results)
                return

            # Title search and author search as separate queries
            by_num = {}
            author = query[1:] if query.startswith("@") else query
            search_queries = []
            if " " in query:
                search_queries.append(f'repo:FreeCAD/FreeCAD is:pr in:title "{query}"')
            else:
                search_queries.append(f"repo:FreeCAD/FreeCAD is:pr in:title {query}")
                # Developer login (exact GitHub username)
                search_queries.append(f"repo:FreeCAD/FreeCAD is:pr author:{author}")

            errors = []
            for q_raw in search_queries:
                try:
                    q = urllib.parse.quote(q_raw)
                    url = (
                        f"https://api.github.com/search/issues?q={q}"
                        f"&per_page=25&sort=created&order=desc"
                    )
                    data = _github_get(url, timeout=12)
                    if isinstance(data, dict) and data.get("message"):
                        errors.append(str(data.get("message")))
                        continue
                    for item in data.get("items", []) if isinstance(data, dict) else []:
                        n = item.get("number")
                        if n is not None:
                            by_num[n] = item
                except Exception as e:
                    errors.append(str(e))

            results = sorted(
                by_num.values(),
                key=lambda item: item.get("created_at") or "",
                reverse=True,
            )
            if not results and errors:
                # Surface first error only if nothing found
                raise RuntimeError(errors[0])
            self.sig_search_results.emit(results)
        except Exception as e:
            print(f"[GitHub search] error: {e}", flush=True)
            self.sig_search_error.emit(str(e))

    def render_pr_search_error(self, err):
        self._clear_layout(self.pr_search_layout)
        lbl = QLabel(f"Search failed:\n{err}")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignCenter)
        self.pr_search_layout.addWidget(lbl)

    def render_pr_search_results(self, results):
        self._clear_layout(self.pr_search_layout)
        if not results:
            lbl = QLabel("No matching pull requests found.")
            lbl.setObjectName("muted")
            lbl.setAlignment(Qt.AlignCenter)
            self.pr_search_layout.addWidget(lbl)
            return
        for pr in results:
            row = PRRowWidget(pr, self)
            self.pr_search_layout.addWidget(row)
        self.pr_search_layout.addStretch()

    def _pr_status_info(self, pr):
        t = get_theme(self.var_dark_mode)
        if pr.get("draft"):
            return "Draft", t["muted"]
        merged_at = pr.get("merged_at")
        if merged_at is None and "pull_request" in pr:
            merged_at = pr["pull_request"].get("merged_at")
        if pr.get("state") == "closed":
            if merged_at:
                return "Merged", t["accent"]
            return "Closed", t["danger"]
        return "Open", t["success"]

    def toggle_pr_favorite(self, pr, btn=None):
        num = pr.get("number")
        if num is None:
            return
        existing_idx = next((i for i, f in enumerate(self.pr_favorites) if f.get("number") == num), None)
        t = get_theme(self.var_dark_mode)

        def _star_style(color):
            return (
                f"QPushButton {{ background: {t['neutral']}; color: {color}; "
                f"border: 1px solid {t['border']}; border-radius: 4px; "
                f"font-size: 13px; font-weight: 700; padding: 0; }}"
                f"QPushButton:hover {{ background: {t['hover']}; }}"
            )

        if existing_idx is not None:
            del self.pr_favorites[existing_idx]
            if btn:
                btn.setText("☆")
                btn.setStyleSheet(_star_style(t["muted"]))
        else:
            merged_at = pr.get("merged_at")
            if merged_at is None and "pull_request" in pr:
                merged_at = pr["pull_request"].get("merged_at")
            fav = {
                "number": num,
                "title": pr.get("title", "Unknown"),
                "user": {"login": pr.get("user", {}).get("login", "unknown")},
                "state": pr.get("state", "open"),
                "draft": pr.get("draft", False),
                "merged_at": merged_at,
            }
            self.pr_favorites.append(fav)
            if btn:
                btn.setText("★")
                btn.setStyleSheet(_star_style("#FFD700"))
        self.config_data["pr_favorites"] = self.pr_favorites
        self.save_config()
        self.render_favorites()

    def render_favorites(self):
        if not hasattr(self, "pr_fav_layout"):
            return
        self._clear_layout(self.pr_fav_layout)
        if not self.pr_favorites:
            lbl = QLabel("No favorites yet.\nClick ★ on a PR to add it here.")
            lbl.setObjectName("muted")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            self.pr_fav_layout.addWidget(lbl)
            return
        for fav in self.pr_favorites:
            row = PRRowWidget(fav, self)
            self.pr_fav_layout.addWidget(row)
        self.pr_fav_layout.addStretch()

    def use_pr_for_testing(self, pr):
        num = str(pr.get("number", ""))
        if not num:
            return
        self.combo_pr.setCurrentText(num)
        title = pr.get("title", "Unknown")
        if len(title) > 40:
            title = title[:37] + "..."
        author = pr.get("user", {}).get("login", "Unknown")
        self.lbl_pr_info.setText(f"Title: {title}\nAuthor: @{author}")
        self.combo_pr.setFocus()

    # ----- Build / Launch PR -----
    def _source_uses_pixi(self, src_dir):
        """
        Use pixi only when the user opted in (checkbox), or as fallback when
        cmake is missing but pixi + pixi.toml are available.
        Upstream FreeCAD always ships pixi.toml — that alone must not force pixi.
        """
        if not src_dir or not os.path.isfile(os.path.join(src_dir, "pixi.toml")):
            return False
        if not shutil.which("pixi"):
            return False
        if getattr(self, "var_use_pixi_build", False):
            return True
        # Fallback: no system cmake, but pixi can provide the toolchain
        if not shutil.which("cmake"):
            return True
        return False

    def get_pr_exe_path(self, src_dir):
        """Return (build_dir, freecad_executable) for classic or pixi layouts."""
        candidates = [
            os.path.join(src_dir, "build", "debug", "bin", "FreeCAD"),
            os.path.join(src_dir, "build", "release", "bin", "FreeCAD"),
            os.path.join(src_dir, "build", "bin", "FreeCAD"),
        ]
        for exe_path in candidates:
            if os.path.isfile(exe_path):
                return os.path.dirname(os.path.dirname(exe_path)), exe_path
        build_dir = os.path.join(src_dir, "build", "debug")
        if not os.path.isdir(build_dir):
            build_dir = os.path.join(src_dir, "build")
        return build_dir, os.path.join(build_dir, "bin", "FreeCAD")

    def _check_build_dependencies(self, src_dir=None):
        missing = []
        if not shutil.which("git"):
            missing.append("git")
        use_pixi = self._source_uses_pixi(src_dir) if src_dir else False
        if use_pixi:
            if not shutil.which("pixi"):
                missing.append("pixi")
        else:
            if not shutil.which("cmake"):
                missing.append("cmake")
        return missing

    def build_and_run_pr(self):
        pr_num = self.get_pr_number()
        src_dir = self.src_folder_edit.text().strip()

        if self._build_in_progress:
            QMessageBox.warning(self, "Warning", "A build is already in progress. Please wait.")
            return
        if not pr_num:
            QMessageBox.warning(self, "Warning", "Please enter a valid numeric PR number.")
            return
        if not src_dir or not os.path.exists(src_dir):
            QMessageBox.critical(self, "Error", f"Source directory not found:\n{src_dir}\nPlease select a valid Git repository.")
            return
        if not os.path.exists(os.path.join(src_dir, ".git")):
            QMessageBox.critical(self, "Error", f"The selected folder is not a valid Git repository:\n{src_dir}")
            return

        missing = self._check_build_dependencies(src_dir)
        if missing:
            hint = ""
            if any("pixi" in m for m in missing):
                hint = (
                    "\n\nThis FreeCAD source uses pixi (pixi.toml found).\n"
                    "Install pixi: https://pixi.sh\n"
                    "  curl -fsSL https://pixi.sh/install.sh | bash"
                )
            QMessageBox.critical(
                self, "Missing dependencies",
                "The following tools are required but not found in PATH:\n\n"
                + "\n".join(f"  • {m}" for m in missing)
                + "\n\nInstall them before building a PR."
                + hint
            )
            return

        if pr_num not in self.pr_history:
            self.pr_history.insert(0, pr_num)
            self.pr_history = self.pr_history[:10]
        self.config_data["pr_history"] = self.pr_history
        self.config_data["src_folder"] = src_dir
        self.config_data["last_pr"] = pr_num
        self.save_config()
        self.combo_pr.clear()
        self.combo_pr.addItems(self.pr_history)
        self.combo_pr.setCurrentText(pr_num)

        self._build_in_progress = True
        self._build_cancel_requested = False
        self._current_build_proc = None
        self.btn_compile_pr.setEnabled(False)
        self.btn_stop_pr.setEnabled(True)
        self.btn_just_launch_pr.setEnabled(False)

        progress_percent_re = re.compile(r"\[\s*(\d{1,3})%\]")
        progress_fraction_re = re.compile(r"\[(\d+)/(\d+)\]")

        def log_build(msg):
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            line = f"[{timestamp}] {msg}\n"
            print(msg, flush=True)
            try:
                with open(BUILD_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

        def run_step(cmd, cwd=None, progress_cb=None):
            if self._build_cancel_requested:
                raise BuildCancelled()
            log_build(f"$ {' '.join(cmd)}  (cwd={cwd or os.getcwd()})")
            # New session so we can kill the whole process group (cmake/ninja children)
            proc = subprocess.Popen(
                cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, start_new_session=True,
            )
            self._current_build_proc = proc
            lines = []
            last_pct = -1
            try:
                for line in proc.stdout:
                    if self._build_cancel_requested:
                        self._kill_build_process(proc)
                        raise BuildCancelled()
                    print(line, end="", flush=True)
                    lines.append(line)
                    if len(lines) > 200:
                        lines.pop(0)
                    if progress_cb:
                        pct = None
                        m = progress_percent_re.search(line)
                        if m:
                            pct = int(m.group(1))
                        else:
                            m2 = progress_fraction_re.search(line)
                            if m2 and int(m2.group(2)) > 0:
                                pct = min(100, int(int(m2.group(1)) * 100 / int(m2.group(2))))
                        if pct is not None and pct != last_pct:
                            last_pct = pct
                            progress_cb(pct)
                proc.wait()
            finally:
                self._current_build_proc = None
            if self._build_cancel_requested:
                raise BuildCancelled()
            if proc.returncode != 0:
                tail = "".join(lines[-40:]).strip()
                raise RuntimeError(f"Command failed: {' '.join(cmd)}\n\n{tail}")
            return proc

        def update_build_progress(pct):
            self.sig_pr_status.emit(f"Compiling PR #{pr_num}... ({pct}%)")

        def task():
            try:
                log_build(f"=== Starting build for PR #{pr_num} ===")
                build_dir, exe_path = self.get_pr_exe_path(src_dir)
                self.sig_pr_status.emit(f"Fetching PR #{pr_num}...")

                try:
                    status = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=src_dir, capture_output=True, text=True, timeout=10
                    )
                    if status.stdout.strip():
                        log_build("Dirty worktree detected — stashing local changes")
                        run_step(["git", "stash", "push", "-u", "-m", f"launcher-auto-stash-before-pr-{pr_num}"], cwd=src_dir)
                except Exception as stash_err:
                    log_build(f"Stash check skipped: {stash_err}")

                run_step(["git", "fetch", "origin", f"pull/{pr_num}/head", "--force"], cwd=src_dir)
                run_step(["git", "checkout", "-B", f"pr-{pr_num}", "FETCH_HEAD"], cwd=src_dir)

                self.sig_pr_status.emit(f"Configuring PR #{pr_num}...")
                run_step(["git", "submodule", "update", "--init", "--recursive"], cwd=src_dir)

                jobs = str(os.cpu_count() or 4)
                use_pixi = self._source_uses_pixi(src_dir)

                if use_pixi:
                    log_build("Detected pixi.toml — building with pixi")
                    self.sig_pr_status.emit(f"Configuring PR #{pr_num} (pixi)...")
                    run_step(["pixi", "run", "configure"], cwd=src_dir)
                    self.sig_pr_status.emit(f"Compiling PR #{pr_num}... (0%)")
                    run_step(
                        ["pixi", "run", "build", "--", "-j", jobs],
                        cwd=src_dir,
                        progress_cb=update_build_progress,
                    )
                else:
                    cache_file = os.path.join(build_dir, "CMakeCache.txt")
                    cmake_configure_cmd = [
                        "cmake", "-B", build_dir, "-S", src_dir, "-DCMAKE_BUILD_TYPE=Debug",
                    ]
                    if shutil.which("ninja"):
                        cmake_configure_cmd += ["-G", "Ninja"]
                    if shutil.which("ccache"):
                        cmake_configure_cmd += [
                            "-DCMAKE_C_COMPILER_LAUNCHER=ccache",
                            "-DCMAKE_CXX_COMPILER_LAUNCHER=ccache",
                        ]
                    try:
                        run_step(cmake_configure_cmd)
                    except RuntimeError as cmake_err:
                        if os.path.exists(cache_file) and (
                            "CMAKE_BUILD_TYPE" in str(cmake_err)
                            or "cache" in str(cmake_err).lower()
                        ):
                            log_build("CMake cache conflict — wiping build dir and reconfiguring")
                            shutil.rmtree(build_dir, ignore_errors=True)
                            run_step(cmake_configure_cmd)
                        else:
                            raise

                    self.sig_pr_status.emit(f"Compiling PR #{pr_num}... (0%)")
                    run_step(
                        ["cmake", "--build", build_dir, "-j", jobs],
                        progress_cb=update_build_progress,
                    )

                _, exe_path = self.get_pr_exe_path(src_dir)
                if not os.path.exists(exe_path):
                    for alt in (
                        os.path.join(src_dir, "build", "debug", "bin", "FreeCAD"),
                        os.path.join(src_dir, "build", "release", "bin", "FreeCAD"),
                        os.path.join(src_dir, "build", "bin", "FreeCAD"),
                    ):
                        if os.path.isfile(alt):
                            exe_path = alt
                            break

                if os.path.exists(exe_path):
                    log_build(f"Build succeeded — launching {exe_path}")
                    # Launch must happen on the UI thread (signal, not QTimer from worker)
                    self.sig_pr_status.emit(f"PR #{pr_num} successfully compiled & launched!")
                    self.sig_launch_pr.emit(exe_path, pr_num)
                else:
                    raise FileNotFoundError("Compiled executable FreeCAD not found in build directory.")

            except BuildCancelled:
                log_build("Build cancelled by user")
                self.sig_pr_status.emit(f"Build cancelled for PR #{pr_num}")
            except Exception as e:
                err_text = str(e)
                log_build(f"BUILD FAILED: {err_text}")
                self.sig_pr_status.emit(f"Build failed for PR #{pr_num}")
                self.sig_show_error.emit(f"Compilation Error - PR #{pr_num}", err_text)
            finally:
                self._build_in_progress = False
                self._build_cancel_requested = False
                self._current_build_proc = None
                self.sig_build_finished.emit()

        threading.Thread(target=task, daemon=True).start()

    def _on_build_finished(self):
        self.btn_compile_pr.setEnabled(True)
        self.btn_stop_pr.setEnabled(False)
        self.btn_just_launch_pr.setEnabled(True)

    def _kill_build_process(self, proc):
        """Terminate a build process and its entire process group (cmake/ninja kids)."""
        if proc is None or proc.poll() is not None:
            return
        try:
            # Kill the whole session started with start_new_session=True
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
        # Give it a moment, then SIGKILL if still alive
        def force_kill():
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
            if proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        threading.Thread(target=force_kill, daemon=True).start()

    def stop_build(self):
        if not self._build_in_progress:
            return
        reply = QMessageBox.question(self, "Stop build", "Stop the build currently in progress?")
        if reply != QMessageBox.Yes:
            return
        self._build_cancel_requested = True
        self.btn_stop_pr.setEnabled(False)
        self.lbl_pr_status.setText("Stopping build...")
        self._kill_build_process(self._current_build_proc)

    def just_launch_pr(self):
        pr_num = self.get_pr_number()
        src_dir = self.src_folder_edit.text().strip()
        if not pr_num or not src_dir:
            QMessageBox.warning(self, "Warning", "Please select or enter a valid PR number.")
            return
        _, exe_path = self.get_pr_exe_path(src_dir)
        if not os.path.exists(exe_path):
            alt_path = os.path.join(src_dir, "build", "bin", "FreeCAD")
            if os.path.exists(alt_path):
                exe_path = alt_path
        if os.path.exists(exe_path):
            self.launch_compiled_pr_instance(exe_path, pr_num)
        else:
            QMessageBox.critical(self, "Error", f"No executable found for PR #{pr_num}.\nCompile it at least once first!")

    def launch_compiled_pr_instance(self, exe_path, pr_num):
        self.lbl_pr_status.setText(f"PR #{pr_num} successfully compiled & launched!")
        env = os.environ.copy()
        if self.var_custom_script_env:
            env["QT_SCALE_FACTOR"] = "1.66"
            env["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
            env["XCURSOR_SIZE"] = "80"
        vanilla_dir = self._apply_vanilla_env(env)
        pr_start_time = time.time()
        pr_process = subprocess.Popen([exe_path], env=env)

        stat_key = self.get_stat_key(f"PR #{pr_num}")

        if self.var_autoclose:
            # Close the window but stay alive until the PR build exits, so the
            # session is recorded and the vanilla profile is cleaned up.
            self.close()
            pr_process.wait()
            self._record_session(stat_key, pr_start_time)
            if vanilla_dir:
                shutil.rmtree(vanilla_dir, ignore_errors=True)
        else:
            def wait_and_log():
                pr_process.wait()
                self._record_session(stat_key, pr_start_time)
                if vanilla_dir:
                    shutil.rmtree(vanilla_dir, ignore_errors=True)
            threading.Thread(target=wait_and_log, daemon=True).start()

    # ----- Versions / Download -----
    def open_download_dialog(self):
        dlg = self.active_download_dialog
        # Reuse only if the previous dialog is still open/visible
        if dlg is not None:
            try:
                if dlg.isVisible():
                    dlg.raise_()
                    dlg.activateWindow()
                    return
            except RuntimeError:
                # C++ object already deleted
                pass
            self.active_download_dialog = None
        DownloadDialog(self, self, is_dark=self.var_dark_mode).exec()


    def _refresh_which_path(self):
        """Ensure ~/.local/bin and ~/.pixi/bin are visible for shutil.which."""
        extras = [
            os.path.join(USER_HOME, ".pixi", "bin"),
            os.path.join(USER_HOME, ".local", "bin"),
        ]
        path = os.environ.get("PATH", "")
        parts = path.split(os.pathsep) if path else []
        changed = False
        for d in extras:
            if d and d not in parts and os.path.isdir(d):
                parts.insert(0, d)
                changed = True
        if changed:
            os.environ["PATH"] = os.pathsep.join(parts)

    def _detect_pkg_install_cmd(self, package):
        """Return a privileged install argv for a system package, or None."""
        if shutil.which("apt-get"):
            return ["apt-get", "install", "-y", package]
        if shutil.which("dnf"):
            return ["dnf", "install", "-y", package]
        if shutil.which("pacman"):
            return ["pacman", "-S", "--noconfirm", package]
        if shutil.which("zypper"):
            return ["zypper", "--non-interactive", "install", package]
        return None

    def _run_privileged(self, argv):
        """Run argv with pkexec or sudo."""
        if shutil.which("pkexec"):
            cmd = ["pkexec"] + list(argv)
        elif shutil.which("sudo"):
            cmd = ["sudo"] + list(argv)
        else:
            raise RuntimeError("Neither pkexec nor sudo is available to install system packages.")
        return subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    def _ensure_git_installed(self):
        """Install git via the distro package manager if missing."""
        self._refresh_which_path()
        if shutil.which("git"):
            return True
        reply = QMessageBox.question(
            self,
            "Install git?",
            "git is required but was not found.\n\n"
            "Install git now using your system package manager?\n"
            "(Administrator privileges will be requested.)",
        )
        if reply != QMessageBox.Yes:
            return False
        pkg_cmd = self._detect_pkg_install_cmd("git")
        if not pkg_cmd:
            QMessageBox.critical(
                self,
                "Cannot install git",
                "No supported package manager found (apt, dnf, pacman, zypper).\n"
                "Please install git manually, then retry.",
            )
            return False
        self.lbl_status.setText("Installing git…")
        QApplication.processEvents()
        try:
            proc = self._run_privileged(pkg_cmd)
        except Exception as e:
            QMessageBox.critical(self, "git install failed", str(e))
            return False
        self._refresh_which_path()
        if proc.returncode != 0 or not shutil.which("git"):
            err = (proc.stderr or proc.stdout or "").strip()[-800:]
            QMessageBox.critical(
                self,
                "git install failed",
                f"Could not install git automatically.\n\n{err}",
            )
            return False
        QMessageBox.information(self, "git", "git was installed successfully.")
        return True

    def _ensure_pixi_installed(self):
        """Install pixi with the official user-level installer if missing."""
        self._refresh_which_path()
        if shutil.which("pixi"):
            return True
        pixi_bin = os.path.join(USER_HOME, ".pixi", "bin", "pixi")
        if os.path.isfile(pixi_bin) and os.access(pixi_bin, os.X_OK):
            self._refresh_which_path()
            if not shutil.which("pixi"):
                os.environ["PATH"] = (
                    os.path.join(USER_HOME, ".pixi", "bin")
                    + os.pathsep
                    + os.environ.get("PATH", "")
                )
            if shutil.which("pixi"):
                return True

        reply = QMessageBox.question(
            self,
            "Install pixi?",
            "pixi is required but was not found.\n\n"
            "Install pixi now for your user account?\n"
            "(Official installer from https://pixi.sh — no system root required.)",
        )
        if reply != QMessageBox.Yes:
            return False

        self.lbl_status.setText("Installing pixi…")
        QApplication.processEvents()
        install_script = os.path.join(tempfile.gettempdir(), "pixi-install.sh")
        proc = None
        try:
            req = urllib.request.Request(
                "https://pixi.sh/install.sh",
                headers={"User-Agent": "FreeCAD-Smart-Launcher/2.1"},
            )
            with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
                script = resp.read()
            with open(install_script, "wb") as f:
                f.write(script)
            proc = subprocess.run(
                ["bash", install_script],
                capture_output=True,
                text=True,
                timeout=600,
                env=os.environ.copy(),
            )
        except Exception as e:
            QMessageBox.critical(self, "pixi install failed", str(e))
            return False
        finally:
            try:
                os.remove(install_script)
            except OSError:
                pass

        self._refresh_which_path()
        if not shutil.which("pixi"):
            os.environ["PATH"] = (
                os.path.join(USER_HOME, ".pixi", "bin")
                + os.pathsep
                + os.environ.get("PATH", "")
            )
        if not shutil.which("pixi"):
            err = ""
            if proc is not None:
                err = (proc.stderr or proc.stdout or "").strip()[-800:]
            QMessageBox.critical(
                self,
                "pixi install failed",
                "pixi was not found after the installer ran.\n"
                "Open a new terminal or log out/in, then retry.\n\n"
                f"{err}",
            )
            return False
        QMessageBox.information(
            self,
            "pixi",
            "pixi was installed successfully.\n"
            f"Binary: {shutil.which('pixi')}",
        )
        return True

    def compile_freecad_with_pixi(self):
        """Guided full FreeCAD build: pick folder, confirm each step, pixi configure/build."""
        if getattr(self, "_pixi_full_build_in_progress", False) or self._build_in_progress:
            QMessageBox.warning(self, "Busy", "A build is already in progress.")
            return

        if not self._ensure_git_installed():
            return
        if not self._ensure_pixi_installed():
            return

        start = self.config_data.get("pixi_build_folder") or self.config_data.get("src_folder") or USER_HOME
        folder = pick_existing_directory(self, start, "Select folder for FreeCAD sources / build")
        if not folder:
            return

        if os.path.isfile(os.path.join(folder, "pixi.toml")) and os.path.isfile(
            os.path.join(folder, "CMakeLists.txt")
        ):
            src_dir = folder
            need_clone = False
        elif os.path.isfile(os.path.join(folder, "FreeCAD", "pixi.toml")) and os.path.isfile(
            os.path.join(folder, "FreeCAD", "CMakeLists.txt")
        ):
            src_dir = os.path.join(folder, "FreeCAD")
            need_clone = False
        else:
            src_dir = os.path.join(folder, "FreeCAD")
            need_clone = not os.path.isdir(os.path.join(src_dir, ".git"))

        plan = (
            f"Build folder: {src_dir}\n\n"
            f"{'1. Clone FreeCAD from GitHub into this folder' if need_clone else '1. Use existing sources (optional git pull)'}\n"
            "2. pixi run configure  (downloads dependencies)\n"
            "3. pixi run build\n\n"
            "This can take a long time and several GB of disk space.\nContinue?"
        )
        if QMessageBox.question(self, "Compile with pixi", plan) != QMessageBox.Yes:
            return

        self.config_data["pixi_build_folder"] = folder
        self.config_data["src_folder"] = src_dir
        self.save_config()
        if hasattr(self, "src_folder_edit"):
            self.src_folder_edit.setText(src_dir)

        dlg = PixiFullBuildDialog(self, is_dark=self.var_dark_mode)
        self._pixi_full_build_in_progress = True
        if hasattr(self, "btn_pixi_full"):
            self.btn_pixi_full.setEnabled(False)

        # cmake/ninja: [42%] or [12/34] — git: "Receiving objects:  67%"
        progress_percent_re = re.compile(r"\[\s*(\d{1,3})%\]")
        progress_fraction_re = re.compile(r"\[(\d+)/(\d+)\]")
        git_progress_re = re.compile(
            r"(?:Receiving objects|Resolving deltas|Counting objects|"
            r"Compressing objects|Updating files|Filtering content):\s*(\d+)%",
            re.I,
        )
        any_pct_re = re.compile(r"(?<![\d.])(\d{1,3})%(?!\d)")

        def _parse_progress_line(line):
            m = progress_percent_re.search(line)
            if m:
                return min(100, int(m.group(1)))
            m = git_progress_re.search(line)
            if m:
                return min(100, int(m.group(1)))
            m2 = progress_fraction_re.search(line)
            if m2 and int(m2.group(2)) > 0:
                return min(100, int(int(m2.group(1)) * 100 / int(m2.group(2))))
            m = any_pct_re.search(line)
            if m:
                return min(100, int(m.group(1)))
            return None

        def run_cmd(cmd, cwd=None):
            if dlg._cancel:
                raise BuildCancelled()
            dlg.sig_log.emit("$ " + " ".join(cmd) + "\n")
            # Binary read so git carriage-return progress is not stuck buffered as text lines
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,
                bufsize=0,
                start_new_session=True,
            )
            dlg._proc = proc
            lines = []
            buf = b""
            last_log_line = ""
            try:
                while True:
                    if dlg._cancel:
                        try:
                            os.killpg(proc.pid, signal.SIGTERM)
                        except Exception:
                            proc.terminate()
                        raise BuildCancelled()
                    chunk = proc.stdout.read(256)
                    if not chunk:
                        break
                    buf += chunk
                    while True:
                        n_idx = buf.find(b"\n")
                        r_idx = buf.find(b"\r")
                        if n_idx < 0 and r_idx < 0:
                            break
                        if n_idx < 0:
                            cut = r_idx
                        elif r_idx < 0:
                            cut = n_idx
                        else:
                            cut = min(n_idx, r_idx)
                        raw = buf[:cut]
                        buf = buf[cut + 1:]
                        line = raw.decode("utf-8", errors="replace")
                        line_st = line.strip()
                        if not line_st:
                            continue
                        if git_progress_re.search(line_st) or (
                            any_pct_re.search(line_st) and "MiB" in line_st
                        ):
                            if line_st != last_log_line:
                                dlg.sig_log.emit(line_st + "\n")
                                last_log_line = line_st
                        else:
                            dlg.sig_log.emit(line_st + "\n")
                            last_log_line = line_st
                        lines.append(line_st)
                        if len(lines) > 80:
                            lines.pop(0)
                        pct = _parse_progress_line(line_st)
                        if pct is not None:
                            dlg.sig_progress.emit(pct)
                if buf.strip():
                    line = buf.decode("utf-8", errors="replace").strip()
                    if line:
                        dlg.sig_log.emit(line + "\n")
                        pct = _parse_progress_line(line)
                        if pct is not None:
                            dlg.sig_progress.emit(pct)
                proc.wait()
            finally:
                dlg._proc = None
            if dlg._cancel:
                raise BuildCancelled()
            if proc.returncode != 0:
                tail = "\n".join(lines[-30:]).strip()
                raise RuntimeError(
                    "Command failed (%s): %s\n%s"
                    % (proc.returncode, " ".join(cmd), tail)
                )

        def ask_continue(title, text):
            # QTimer from a worker thread is unsafe; use a queued Signal instead.
            if dlg._cancel:
                return False
            ev = threading.Event()
            dlg._confirm_ok = False
            dlg._confirm_event = ev
            dlg.sig_confirm.emit(title, text)
            while not ev.wait(timeout=0.2):
                if dlg._cancel:
                    return False
            return bool(dlg._confirm_ok)

        def task():
            try:
                if need_clone:
                    dlg.sig_status.emit("Waiting for confirmation: clone repository…")
                    if not ask_continue(
                        "Clone FreeCAD?",
                        f"Clone https://github.com/FreeCAD/FreeCAD.git into:\n{src_dir}\n\nContinue?",
                    ):
                        raise BuildCancelled()
                    dlg.sig_status.emit("Cloning FreeCAD (this may take a while)…")
                    dlg.sig_progress.emit(5)
                    os.makedirs(folder, exist_ok=True)
                    if os.path.isdir(src_dir) and not os.path.isdir(os.path.join(src_dir, ".git")):
                        shutil.rmtree(src_dir, ignore_errors=True)
                    run_cmd(
                        [
                            "git", "clone", "--progress", "--recurse-submodules",
                            "https://github.com/FreeCAD/FreeCAD.git", src_dir,
                        ],
                        cwd=folder,
                    )
                    dlg.sig_progress.emit(100)
                    dlg.sig_status.emit("Clone finished.")
                else:
                    dlg.sig_status.emit("Waiting for confirmation: update sources…")
                    if ask_continue(
                        "Update sources?",
                        f"Run git pull in:\n{src_dir}\n\nContinue? (No = keep current sources)",
                    ):
                        dlg.sig_status.emit("Updating sources…")
                        try:
                            run_cmd(["git", "pull", "--ff-only", "--progress"], cwd=src_dir)
                        except RuntimeError as e:
                            dlg.sig_log.emit(f"git pull skipped/failed: {e}\n")
                    run_cmd(
                        ["git", "submodule", "update", "--init", "--recursive"],
                        cwd=src_dir,
                    )

                if dlg._cancel:
                    raise BuildCancelled()

                dlg.sig_status.emit("Waiting for confirmation: pixi configure…")
                if not ask_continue(
                    "Configure with pixi?",
                    "Next step: pixi run configure\n"
                    "This downloads/resolves dependencies (can be large).\n\nContinue?",
                ):
                    raise BuildCancelled()

                dlg.sig_status.emit("pixi configure (fetching dependencies)…")
                dlg.sig_progress.emit(15)
                run_cmd(["pixi", "run", "configure"], cwd=src_dir)

                if dlg._cancel:
                    raise BuildCancelled()

                jobs = str(os.cpu_count() or 4)
                dlg.sig_status.emit("Waiting for confirmation: pixi build…")
                if not ask_continue(
                    "Build FreeCAD?",
                    f"Next step: pixi run build -j {jobs}\n"
                    "Compilation can take a long time.\n\nContinue?",
                ):
                    raise BuildCancelled()

                dlg.sig_status.emit(f"Building with pixi (-j {jobs})…")
                dlg.sig_progress.emit(25)
                run_cmd(["pixi", "run", "build", "--", "-j", jobs], cwd=src_dir)

                _, exe = self.get_pr_exe_path(src_dir)
                if not os.path.isfile(exe):
                    for alt in (
                        os.path.join(src_dir, "build", "debug", "bin", "FreeCAD"),
                        os.path.join(src_dir, "build", "release", "bin", "FreeCAD"),
                        os.path.join(src_dir, "build", "bin", "FreeCAD"),
                    ):
                        if os.path.isfile(alt):
                            exe = alt
                            break
                # User chose the pixi full-build path — remember it for PR builds
                self.var_use_pixi_build = True
                self.config_data["use_pixi_build"] = True
                self.save_config()

                def _sync_pixi_chk():
                    if hasattr(self, "chk_pixi"):
                        self.chk_pixi.blockSignals(True)
                        self.chk_pixi.setChecked(True)
                        self.chk_pixi.blockSignals(False)
                    self._update_pr_setup_panel()

                QTimer.singleShot(0, _sync_pixi_chk)

                # Remember that this tree was built via the pixi full-build flow
                self.var_use_pixi_build = True
                self.config_data["use_pixi_build"] = True
                self.save_config()

                def _sync_pixi_chk():
                    if hasattr(self, "chk_pixi"):
                        self.chk_pixi.blockSignals(True)
                        self.chk_pixi.setChecked(True)
                        self.chk_pixi.blockSignals(False)
                    self._update_pr_setup_panel()

                QTimer.singleShot(0, _sync_pixi_chk)

                if os.path.isfile(exe):
                    msg = f"Build finished.\n\nExecutable:\n{exe}"
                    dlg.sig_finished.emit(True, msg)
                    dlg.sig_log.emit(msg + "\n")
                else:
                    dlg.sig_finished.emit(
                        True,
                        "Build finished, but FreeCAD binary was not found in the usual paths.",
                    )
            except BuildCancelled:
                dlg.sig_finished.emit(False, "Build cancelled.")
            except Exception as e:
                dlg.sig_finished.emit(False, f"Build failed:\n{e}")
                dlg.sig_log.emit(f"\nERROR: {e}\n")
            finally:
                self._pixi_full_build_in_progress = False

                def _reenable():
                    if hasattr(self, "btn_pixi_full"):
                        self.btn_pixi_full.setEnabled(True)

                QTimer.singleShot(0, _reenable)

        threading.Thread(target=task, daemon=True).start()
        dlg.exec()
        self._update_pr_setup_panel()

    def show_info(self):
        InfoDialog(self, is_dark=self.var_dark_mode).exec()

    def show_copyable_error(self, title, message):
        CopyableErrorDialog(self, title, message, is_dark=self.var_dark_mode).exec()

    def on_version_combo_changed(self, kind):
        """User picked a version from stable or weekly dropdown."""
        self._active_version_kind = kind
        if kind == "stable":
            idx = self.stable_combo.currentIndex()
            if 0 <= idx < len(self.stable_versions):
                self.config_data["last_selected_version"] = self.stable_versions[idx]["display"]
                self.save_config()
        else:
            idx = self.weekly_combo.currentIndex()
            if 0 <= idx < len(self.weekly_versions):
                self.config_data["last_selected_version"] = self.weekly_versions[idx]["display"]
                self.save_config()
        self._update_version_highlight()

    def _update_version_highlight(self):
        """Visually mark which version (stable/weekly) will be launched."""
        if not hasattr(self, "stable_combo"):
            return
        t = get_theme(self.var_dark_mode)
        # Active: subtle accent fill + stronger border (readable, not flashy)
        active = (
            f"QComboBox {{ background-color: {t['neutral']}; color: {t['text']}; "
            f"border: 1px solid {t['accent']}; border-left: 3px solid {t['accent']}; "
            f"border-radius: 5px; padding: 4px 8px; min-height: 24px; font-weight: 600; }}"
            f"QComboBox:hover {{ border-color: {t['accent']}; }}"
            f"QComboBox::drop-down {{ border: none; border-left: 1px solid {t['border']}; "
            f"background-color: {t['neutral']}; width: 26px; "
            f"border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}"
        )
        inactive = (
            f"QComboBox {{ background-color: {t['input']}; color: {t['text']}; "
            f"border: 1px solid {t['border']}; border-radius: 5px; "
            f"padding: 4px 8px; min-height: 24px; }}"
            f"QComboBox:hover {{ border-color: {t['muted']}; }}"
            f"QComboBox::drop-down {{ border: none; border-left: 1px solid {t['border']}; "
            f"background-color: {t['neutral']}; width: 26px; "
            f"border-top-right-radius: 5px; border-bottom-right-radius: 5px; }}"
        )
        if self._active_version_kind == "weekly":
            self.stable_combo.setStyleSheet(inactive)
            self.weekly_combo.setStyleSheet(active)
        else:
            self.stable_combo.setStyleSheet(active)
            self.weekly_combo.setStyleSheet(inactive)

    def _selected_version(self):
        """Return the currently active version dict, or None."""
        if self._active_version_kind == "weekly":
            idx = self.weekly_combo.currentIndex()
            if 0 <= idx < len(self.weekly_versions):
                return self.weekly_versions[idx]
        idx = self.stable_combo.currentIndex()
        if 0 <= idx < len(self.stable_versions):
            return self.stable_versions[idx]
        idx = self.weekly_combo.currentIndex()
        if 0 <= idx < len(self.weekly_versions):
            return self.weekly_versions[idx]
        return None

    def toggle_autoclose(self, checked):
        self.var_autoclose = checked
        self.config_data["auto_close"] = checked
        self.save_config()

    def toggle_custom_script_env(self, checked):
        self.var_custom_script_env = checked
        self.config_data["use_custom_script_env"] = checked
        self.save_config()

    def toggle_vanilla_launch(self, checked):
        self.var_vanilla_launch = checked
        self.config_data["vanilla_launch"] = checked
        self.save_config()

    def toggle_use_pixi_build(self, checked):
        self.var_use_pixi_build = checked
        self.config_data["use_pixi_build"] = checked
        self.save_config()

    def toggle_disable_update_reminder(self, checked):
        self.var_disable_update_reminder = checked
        self.config_data["disable_update_reminder"] = checked
        self.save_config()

    def _apply_vanilla_env(self, env):
        if not self.var_vanilla_launch:
            return None
        vanilla_dir = tempfile.mkdtemp(prefix="freecad_vanilla_")
        env["FREECAD_USER_HOME"] = vanilla_dir
        return vanilla_dir

    def refresh_local_versions(self):
        self.stable_combo.blockSignals(True)
        self.weekly_combo.blockSignals(True)
        self.stable_combo.clear()
        self.weekly_combo.clear()
        self.stable_versions = []
        self.weekly_versions = []

        install_dir = self.get_install_dir()
        if os.path.exists(install_dir):
            appimages = [f for f in os.listdir(install_dir) if f.endswith(".AppImage")]
            appimages.sort(key=version_sort_key, reverse=True)
            for file in appimages:
                full_path = os.path.join(install_dir, file)
                if "weekly" in file.lower() or "dev" in file.lower():
                    display_name = self.format_version_name(file, is_weekly=True)
                    self.weekly_versions.append({"display": display_name, "name": file, "path": full_path})
                    self.weekly_combo.addItem(display_name)
                else:
                    display_name = self.format_version_name(file, is_weekly=False)
                    self.stable_versions.append({"display": display_name, "name": file, "path": full_path})
                    self.stable_combo.addItem(display_name)

        last_sel = self.config_data.get("last_selected_version", "")
        restored = False
        if last_sel:
            for i, v in enumerate(self.stable_versions):
                if v["display"] == last_sel or v["name"] == last_sel:
                    self.stable_combo.setCurrentIndex(i)
                    self._active_version_kind = "stable"
                    restored = True
                    break
            if not restored:
                for i, v in enumerate(self.weekly_versions):
                    if v["display"] == last_sel or v["name"] == last_sel:
                        self.weekly_combo.setCurrentIndex(i)
                        self._active_version_kind = "weekly"
                        restored = True
                        break
        if not restored:
            if self.stable_combo.count() > 0:
                self.stable_combo.setCurrentIndex(0)
                self._active_version_kind = "stable"
            elif self.weekly_combo.count() > 0:
                self.weekly_combo.setCurrentIndex(0)
                self._active_version_kind = "weekly"

        self.stable_combo.blockSignals(False)
        self.weekly_combo.blockSignals(False)
        self._update_version_highlight()
        self.check_versions_status()

    def check_versions_status(self):
        local_stable_keys = {extract_version_key(v["name"]) for v in self.stable_versions}
        local_weekly_keys = {extract_version_key(v["name"]) for v in self.weekly_versions}
        local_stable_keys.discard(None)
        local_weekly_keys.discard(None)

        t = get_theme(self.var_dark_mode)
        if self.stables_values:
            latest_key = extract_version_key(self.stables_values[0])
            if latest_key is not None and latest_key in local_stable_keys:
                self.lbl_stable_status.setText("● Up to date")
                self.lbl_stable_status.setStyleSheet(f"color: {t['success']}; font-size: 11px; font-weight: 600;")
            else:
                self.lbl_stable_status.setText("● Update available")
                self.lbl_stable_status.setStyleSheet(f"color: {t['danger']}; font-size: 11px; font-weight: 600;")
        else:
            self.lbl_stable_status.setText("Checking…")
            self.lbl_stable_status.setStyleSheet("")

        if self.weeklys_values:
            latest_key = extract_version_key(self.weeklys_values[0])
            if latest_key is not None and latest_key in local_weekly_keys:
                self.lbl_weekly_status.setText("● Up to date")
                self.lbl_weekly_status.setStyleSheet(f"color: {t['success']}; font-size: 11px; font-weight: 600;")
            else:
                self.lbl_weekly_status.setText("● Update available")
                self.lbl_weekly_status.setStyleSheet(f"color: {t['danger']}; font-size: 11px; font-weight: 600;")
        else:
            self.lbl_weekly_status.setText("Checking…")
            self.lbl_weekly_status.setStyleSheet("")

    def fetch_next_milestone(self):
        """Fetch open FreeCAD milestones and pick the next stable release target."""
        try:
            milestones = _github_get(
                "https://api.github.com/repos/FreeCAD/FreeCAD/milestones"
                "?state=open&sort=due_on&direction=asc&per_page=20",
                timeout=12,
            )
            if not isinstance(milestones, list):
                return

            candidates = []
            for m in milestones:
                title = (m.get("title") or "").strip()
                if not title or title.lower() in ("tbd", "to be decided", "backlog"):
                    continue
                open_i = int(m.get("open_issues") or 0)
                closed_i = int(m.get("closed_issues") or 0)
                total = open_i + closed_i
                if total <= 0:
                    continue
                candidates.append(m)

            if not candidates:
                self.sig_milestone.emit({})
                return

            # Prefer nearest due date; fall back to first with most progress
            def sort_key(m):
                due = m.get("due_on") or "9999-12-31"
                return due

            candidates.sort(key=sort_key)
            m = candidates[0]
            open_i = int(m.get("open_issues") or 0)
            closed_i = int(m.get("closed_issues") or 0)
            total = open_i + closed_i
            pct = int(round(closed_i * 100 / total)) if total else 0
            number = m.get("number")
            html_url = m.get("html_url") or (
                f"https://github.com/FreeCAD/FreeCAD/milestone/{number}" if number else
                "https://github.com/FreeCAD/FreeCAD/milestones"
            )
            self.sig_milestone.emit({
                "title": m.get("title", "?"),
                "description": (m.get("description") or "").strip().split("\n")[0][:120],
                "open": open_i,
                "closed": closed_i,
                "total": total,
                "percent": pct,
                "due_on": (m.get("due_on") or "")[:10],
                "url": html_url,
            })
        except Exception as e:
            print(f"[GitHub milestone] error: {e}", flush=True)
            self.sig_milestone.emit({})

    def _apply_milestone(self, data):
        # Cache so theme rebuild can restore without another network call
        self._milestone_data = data or {}
        if not hasattr(self, "lbl_milestone"):
            return
        if not data:
            self.lbl_milestone.setText("Next stable: unavailable")
            self.milestone_bar.setValue(0)
            self.lbl_milestone_detail.setText("")
            return

        title = data.get("title", "?")
        pct = int(data.get("percent") or 0)
        closed = data.get("closed", 0)
        total = data.get("total", 0)
        due = data.get("due_on") or ""
        self._milestone_url = data.get("url") or "https://github.com/FreeCAD/FreeCAD/milestones"

        self.lbl_milestone.setText(f"Next stable: {title}  ·  {pct}%")
        self.milestone_bar.setValue(max(0, min(100, pct)))

        parts = [f"{closed} / {total} issues closed"]
        if due:
            parts.append(f"due {due}")
        self.lbl_milestone_detail.setText(" · ".join(parts))

    def fetch_github_releases(self):
        try:
            releases = _github_get(
                "https://api.github.com/repos/FreeCAD/FreeCAD/releases?per_page=20",
                timeout=15,
            )
            stables, weeklys = [], []
            self.download_urls = {}
            self.download_sizes = {}
            for rel in releases:
                tag = rel["tag_name"]
                for asset in rel["assets"]:
                    name = asset["name"]
                    if name.endswith(".AppImage") and ("x86_64" in name or "conda" in name):
                        self.download_urls[name] = asset["browser_download_url"]
                        self.download_sizes[name] = asset.get("size")
                        if "weekly" in tag.lower() or "dev" in tag.lower():
                            weeklys.append(name)
                        else:
                            stables.append(name)
                        break
            stables.sort(key=version_sort_key, reverse=True)
            weeklys.sort(key=version_sort_key, reverse=True)
            self.sig_releases.emit(stables, weeklys)
        except Exception as e:
            print(f"[GitHub releases] error: {e}", flush=True)
            self.sig_releases_error.emit(f"Offline mode ({type(e).__name__})")

    def update_release_combos(self, stables, weeklys):
        self.stables_values = stables
        self.weeklys_values = weeklys
        if self.active_download_dialog:
            self.active_download_dialog.update_combos(stables, weeklys)
        self.lbl_status.setText("Connected to GitHub. Ready.")
        if self.active_download_dialog:
            self.active_download_dialog.update_status("Connected to GitHub. Ready.")
        self.check_versions_status()
        self._maybe_prompt_updates()

    def _on_download_status(self, text):
        """Update main status label and the download dialog (progress + auto-close)."""
        self.lbl_status.setText(text)
        dlg = self.active_download_dialog
        if dlg is not None:
            try:
                dlg.update_status(text)
            except Exception:
                pass


    def _available_updates(self):
        """Return list of remote AppImages not yet installed: {kind, filename, label}."""
        updates = []
        install_dir = self.get_install_dir()
        local_names = set()
        if os.path.isdir(install_dir):
            local_names = {f for f in os.listdir(install_dir) if f.endswith(".AppImage")}

        if self.stables_values:
            latest = self.stables_values[0]
            if latest not in local_names:
                updates.append({
                    "kind": "stable",
                    "filename": latest,
                    "label": self.format_version_name(latest, is_weekly=False),
                })
        if self.weeklys_values:
            latest = self.weeklys_values[0]
            if latest not in local_names:
                updates.append({
                    "kind": "weekly",
                    "filename": latest,
                    "label": self.format_version_name(latest, is_weekly=True),
                })
        return updates

    def _local_versions_of_kind(self, kind):
        """Return list of local version dicts for stable or weekly (newest first)."""
        if kind == "weekly":
            return list(self.weekly_versions)
        return list(self.stable_versions)

    def _maybe_prompt_updates(self):
        """Show welcome (no local installs) or update reminder at startup."""
        if self._update_prompt_shown:
            return
        updates = self._available_updates()
        if not updates:
            return
        has_local = bool(self.stable_versions or self.weekly_versions)
        is_welcome = not has_local
        # "Turn off update reminder" only suppresses update prompts, not first-run welcome
        if not is_welcome and self.var_disable_update_reminder:
            return
        self._update_prompt_shown = True
        self.sig_updates_available.emit(updates, is_welcome)

    def _show_update_available_dialog(self, updates, is_welcome=False):
        if not updates:
            return
        dlg = UpdateAvailableDialog(
            self, updates, is_dark=self.var_dark_mode, welcome=is_welcome
        )
        dlg.exec()
        choice = getattr(dlg, "choice", None)
        if not choice:
            return
        selected = updates
        if choice == "stable":
            selected = [u for u in updates if u.get("kind") == "stable"]
        elif choice == "weekly":
            selected = [u for u in updates if u.get("kind") == "weekly"]
        # choice == "both" -> all updates
        for u in selected:
            fn = u.get("filename")
            if not fn:
                continue
            kind = u.get("kind") or (
                "weekly" if ("weekly" in fn.lower() or "dev" in fn.lower()) else "stable"
            )
            if is_welcome:
                # First install: no previous-version prompt; ask for desktop entry after each DL
                self.download_version(fn, from_download_dialog=True)
            else:
                # Snapshot previous local version(s) of this channel before download
                previous = self._local_versions_of_kind(kind)
                old = previous[0] if previous else None
                self._pending_update_meta[fn] = {
                    "kind": kind,
                    "new_label": u.get("label") or self.format_version_name(
                        fn, is_weekly=(kind == "weekly")
                    ),
                    "old_name": old["name"] if old else None,
                    "old_path": old["path"] if old else None,
                    "old_display": old["display"] if old else None,
                }
                self.download_version(fn)

    def _on_update_download_finished(self, filename):
        """After an update download: optionally delete old AppImage and migrate .desktop."""
        meta = self._pending_update_meta.pop(filename, None)
        if not meta:
            return
        new_path = os.path.join(self.get_install_dir(), filename)
        new_display = meta.get("new_label") or self.format_version_name(
            filename, is_weekly=(meta.get("kind") == "weekly")
        )
        old_path = meta.get("old_path")
        old_display = meta.get("old_display")
        old_name = meta.get("old_name")

        # Only migrate the .desktop when the user chooses to replace the previous version.
        # If they keep the old AppImage, the existing start-menu entry must keep launching it.
        if old_path and os.path.isfile(old_path) and os.path.abspath(old_path) != os.path.abspath(new_path):
            msg = (
                f"Update complete: FreeCAD {new_display}\n\n"
                f"Delete the previous version?\n{old_name or old_path}\n\n"
                "Yes: remove the old AppImage and update any start-menu entry to the new version.\n"
                "No: keep the old AppImage and leave its start-menu entry unchanged."
            )
            reply = QMessageBox.question(self, "Remove previous version", msg)
            if reply == QMessageBox.Yes:
                try:
                    self._migrate_desktop_entry_after_update(
                        old_path=old_path,
                        old_display=old_display,
                        new_path=new_path,
                        new_display=new_display,
                    )
                except Exception as e:
                    print(f"[desktop migrate] {e}", flush=True)
                try:
                    os.remove(old_path)
                    self.refresh_local_versions()
                    self.lbl_status.setText(
                        f"Updated to {new_display}; previous version removed."
                    )
                except Exception as e:
                    QMessageBox.critical(
                        self, "Error", f"Could not delete previous version:\n{e}"
                    )
            else:
                self.lbl_status.setText(
                    f"Updated to {new_display} (previous version and desktop entry kept)."
                )
        else:
            self.lbl_status.setText(f"Updated to {new_display}.")


    def _on_manual_download_finished(self, filename):
        """After a Download-dialog download: offer to create a start-menu entry."""
        if filename not in getattr(self, "_download_from_dialog", set()):
            return
        self._download_from_dialog.discard(filename)
        is_weekly = "weekly" in filename.lower() or "dev" in filename.lower()
        display = self.format_version_name(filename, is_weekly=is_weekly)
        name = f"FreeCAD {display}"
        app_path = os.path.join(self.get_install_dir(), filename)
        if not os.path.isfile(app_path):
            return
        reply = QMessageBox.question(
            self,
            "Download complete",
            f"Download finished:\n{name}\n\n"
            "Create a start-menu desktop entry for this version?",
        )
        if reply != QMessageBox.Yes:
            return
        try:
            desktop_path = self._desktop_file_path(display)
            self._write_desktop_file(desktop_path, display, app_path)
            QMessageBox.information(
                self,
                "Start menu",
                f"Desktop entry created:\n{name}\n\n{desktop_path}",
            )
            self.lbl_status.setText(f"Desktop entry created for {name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create .desktop file:\n{e}")

    def _write_desktop_file(self, desktop_path, display, app_path, icon_value=None):
        """Write (or overwrite) a .desktop file for the given AppImage."""
        name = f"FreeCAD {display}"
        apps_dir = os.path.dirname(desktop_path)
        os.makedirs(apps_dir, exist_ok=True)
        if icon_value is None:
            icon_value = self._ensure_freecad_menu_icon()
        exec_path = os.path.abspath(app_path).replace("\\", "\\\\").replace(" ", "\\ ")
        lines = [
            "[Desktop Entry]",
            "Version=1.0",
            "Type=Application",
            f"Name={name}",
            "GenericName=CAD Application",
            "Comment=Feature based Parametric Modeler",
            f"Exec={exec_path} %F",
            f"Icon={icon_value}",
            "Terminal=false",
            "Categories=Graphics;Science;Education;Engineering;X-CNC;",
            "StartupNotify=true",
            "StartupWMClass=FreeCAD",
            "MimeType=application/x-extension-fcstd;model/step;model/stl;application/iges;model/iges;",
            "",
        ]
        with open(desktop_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        os.chmod(desktop_path, 0o755)
        for cmd in (
            ["update-desktop-database", apps_dir],
            ["xdg-desktop-menu", "forceupdate"],
        ):
            try:
                if shutil.which(cmd[0]):
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except Exception:
                pass
        return desktop_path


    def _migrate_desktop_entry_after_update(self, old_path, old_display, new_path, new_display):
        """
        Keep existing start-menu entries, but retarget them to the new AppImage
        and rename the .desktop file / Name to the new version.
        """
        apps_dir = os.path.join(USER_HOME, ".local", "share", "applications")
        if not os.path.isdir(apps_dir):
            return

        new_desktop = self._desktop_file_path(new_display)
        icon_value = self._ensure_freecad_menu_icon()
        candidates = []

        # Prefer the exact old slug path
        if old_display:
            old_desktop = self._desktop_file_path(old_display)
            if os.path.isfile(old_desktop):
                candidates.append(old_desktop)

        # Also scan freecad-*.desktop files that Exec the old AppImage
        old_abs = os.path.abspath(old_path) if old_path else None
        try:
            for fname in os.listdir(apps_dir):
                if not fname.startswith("freecad-") or not fname.endswith(".desktop"):
                    continue
                full = os.path.join(apps_dir, fname)
                if full in candidates:
                    continue
                try:
                    with open(full, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception:
                    continue
                if old_abs and old_abs in content.replace(r"\ ", " "):
                    candidates.append(full)
                elif old_path and os.path.basename(old_path) in content:
                    candidates.append(full)
        except Exception:
            pass

        if not candidates:
            return

        # Use the first matching entry as the one to migrate; remove duplicates
        primary = candidates[0]
        for extra in candidates[1:]:
            try:
                if os.path.abspath(extra) != os.path.abspath(new_desktop):
                    os.remove(extra)
            except OSError:
                pass

        # Write new content to the new versioned filename; remove old file if different
        self._write_desktop_file(new_desktop, new_display, new_path, icon_value=icon_value)
        if os.path.abspath(primary) != os.path.abspath(new_desktop) and os.path.isfile(primary):
            try:
                os.remove(primary)
            except OSError:
                pass

    def cancel_download(self):
        """Request cancellation of the in-progress AppImage download."""
        self._download_cancel = True

    def download_version(self, filename, from_download_dialog=False):
        if not filename:
            self.sig_download_status.emit("Download error.")
            return
        url = self.download_urls.get(filename)
        if not url:
            self.sig_download_status.emit("Download error.")
            return
        install_dir = self.get_install_dir()
        target_path = os.path.join(install_dir, filename)
        if os.path.exists(target_path):
            QMessageBox.information(self, "Info", "This version is already installed!")
            self.sig_download_status.emit("Already installed.")
            return
        tmp_path = target_path + ".part"
        expected_size = self.download_sizes.get(filename)
        last_pct = [-1]
        self._download_cancel = False
        if from_download_dialog:
            self._download_from_dialog.add(filename)

        def downloader():
            self.sig_download_status.emit(f"Downloading {filename}... 0%")
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "FreeCAD-Smart-Launcher/2.1"},
                )
                with urllib.request.urlopen(req, timeout=60, context=_SSL_CTX) as resp:
                    total = resp.headers.get("Content-Length")
                    try:
                        total = int(total) if total else (expected_size or 0)
                    except (TypeError, ValueError):
                        total = expected_size or 0
                    downloaded = 0
                    chunk_size = 256 * 1024
                    with open(tmp_path, "wb") as out:
                        while True:
                            if self._download_cancel:
                                raise InterruptedError("cancelled")
                            chunk = resp.read(chunk_size)
                            if not chunk:
                                break
                            out.write(chunk)
                            downloaded += len(chunk)
                            if total:
                                pct = min(100, int(downloaded * 100 / total))
                                if pct != last_pct[0]:
                                    last_pct[0] = pct
                                    self.sig_download_status.emit(
                                        f"Downloading {filename}... {pct}%"
                                    )

                if self._download_cancel:
                    raise InterruptedError("cancelled")

                actual_size = os.path.getsize(tmp_path)
                if expected_size and actual_size != expected_size:
                    raise IOError(
                        f"Incomplete download: got {actual_size} bytes, "
                        f"expected {expected_size} bytes."
                    )
                os.chmod(tmp_path, 0o755)
                os.replace(tmp_path, target_path)
                is_weekly = "weekly" in filename.lower() or "dev" in filename.lower()
                display = self.format_version_name(filename, is_weekly=is_weekly)
                self.config_data["last_selected_version"] = display
                self.save_config()
                self.sig_refresh_versions.emit()
                self.sig_download_status.emit("Download complete.")
                self.sig_download_finished.emit(filename)
            except InterruptedError:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                self._download_from_dialog.discard(filename)
                self.sig_download_status.emit("Download cancelled.")
            except Exception as e:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                self._download_from_dialog.discard(filename)
                self.sig_download_status.emit("Download error.")
                err = str(e)
                QTimer.singleShot(
                    0,
                    lambda: QMessageBox.critical(
                        self, "Error", f"Download failed: {err}"
                    ),
                )
            finally:
                self._download_cancel = False

        threading.Thread(target=downloader, daemon=True).start()

    # ----- Project library -----

    def _is_freecad_source_dir(self, path):
        """True if path looks like a FreeCAD source tree usable for PR builds."""
        if not path:
            return False
        path = os.path.abspath(os.path.expanduser(str(path).strip()))
        if not os.path.isdir(path):
            return False
        if os.path.isfile(os.path.join(path, "CMakeLists.txt")):
            return True
        nested = os.path.join(path, "FreeCAD")
        return os.path.isfile(os.path.join(nested, "CMakeLists.txt"))

    def _resolve_freecad_source_dir(self, path):
        path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if os.path.isfile(os.path.join(path, "CMakeLists.txt")):
            return path
        nested = os.path.join(path, "FreeCAD")
        if os.path.isfile(os.path.join(nested, "CMakeLists.txt")):
            return nested
        return path

    def _update_pr_setup_panel(self):
        """Show onboarding or full PR controls depending on configured source."""
        if not hasattr(self, "pr_setup_stack"):
            return
        src = ""
        if hasattr(self, "src_folder_edit"):
            src = self.src_folder_edit.text().strip()
        if not src:
            src = (self.config_data.get("src_folder") or "").strip()
        self.pr_setup_stack.setCurrentIndex(1 if self._is_freecad_source_dir(src) else 0)

    def _on_src_folder_edited(self):
        text = self.src_folder_edit.text().strip()
        if text:
            resolved = self._resolve_freecad_source_dir(text)
            if resolved != text and self._is_freecad_source_dir(resolved):
                self.src_folder_edit.setText(resolved)
                text = resolved
            self.config_data["src_folder"] = text
            self.save_config()
        self._update_pr_setup_panel()

    def _pick_existing_pr_source(self):
        """Pick an existing FreeCAD source tree and unlock the PR UI."""
        start = (
            self.config_data.get("src_folder")
            or self.config_data.get("pixi_build_folder")
            or USER_HOME
        )
        folder = pick_existing_directory(self, start, "Select FreeCAD source folder")
        if not folder:
            return
        resolved = self._resolve_freecad_source_dir(folder)
        if not self._is_freecad_source_dir(resolved):
            QMessageBox.warning(
                self,
                "Invalid folder",
                "This does not look like a FreeCAD source tree.\n"
                "Choose the folder that contains CMakeLists.txt\n"
                "(or its parent if sources are in FreeCAD/).",
            )
            return
        self.config_data["src_folder"] = resolved
        self.save_config()
        if hasattr(self, "src_folder_edit"):
            self.src_folder_edit.setText(resolved)
        self._update_pr_setup_panel()
        self.lbl_status.setText(f"PR source set: {resolved}")

    def change_src_folder(self):
        folder = pick_existing_directory(
            self,
            self.config_data.get("src_folder", USER_HOME),
            "Select FreeCAD Source Folder",
        )
        if folder:
            resolved = self._resolve_freecad_source_dir(folder)
            self.config_data["src_folder"] = resolved
            self.src_folder_edit.setText(resolved)
            self.save_config()
            self._update_pr_setup_panel()


    def change_scan_folder(self):
        folder = pick_existing_directory(
            self,
            self.config_data.get("scan_folder", USER_HOME),
            "Select Project Scan Directory",
        )
        if folder:
            self.config_data["scan_folder"] = folder
            self.save_config()
            self.refresh_recent_files()

    def refresh_recent_files(self):
        self.recent_list.clear()
        self.recent_files_map.clear()
        scan_dir = self.config_data.get("scan_folder", USER_HOME)
        if not os.path.isdir(scan_dir):
            return
        files = []
        for root, dirs, filenames in os.walk(scan_dir):
            for fname in filenames:
                if os.path.splitext(fname)[1].lower() in SUPPORTED_3D_EXTENSIONS:
                    files.append(os.path.join(root, fname))
        files.sort(key=os.path.getmtime, reverse=True)
        for f in files[:20]:
            name = os.path.basename(f)
            self.recent_files_map[name] = f
            self.recent_list.addItem(name)
        if self.recent_list.count() > 0:
            self.recent_list.setCurrentRow(0)
            self.on_project_select()

    def _preview_size(self):
        """Current thumbnail widget size for rendering previews."""
        w = max(80, self.thumb_label.width() or 285)
        h = max(60, self.thumb_label.height() or 165)
        return w, h

    def eventFilter(self, obj, event):
        if obj is getattr(self, "thumb_label", None) and event.type() == QEvent.Resize:
            if self._preview_mode in ("pixmap", "wireframe"):
                self._preview_resize_timer.start()
        return super().eventFilter(obj, event)

    def _scale_preview_to_label(self):
        """Rescale current preview to the label size (called on resize)."""
        if not hasattr(self, "thumb_label"):
            return
        pw, ph = self._preview_size()
        if self._preview_mode == "pixmap" and self._preview_base_pixmap is not None:
            scaled = self._preview_base_pixmap.scaled(
                pw, ph, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.thumb_label.setPixmap(scaled)
        elif self._preview_mode == "wireframe" and self._preview_triangles is not None:
            line_col = "#0277BD" if not self.var_dark_mode else "#4FC3F7"
            pix = draw_stl_wireframe_pixmap(self._preview_triangles, pw, ph, line_col)
            self.thumb_label.setPixmap(pix)

    def _set_preview_pixmap(self, base_pixmap):
        self._preview_base_pixmap = base_pixmap
        self._preview_triangles = None
        self._preview_mode = "pixmap"
        self._scale_preview_to_label()

    def _set_preview_wireframe(self, triangles):
        self._preview_triangles = triangles
        self._preview_base_pixmap = None
        self._preview_mode = "wireframe"
        self._scale_preview_to_label()

    def _clear_preview(self, text="No project selected"):
        self._preview_base_pixmap = None
        self._preview_triangles = None
        self._preview_mode = "none"
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(text)
        if hasattr(self, "btn_view_3d"):
            self.btn_view_3d.setEnabled(False)

    def _update_view_3d_button(self, ext):
        if not hasattr(self, "btn_view_3d"):
            return
        can_view = ext in (
            {".stl", ".obj", ".ply", ".gltf", ".glb", ".fcstd"} | set(STEP_LIKE_EXTENSIONS)
        )
        self.btn_view_3d.setEnabled(bool(can_view))

    def on_project_select(self):
        items = self.recent_list.selectedItems()
        if not items:
            self._clear_preview()
            return
        filename = items[0].text()
        filepath = self.recent_files_map[filename]
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(filepath)))
        ext = os.path.splitext(filepath)[1].lower()
        self._update_view_3d_button(ext)

        if ext == ".fcstd":
            fc_version = "Unknown"
            try:
                with zipfile.ZipFile(filepath, "r") as z:
                    if "Document.xml" in z.namelist():
                        with z.open("Document.xml") as f:
                            for _, elem in ET.iterparse(f, events=("start",)):
                                if elem.tag == "Document" or elem.tag.endswith("Document"):
                                    fc_version = elem.attrib.get("ProgramVersion", "Unknown")
                                    break
            except Exception:
                pass
            self.lbl_file_info.setText(f"{filename}\nModified: {mtime}\nVersion: {fc_version}")
            try:
                with zipfile.ZipFile(filepath, "r") as z:
                    thumb_entry = next((n for n in z.namelist() if n.lower().endswith("thumbnail.png")), None)
                    if thumb_entry:
                        img_data = z.read(thumb_entry)
                        img = QImage.fromData(img_data)
                        self._set_preview_pixmap(QPixmap.fromImage(img))
                    else:
                        self._clear_preview("No preview available")
            except Exception:
                self._clear_preview("No preview available")

        elif ext == ".stl":
            self.lbl_file_info.setText(f"{filename}\nModified: {mtime}\nFormat: STL mesh")
            try:
                triangles = parse_stl_triangles(filepath)
                self._set_preview_wireframe(triangles)
            except Exception:
                self._clear_preview("Unreadable STL file")

        elif ext in STEP_LIKE_EXTENSIONS:
            format_label = ext.lstrip(".").upper()
            self.lbl_file_info.setText(f"{filename}\nModified: {mtime}\nFormat: {format_label}")
            self.request_step_preview(filepath)
        else:
            format_label = ext.lstrip(".").upper()
            self.lbl_file_info.setText(f"{filename}\nModified: {mtime}\nFormat: {format_label}")
            self._clear_preview(f"No preview for {format_label} files\n(click Launch to open in FreeCAD)")

    def get_selected_version_path(self):
        ver = self._selected_version()
        if ver:
            return ver["path"]
        if self.stable_versions:
            return self.stable_versions[0]["path"]
        if self.weekly_versions:
            return self.weekly_versions[0]["path"]
        return None


    def open_interactive_mesh_preview(self, *_args):
        """Open the selected project in F3D, or VTK as fallback."""
        items = self.recent_list.selectedItems()
        if not items:
            return
        filename = items[0].text()
        filepath = self.recent_files_map.get(filename)
        if not filepath or not os.path.isfile(filepath):
            return
        ext = os.path.splitext(filepath)[1].lower()
        supported = {".stl", ".obj", ".ply", ".gltf", ".glb", ".3ds", ".fbx"} | set(
            STEP_LIKE_EXTENSIONS
        ) | {".fcstd"}
        if ext not in supported and ext not in {".stl"} | set(STEP_LIKE_EXTENSIONS):
            # still try F3D for unknown 3D-ish files
            pass

        # FCStd is not read by F3D; export STEP/IGES (or STL) first
        view_path = filepath
        if ext == ".fcstd":
            app_path = self.get_selected_version_path()
            if not app_path:
                QMessageBox.information(
                    self,
                    "3D viewer",
                    "Viewing .FCStd in F3D requires a FreeCAD AppImage selected "
                    "in the launcher (used to export STEP/IGES).",
                )
                return
            self.lbl_status.setText("Exporting FreeCAD file to STEP/IGES for F3D…")
            QApplication.processEvents()
            cad_tmp = export_fcstd_to_temp_cad(app_path, filepath)
            if not cad_tmp:
                QMessageBox.warning(
                    self,
                    "3D viewer",
                    "Could not export this FreeCAD file to STEP/IGES.\n"
                    "Try Launch Project to open it in FreeCAD.",
                )
                return
            view_path = cad_tmp
            self.lbl_status.setText(f"Exported: {os.path.basename(cad_tmp)}")

        # Prefer F3D when installed
        if not os.path.isfile(view_path):
            QMessageBox.warning(
                self,
                "3D viewer",
                "Export finished but the temporary mesh file is missing.\n"
                + view_path
                + "\n\nCheck that FreeCAD can run headless from the launcher.",
            )
            return
        if self._open_with_f3d(view_path):
            return

        # Fallback: VTK mesh viewer
        triangles = None
        if ext == ".stl":
            try:
                triangles = parse_stl_triangles(filepath)
            except Exception:
                triangles = None
        elif ext == ".fcstd":
            if view_path.lower().endswith(".stl"):
                try:
                    triangles = parse_stl_triangles(view_path)
                except Exception:
                    triangles = None
            elif any(view_path.lower().endswith(x) for x in (".step", ".stp", ".iges", ".igs")):
                triangles = tessellate_step_with_ocp(view_path)
                if not triangles:
                    vp = self.get_selected_version_path()
                    if vp:
                        triangles = tessellate_step_file(vp, view_path)
        elif ext in STEP_LIKE_EXTENSIONS:
            triangles = self.step_preview_cache.get((filepath, os.path.getmtime(filepath)))
            if not triangles:
                triangles = tessellate_step_with_ocp(filepath)
            if not triangles:
                vp = self.get_selected_version_path()
                if vp:
                    triangles = tessellate_step_file(vp, filepath)

        if triangles and open_vtk_mesh_viewer(triangles, title=f"Preview — {filename}"):
            return

        QMessageBox.information(
            self,
            "3D viewer",
            "Could not open an interactive 3D viewer.\n\n"
            "Recommended: install F3D, then double-click the file again.\n\n"
            "  • Arch/CachyOS:  sudo pacman -S f3d\n"
            "  • Flatpak:      flatpak install flathub io.github.f3d_app.f3d\n"
            "  • Website:      https://f3d.app/\n\n"
            "Fallback: pip install vtk\n\n"
            "The small static preview in the launcher still works without F3D.",
        )

    def _open_with_f3d(self, filepath):
        """Launch F3D for filepath (native binary or Flatpak)."""
        # Absolute path; list argv handles spaces without shell=True
        path = os.path.abspath(os.path.expanduser(filepath))
        try:
            path = os.path.realpath(path)
        except OSError:
            pass
        if not os.path.isfile(path):
            print(f"[F3D] file not found: {path!r}", flush=True)
            QMessageBox.warning(
                self,
                "F3D",
                f"File not found:\n{path}\n\nThe path in the project list may be outdated — try Refresh.",
            )
            return False

        candidates = []
        which = shutil.which("f3d")
        if which:
            candidates.append([which, path])
        if shutil.which("flatpak"):
            candidates.append(
                [
                    "flatpak",
                    "run",
                    "--filesystem=host",
                    "io.github.f3d_app.f3d",
                    path,
                ]
            )
            candidates.append(
                [
                    "flatpak",
                    "run",
                    "--file-forwarding",
                    "io.github.f3d_app.f3d",
                    "@@",
                    path,
                    "@@",
                ]
            )

        for cmd in candidates:
            try:
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self.lbl_status.setText(f"Opened in F3D: {os.path.basename(path)}")
                return True
            except Exception as e:
                print(f"[F3D] {cmd[:3]}: {e}", flush=True)
        return False

    def request_step_preview(self, filepath):
        version_path = self.get_selected_version_path()
        cache_key = (filepath, os.path.getmtime(filepath))
        cached = self.step_preview_cache.get(cache_key)
        if cached is not None:
            self._set_preview_wireframe(cached)
            return
        token = object()
        self._preview_token = token
        self._clear_preview("Generating preview...")

        def worker():
            # Prefer OCP/pythonocc if available (faster, no FreeCAD process)
            triangles = tessellate_step_with_ocp(filepath)
            if not triangles:
                triangles = (
                    tessellate_step_file(version_path, filepath)
                    if version_path else None
                )
            if triangles:
                self.step_preview_cache[cache_key] = triangles
            if self._preview_token is token:
                self.sig_step_preview.emit(token, triangles)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_step_preview(self, token, triangles):
        if self._preview_token is not token:
            return
        if not triangles:
            self._clear_preview("Preview unavailable\n(open in FreeCAD to view)")
        else:
            self._set_preview_wireframe(triangles)

    # ----- Launch helpers -----
    def launch_appimage(self, app_path, project_path=None, single_instance=False):
        cmd = [app_path]
        if single_instance:
            cmd.append("--single-instance")
        env = os.environ.copy()
        if self.var_custom_script_env:
            env["QT_SCALE_FACTOR"] = "1.66"
            env["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
            env["XCURSOR_SIZE"] = "80"
        vanilla_dir = self._apply_vanilla_env(env)
        if project_path:
            cmd.append(project_path)
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env)

        def watch_for_fuse_failure():
            fuse_signature_seen = False
            start = time.time()
            try:
                for raw_line in iter(process.stderr.readline, b""):
                    if time.time() - start <= 2:
                        low = raw_line.lower()
                        if b"fuse" in low or b"dlopen" in low:
                            fuse_signature_seen = True
            except Exception:
                pass
            process.wait()
            try:
                if process.returncode == 0:
                    return
                if fuse_signature_seen:
                    fallback_cmd = [app_path]
                    if single_instance:
                        fallback_cmd.append("--single-instance")
                    fallback_cmd.append("--appimage-extract-and-run")
                    if project_path:
                        fallback_cmd.append(project_path)
                    fallback_process = subprocess.Popen(fallback_cmd, env=env)
                    fallback_process.wait()
                elif time.time() - start <= 2:
                    QTimer.singleShot(0, lambda: QMessageBox.critical(
                        self, "Error", f"FreeCAD failed to start (exit code {process.returncode})."
                    ))
            finally:
                if vanilla_dir:
                    shutil.rmtree(vanilla_dir, ignore_errors=True)

        threading.Thread(target=watch_for_fuse_failure, daemon=True).start()
        return process

    def _record_session(self, stat_key, start_time):
        """Add a finished FreeCAD session (longer than 5 s) to the usage statistics."""
        duration = int(time.time() - start_time)
        if duration <= 5:
            return
        entry = self.stats_data.setdefault(stat_key, {"time_sec": 0, "launches": 0})
        entry["time_sec"] += duration
        entry["launches"] += 1
        self.save_stats()
        self.sig_footer.emit()

    def track_time(self, app_path, version_name, project_path=None, single_instance=False):
        start_time = time.time()
        stat_key = self.get_stat_key(version_name)
        process = self.launch_appimage(app_path, project_path, single_instance=single_instance)
        if self.var_autoclose:
            # The window closes, but this process stays alive until FreeCAD exits
            # so the session time can still be recorded.
            self.close()
            process.wait()
            self._record_session(stat_key, start_time)
        else:
            def wait_and_log():
                process.wait()
                self._record_session(stat_key, start_time)
            threading.Thread(target=wait_and_log, daemon=True).start()

    def launch_local(self):
        ver = self._selected_version()
        if ver:
            self.track_time(ver["path"], ver["name"])
        else:
            QMessageBox.warning(self, "Warning", "Please select a FreeCAD version to launch.")

    def launch_project(self):
        ver = self._selected_version()
        items_p = self.recent_list.selectedItems()
        if not ver:
            QMessageBox.warning(self, "Warning", "Please select a FreeCAD version on the left.")
            return
        if not items_p:
            QMessageBox.warning(self, "Warning", "Please select a project on the right.")
            return
        proj_name = items_p[0].text()
        proj_path = self.recent_files_map[proj_name]
        self.track_time(ver["path"], ver["name"], proj_path)

    def launch_project_in_current_instance(self):
        ver = self._selected_version()
        items_p = self.recent_list.selectedItems()
        if not ver:
            QMessageBox.warning(self, "Warning", "Please select a FreeCAD version on the left.")
            return
        if not items_p:
            QMessageBox.warning(self, "Warning", "Please select a project on the right.")
            return
        proj_name = items_p[0].text()
        proj_path = self.recent_files_map[proj_name]
        self.track_time(ver["path"], ver["name"], proj_path, single_instance=True)

    def launch_project_with_pr(self):
        items_p = self.recent_list.selectedItems()
        if not items_p:
            QMessageBox.warning(self, "Warning", "Please select a project on the right.")
            return
        src_dir = self.src_folder_edit.text().strip()
        if not src_dir or not os.path.exists(src_dir):
            QMessageBox.critical(
                self, "Error",
                "No valid FreeCAD source folder is set.\nSet it in the \"TEST A GITHUB PULL REQUEST\" section first."
            )
            return
        _, exe_path = self.get_pr_exe_path(src_dir)
        if not os.path.exists(exe_path):
            alt_path = os.path.join(src_dir, "build", "bin", "FreeCAD")
            if os.path.exists(alt_path):
                exe_path = alt_path
        if not os.path.exists(exe_path):
            QMessageBox.critical(self, "Error", "No compiled PR executable found.\nBuild a PR at least once first!")
            return
        proj_name = items_p[0].text()
        proj_path = self.recent_files_map[proj_name]
        pr_num = self.get_pr_number()
        version_name = f"PR #{pr_num}" if pr_num else "PR build"
        self.track_time(exe_path, version_name, proj_path)

    def _desktop_slug(self, display_name):
        """Filename-safe slug for a version display name."""
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", display_name.strip())
        slug = re.sub(r"-{2,}", "-", slug).strip("-").lower()
        return slug or "version"

    def _desktop_file_path(self, display_name):
        apps_dir = os.path.join(USER_HOME, ".local", "share", "applications")
        return os.path.join(apps_dir, f"freecad-{self._desktop_slug(display_name)}.desktop")

    def _ensure_freecad_menu_icon(self):
        """Return an Icon= value for .desktop files (theme name or local SVG path)."""
        # Prefer icon theme names when available
        for name in ("org.freecad.FreeCAD", "freecad", "FreeCAD"):
            for base in (
                "/usr/share/icons",
                "/usr/share/pixmaps",
                os.path.join(USER_HOME, ".local", "share", "icons"),
            ):
                if not os.path.isdir(base):
                    continue
                for root, _dirs, files in os.walk(base):
                    for f in files:
                        stem = os.path.splitext(f)[0]
                        if stem == name or stem.lower() == name.lower():
                            return name

        # Install FreeCAD SVG under the user icon theme
        icon_dir = os.path.join(
            USER_HOME, ".local", "share", "icons", "hicolor", "scalable", "apps"
        )
        icon_path = os.path.join(icon_dir, "org.freecad.FreeCAD.svg")
        if os.path.isfile(icon_path):
            return icon_path

        urls = (
            "https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/Gui/Icons/freecad.svg",
            "https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/XDGData/org.freecad.FreeCAD.svg",
        )
        try:
            os.makedirs(icon_dir, exist_ok=True)
            for url in urls:
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "FreeCAD-Smart-Launcher/2.1"}
                    )
                    with urllib.request.urlopen(req, timeout=12, context=_SSL_CTX) as resp:
                        data = resp.read()
                    if data and len(data) > 100:
                        with open(icon_path, "wb") as f:
                            f.write(data)
                        return icon_path
                except Exception:
                    continue
        except Exception:
            pass

        # Fallback theme name
        return "org.freecad.FreeCAD"

    def create_desktop_entry(self):
        """Create a .desktop entry for the selected AppImage."""
        ver = self._selected_version()
        if not ver:
            QMessageBox.warning(self, "Warning", "Please select a FreeCAD version first.")
            return

        app_path = os.path.abspath(ver["path"])
        if not os.path.isfile(app_path):
            QMessageBox.critical(self, "Error", f"AppImage not found:\n{app_path}")
            return

        display = ver.get("display") or self.format_version_name(
            ver["name"],
            is_weekly=("weekly" in ver["name"].lower() or "dev" in ver["name"].lower()),
        )
        name = f"FreeCAD {display}"
        desktop_path = self._desktop_file_path(display)

        if os.path.exists(desktop_path):
            reply = QMessageBox.question(
                self,
                "Menu entry exists",
                f"A start-menu entry already exists for {name}.\nOverwrite it?",
            )
            if reply != QMessageBox.Yes:
                return

        try:
            self._write_desktop_file(desktop_path, display, app_path)
            QMessageBox.information(
                self,
                "Start menu",
                f"Menu entry created:\n{name}\n\n{desktop_path}\n\n"
                "It should appear in your application menu shortly.",
            )
            self.lbl_status.setText(f"Desktop entry created for {name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create .desktop file:\n{e}")

    def delete_local(self):
        ver = self._selected_version()
        if not ver:
            return
        reply = QMessageBox.question(self, "Confirmation", f"Are you sure you want to delete {ver['name']}?")
        if reply == QMessageBox.Yes:
            try:
                # Remove matching start-menu entry if present
                display = ver.get("display") or ""
                if display:
                    desk = self._desktop_file_path(display)
                    if os.path.isfile(desk):
                        try:
                            os.remove(desk)
                        except OSError:
                            pass
                os.remove(ver["path"])
                self.refresh_local_versions()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def show_stats(self):
        def do_reset():
            self.stats_data = {}
            self.save_stats()
            self.update_footer_text()

        StatsDialog(
            self,
            self.stats_data,
            is_dark=self.var_dark_mode,
            on_reset=do_reset,
        ).exec()
        self.update_footer_text()


if __name__ == "__main__":
    if not acquire_single_instance_lock():
        app = QApplication(sys.argv)
        QMessageBox.warning(None, "FreeCAD Launcher", "The launcher is already open in another window.")
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = FreeCADLauncher()
    window.show()
    sys.exit(app.exec())
