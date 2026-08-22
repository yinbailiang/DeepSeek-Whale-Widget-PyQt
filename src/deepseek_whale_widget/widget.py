"""主挂件：透明置顶小鲸鱼 + 气泡 + 拖拽吸附 + 菜单。"""
from __future__ import annotations

import json
import math
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QMovie,
    QPainter,
    QPen,
    QPixmap,
    QRegion,
)
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import api, storage
from .pricing import fmt_amount, is_peak_time

try:  # QtMultimedia 可能因系统缺后端而不可用，静默降级
    from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover
    QAudioOutput = None
    QMediaPlayer = None

# ---------- 常量（与原版一致） ----------
MIN_SCALE = 0.6
MAX_SCALE = 2.5
REFRESH_MS = 60000
CHANGE_MS = 900        # 余额滚动动画时长
BUBBLE_MS = 5000
CLICK_SQ = 9           # 拖拽判定阈值（像素平方）

BUBBLE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1026 700" preserveAspectRatio="xMidYMid meet">
<path fill="#FFFFFF" stroke="#203170" stroke-width="18" stroke-linejoin="round" stroke-linecap="round" d="M 827 248 A 373 232 0 1 0 81 246 A 373 232 0 0 0 301 465 A 57 32 10 0 0 413 484 A 373 232 0 0 0 827 248 Z"/>
<ellipse cx="352" cy="561" rx="37.5" ry="26" fill="#FFFFFF" stroke="#203170" stroke-width="18"/>
<ellipse cx="442" cy="646" rx="24.5" ry="18" fill="#FFFFFF" stroke="#203170" stroke-width="18"/>
</svg>"""

TEXT_COLOR = "#536ba9"
HINT_COLOR = "#9fb0d9"
PEAK_COLOR = "#e0433f"
OFFPEAK_COLOR = "#2fa24c"

RANDOM_TAUNTS = [
    "不知道用户有什么用，先赶走吧~",
    "我...我...我也要挣钱吗？",
    "我去吃饭啦，测完叫我",
    "压力一只蓝色大肥鱼？！",
    "DeepSleep...",
    "坏了...用户彻底怒了！",
]
RANDOM_GIF_FALLBACK = ["gif 加载失败了...", "今天没有动图给你看~", "呜呜 动图不见了..."]
RANDOM_TOKEN_LINES = ["你目录里的dsh是什么...大烧货吗...?", "恭喜你实现token自由！token全跑了！", "真当我是便宜货啊..."]


def _assets_dir() -> Path:
    pkg = Path(__file__).resolve().parent
    for cand in (pkg.parent.parent / "assets", pkg.parent / "assets", pkg / "assets"):
        if cand.is_dir():
            return cand
    return pkg.parent.parent / "assets"


_FONT_FAMILY_CACHE: Optional[str] = None
_FONT_FAMILY_TRIED = False


def _cjk_font_family() -> str:
    """挑一个支持中文的系统字体；找不到返回空串（用 Qt 默认字体）。"""
    global _FONT_FAMILY_CACHE, _FONT_FAMILY_TRIED
    if _FONT_FAMILY_TRIED:
        return _FONT_FAMILY_CACHE or ""
    _FONT_FAMILY_TRIED = True # type: ignore
    candidates = [
        "Noto Sans CJK SC",
        "Noto Sans SC",
        "Source Han Sans SC",
        "Microsoft YaHei",
        "PingFang SC",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "SimHei",
        "HarmonyOS Sans SC",
        "MiSans",
    ]
    try:
        families: set[str] = set(QFontDatabase.families())
    except Exception:
        families = set()
    for name in candidates:
        if name in families:
            _FONT_FAMILY_CACHE = name
            return name
    return ""



class SoundManager:
    """按压/松手音效（缺失时静默降级）。"""

    def __init__(self) -> None:
        self._press: Any = None
        self._release: Any = None
        self._vol = 0.9
        self._set = "duck"
        self._enabled = QMediaPlayer is not None
        self._build()

        fam = _cjk_font_family()
        print("CJK font:", repr(fam))

    def _build(self) -> None:
        if not self._enabled:
            return
        try:
            self._press = QMediaPlayer()
            self._release = QMediaPlayer()
            self._press.setAudioOutput(QAudioOutput())
            self._release.setAudioOutput(QAudioOutput())
        except Exception:
            self._press = self._release = None

    def set_sound_set(self, name: str) -> None:
        self._set = "fx1" if name == "fx1" else "duck"
        self._apply_sources()

    def set_volume(self, vol: float) -> None:
        self._vol = max(0.0, min(1.0, vol))
        if self._enabled and self._press and self._release:
            try:
                self._press.audioOutput().setVolume(self._vol)
                self._release.audioOutput().setVolume(self._vol)
            except Exception:
                pass

    def _apply_sources(self) -> None:
        if not self._enabled or not self._press:
            return
        assets = _assets_dir()
        if self._set == "fx1":
            press_p, release_p = assets / "D1.mp3", assets / "D2.mp3"
        else:
            press_p, release_p = assets / "Ya1.mp3", assets / "Ya2.mp3"
        try:
            self._press.setSource(QUrl.fromLocalFile(str(press_p)) if press_p.exists() else QUrl())
            self._release.setSource(QUrl.fromLocalFile(str(release_p)) if release_p.exists() else QUrl())
        except Exception:
            pass

    def play_press(self) -> None:
        if self._enabled and self._press:
            try:
                self._press.stop()
                self._press.play()
            except Exception:
                pass

    def play_release(self) -> None:
        if self._enabled and self._release:
            try:
                self._release.stop()
                self._release.play()
            except Exception:
                pass


class WhaleWidget(QWidget):
    """透明置顶小鲸鱼挂件主窗口。"""

    payload_ready = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        # ---- 状态 ----
        cfg = storage.read_config()
        self._scale: float = float(cfg.get("scale", 1.0))
        self._sound_on: bool = bool(cfg.get("sound", True))
        self._vol: float = float(cfg.get("vol", 0.9))
        self._sound_set: str = cfg.get("soundSet", "duck")
        self._usage_mode: str = cfg.get("usageMode", "ledger")
        self._peak_mode: str = cfg.get("peakMode", "default")
        self._bubble_on: bool = bool(cfg.get("bubbleOn", True))
        self._turn_cost_on: bool = bool(cfg.get("turnCostOn", True))
        self._turn_cost_close_ms: int = int(cfg.get("turnCostCloseMs", 5000))

        self._left: int = int(cfg.get("left") if cfg.get("left") is not None else 0)
        self._top: int = int(cfg.get("top") if cfg.get("top") is not None else 0)

        self._balance: Optional[float] = None
        self._shown: Optional[float] = None
        self._currency: str = "CNY"
        self._today_usage: Any = None
        self._is_peak: bool = False
        self._status: str = "loading"  # loading | ok | error | changing
        self._message: str = ""
        self._busy: bool = False
        self._rolling: bool = False

        # ---- 气泡 ----
        self._bubble_shown = False
        self._bubble_random = False
        self._cost_bubble = False
        self._gif_line = False
        self._bubble_lines: List[Tuple[str, str, bool, str]] = []
        self._bubble_opacity = 0.0
        self._bubble_timer: Optional[QTimer] = None
        self._last_hint: Optional[str] = None
        self._gif_movie: Optional[QMovie] = None

        # ---- 交互 ----
        self._pressing = False
        self._hover = False
        self._menu_open = False
        self._drag: Optional[Dict[str, Any]] = None
        self._menu: Optional[SettingsMenu] = None

        # ---- 资源 ----
        assets = _assets_dir()
        self._whale_pix = self._load_whale(assets)
        self._whale_img = self._whale_pix.toImage() if not self._whale_pix.isNull() else QImage()
        self._svg = QSvgRenderer(BUBBLE_SVG.encode("utf-8"))
        gif_path = assets / "rua.gif"
        if gif_path.exists():
            self._gif_movie = QMovie(str(gif_path))
            self._gif_movie.setCacheMode(QMovie.CacheMode.CacheAll)
            self._gif_movie.frameChanged.connect(lambda _: self.update())
            self._gif_movie.setPaused(True)

        self._sound = SoundManager()
        self._sound.set_sound_set(self._sound_set)
        self._sound.set_volume(self._vol if self._sound_on else 0.0)

        # ---- 定时器 ----
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(lambda: self.refresh(False))
        self._refresh_timer.start(REFRESH_MS)

        self._turn_timer = QTimer(self)
        self._turn_timer.timeout.connect(self._poll_last_turn)
        self._turn_timer.start(1000)

        self._last_cost_seq = 0
        self._last_cost_aligned = False

        self.payload_ready.connect(self._on_payload)

        # 初始几何：无保存位置时右下角吸附
        self._apply_size(initial=True)
        self._first_position()

    # ---------------- 资源 ----------------
    def _load_whale(self, assets: Path) -> QPixmap:
        for name in ("DSniang1.png", "DSniang02.png"):
            p = assets / name
            if p.exists():
                pm = QPixmap(str(p))
                if not pm.isNull():
                    return pm
        return QPixmap()

    # ---------------- 几何 ----------------
    def _viewport(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)

    def _base(self) -> int:
        geo = self._viewport()
        v = min(geo.width(), geo.height())
        return int(max(122, min(625, min(250, v * 0.28) * self._scale)))

    def _apply_size(self, initial: bool = False) -> None:
        base = self._base()
        self.setFixedSize(base, base)
        self.settle()
        self._update_mask()

    def settle(self) -> None:
        # 自由悬浮：只把挂件限制在当前屏幕内，不做吸附
        geo = self._viewport()
        w, h = self.width(), self.height()
        self._left = max(geo.left(), min(self._left, max(geo.left(), geo.right() - w + 1)))
        self._top = max(geo.top(), min(self._top, max(geo.top(), geo.bottom() - h + 1)))
        self.move(self._left, self._top)

    def _first_position(self) -> None:
        cfg = storage.read_config()
        if cfg.get("left") is not None and cfg.get("top") is not None:
            self._left = int(cfg["left"])
            self._top = int(cfg["top"])
            self.settle()
            return
        # 默认放屏幕右下角
        geo = self._viewport()
        w, h = self.width(), self.height()
        self._left = geo.right() - w + 1
        self._top = geo.bottom() - h + 1
        self.move(self._left, self._top)
        self._save_position()

    # ---------------- 绘制 ----------------
    def paintEvent(self, event) -> None:  # noqa: N802
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        qp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._draw(qp, self._base(), for_mask=False)
        qp.end()

    def _draw(self, qp: QPainter, base: int, for_mask: bool) -> None:
        squish = self._pressing

        if squish:
            qp.save()
            qp.translate(base / 2.0, float(base))
            qp.scale(1.12, 0.88)
            qp.translate(-base / 2.0, -float(base))

        # ---- 气泡 + 文字 + gif ----
        if self._bubble_shown:
            opacity = 1.0 if for_mask else self._bubble_opacity
            qp.save()
            qp.setOpacity(opacity)
            bubble_h = base * 700.0 / 1026.0
            self._svg.render(qp, QRectF(0, 0, base, bubble_h))
            qp.restore()

            u = base / 1026.0
            cx = base * 0.45
            cy = base * 0.25
            if self._gif_line:
                self._draw_gif(qp, cx, cy, u, opacity if not for_mask else 1.0)
            elif self._bubble_lines:
                self._draw_lines(qp, self._bubble_lines, cx, cy, u, opacity if not for_mask else 1.0)

        # ---- 鲸鱼 ----
        if not self._whale_pix.isNull():
            ws = base * 0.5945
            qp.drawPixmap(QRectF(base - ws, base - ws, ws, ws), self._whale_pix, QRectF(self._whale_pix.rect()))

        if squish:
            qp.restore()

        # ---- 汉堡菜单按钮（始终右上角，不受按压影响） ----
        if self._hover or self._menu_open:
            btn = self._btn_rect(base)
            qp.save()
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(32, 49, 112, 217))
            qp.drawRoundedRect(btn, 6, 6)
            qp.setPen(QPen(QColor("#ffffff"), 2))
            for i in range(3):
                y = btn.top() + 8 + i * 6
                qp.drawLine(QPoint(btn.left() + 6, y), QPoint(btn.right() - 6, y))
            qp.restore()

    def _btn_rect(self, base: int) -> QRect:
        # 原版：top:40.55%+4px, right:4px, 26×26
        return QRect(base - 4 - 26, int(base * 0.4055) + 4, 26, 26)

    # ---------------- 文字 ----------------
    def _style_font(self, style: str, u: float) -> QFont:
        font = QFont(_cjk_font_family())
        if style == "B":  # 金额
            font.setPixelSize(max(8, int(128 * u)))
            font.setWeight(QFont.Weight.ExtraBold)
        elif style == "P":  # 时段
            font.setPixelSize(max(8, int(104 * u)))
            font.setWeight(QFont.Weight.ExtraBold)
        elif style == "C":  # 提示
            font.setPixelSize(max(6, int(56 * u)))
            font.setWeight(QFont.Weight.Normal)
        else:  # A 标签
            font.setPixelSize(max(6, int(66 * u)))
            font.setWeight(QFont.Weight.DemiBold)
        return font

    def _style_color(self, style: str, color: str) -> QColor:
        if color:
            return QColor(color)
        if style == "C":
            return QColor(HINT_COLOR)
        return QColor(TEXT_COLOR)

    def _draw_lines(self, qp: QPainter, lines: List[Tuple[str, str, bool, str]], cx: float, cy: float, u: float, opacity: float) -> None:
        items = [(t, s, w, c) for (t, s, w, c) in lines if t]
        if not items:
            return
        # 行高用真实 QFontMetrics.height()，保证各行绝不重叠（原版 CSS line-height 换算成 Qt 会偏小导致文字挤在一起）
        laid = []
        for text, style, wrap, color in items:
            font = self._style_font(style, u)
            laid.append((text, style, wrap, color, font, QFontMetrics(font)))
        margin = 9 * u if len(items) >= 3 else 0
        total = sum(fm.height() for (_, _, _, _, _, fm) in laid) + margin
        y = (cy - total / 2.0)
        qp.save()
        qp.setOpacity(opacity)
        for idx, (text, style, wrap, color, font, fm) in enumerate(laid):
            qp.setFont(font)
            qp.setPen(self._style_color(style, color))
            lh = fm.height()
            if wrap:
                self._draw_wrapped(qp, text, font, cx, y + lh / 2.0, 560 * u)
            else:
                qp.drawText(QPointF(cx - fm.horizontalAdvance(text) / 2.0, y + fm.ascent()), text)
            y += lh
            if idx == 1 and len(items) >= 3:
                y += margin
        qp.restore()

    def _draw_wrapped(self, qp: QPainter, text: str, font: QFont, cx: float, center_y: float, max_w: float) -> None:
        fm = QFontMetrics(font)
        words = text.split(" ")
        lines: List[str] = []
        cur = ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if fm.horizontalAdvance(trial) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        total_h = len(lines) * fm.height()
        y = center_y - total_h / 2.0
        for ln in lines:
            w = fm.horizontalAdvance(ln)
            qp.drawText(QPointF(cx - w / 2.0, y + fm.ascent()), ln)
            y += fm.height()

    def _draw_gif(self, qp: QPainter, cx: float, cy: float, u: float, opacity: float) -> None:
        if not self._gif_movie:
            return
        frame = self._gif_movie.currentPixmap()
        if frame.isNull():
            return
        tw, th = 560 * u, 400 * u
        ratio = min(tw / max(1, frame.width()), th / max(1, frame.height()))
        w, h = frame.width() * ratio, frame.height() * ratio
        qp.save()
        qp.setOpacity(opacity)
        qp.drawPixmap(QRectF(cx - w / 2.0, cy - h / 2.0, w, h), frame, QRectF(frame.rect()))
        qp.restore()

    # ---------------- 蒙版（点击穿透） ----------------
    def _update_mask(self) -> None:
        base = self._base()
        img = QImage(base, base, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        qp = QPainter(img)
        self._draw(qp, base, for_mask=True)
        qp.end()
        region = QRegion()
        step = 2
        for y in range(0, base, step):
            for x in range(0, base, step):
                rgb = img.pixel(x, y)
                if (rgb >> 24) & 0xFF > 12:
                    region += QRegion(x, y, step, step)
        # 汉堡按钮区域始终可点
        region += QRegion(self._btn_rect(base))
        self.setMask(region)

    # ---------------- 命中检测 ----------------
    def _hit_whale(self, pos: QPointF) -> bool:
        if self._whale_pix.isNull():
            return False
        base = self._base()
        ws = base * 0.5945
        x0, y0 = base - ws, base - ws
        if not (x0 <= pos.x() <= base and y0 <= pos.y() <= base):
            return False
        # 原版拉伸到 610×610 做像素级 alpha 命中
        lx = (pos.x() - x0) / ws * 610
        ly = (pos.y() - y0) / ws * 610
        if not (0 <= lx < 610 and 0 <= ly < 610):
            return False
        img = self._whale_img
        if img.isNull():
            return True
        ix = min(img.width() - 1, int(lx / 610 * img.width()))
        iy = min(img.height() - 1, int(ly / 610 * img.height()))
        rgb = img.pixel(ix, iy)
        return (rgb >> 24) & 0xFF > 10

    def _hit_bubble(self, pos: QPointF) -> bool:
        if not self._bubble_shown:
            return False
        base = self._base()
        bubble_h = base * 700.0 / 1026.0
        return 0 <= pos.x() <= base and 0 <= pos.y() <= bubble_h

    def _hit_btn(self, pos: QPointF) -> bool:
        return self._btn_rect(self._base()).contains(QPoint(int(pos.x()), int(pos.y())))

    # ---------------- 鼠标事件 ----------------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._menu_open:
            self._close_menu()
            return
        if self._hit_btn(pos):
            self._toggle_menu()
            return
        if self._hit_whale(pos):
            # 鲸鱼在气泡之上：先拖拽，不触发气泡
            pass
        elif self._hit_bubble(pos):
            self._toggle_bubble()
            return
        else:
            return
        self._drag = {
            "global_start": event.globalPosition().toPoint(),
            "orig_left": self._left,
            "orig_top": self._top,
            "moved": False,
            "vp": self._viewport(),
        }
        self._pressing = True
        self._sound.play_press()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self._update_mask()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if self._drag:
            d = self._drag
            global_pos = event.globalPosition().toPoint()
            dx = global_pos.x() - d["global_start"].x()
            dy = global_pos.y() - d["global_start"].y()
            if dx * dx + dy * dy >= CLICK_SQ:
                d["moved"] = True
            geo = d["vp"]
            w, h = self.width(), self.height()
            self._left = max(geo.left(), min(int(d["orig_left"] + dx), max(geo.left(), geo.right() - w + 1)))
            self._top = max(geo.top(), min(int(d["orig_top"] + dy), max(geo.top(), geo.bottom() - h + 1)))
            self.move(self._left, self._top)
            return
        # 悬停状态
        over = self._hit_whale(pos) or self._hit_btn(pos) or self._hit_bubble(pos)
        self._hover = bool(over)
        if self._hit_btn(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._hit_whale(pos):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if not self._drag:
            return
        d = self._drag
        self._drag = None
        self._pressing = False
        self._sound.play_release()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._update_mask()
        self.update()
        if not d["moved"]:
            # 点击鲸鱼：展示气泡 + 手动刷新
            self.show_bubble()
            self.refresh(True)
            return
        self._snap_and_save()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def _snap_and_save(self) -> None:
        # 自由悬浮：拖到哪里就停哪里（不做吸附），仅保存位置
        self.settle()
        self._update_mask()
        self._save_position()

    # ---------------- 气泡 ----------------
    def _default_lines(self) -> List[Tuple[str, str, bool, str]]:
        amount = fmt_amount(self._shown if self._shown is not None else self._balance, self._currency)
        if self._status == "error":
            amount = fmt_amount(self._shown, self._currency) if self._shown is not None else "--"
            hint = (self._message or "获取失败 · 点击重试")[:14] + " · 点击重试"
        elif self._balance is None:
            amount = fmt_amount(self._shown, self._currency) if self._shown is not None else "…"
            hint = "加载中…"
        else:
            amount = fmt_amount(self._shown if self._shown is not None else self._balance, self._currency)
            hint = "今日已用 " + fmt_amount(self._today_usage, self._currency) if self._today_usage is not None else "今日已用 --"
        return [("DeepSeek 余额", "A", False, ""), (amount, "B", False, ""), (hint, "C", False, "")]

    def show_bubble(self) -> None:
        if not self._bubble_on or self._cost_bubble:
            return
        self._bubble_random = False
        self._gif_line = False
        self._bubble_lines = self._default_lines()
        self._bubble_shown = True
        self._last_hint = None
        self._start_bubble_timer(BUBBLE_MS)
        self._animate_opacity(0.0, 1.0, 200, lambda: None)
        self._update_mask()
        self.update()

    def _toggle_bubble(self) -> None:
        if self._cost_bubble:
            self._hide_cost_bubble()
            return
        if self._bubble_random:
            self._hide_bubble()
            return
        self._bubble_random = True
        gif, lines = self._pick_random_lines()
        if gif:
            # gif 不可用时降级为文字台词，避免空白白色气泡
            if self._gif_movie is None or self._gif_movie.currentPixmap().isNull():
                self._gif_line = False
                self._bubble_lines = [(random.choice(RANDOM_GIF_FALLBACK), "A", True, "")]
                self._stop_gif()
            else:
                self._gif_line = True
                self._bubble_lines = []
                self._start_gif()
        else:
            self._gif_line = False
            self._bubble_lines = lines
            self._stop_gif()
        self._restart_bubble_timer(BUBBLE_MS)
        self.update()

    def _hide_bubble(self) -> None:
        self._stop_bubble_timer()
        self._bubble_random = False
        self._gif_line = False
        self._stop_gif()
        self._animate_opacity(self._bubble_opacity, 0.0, 200, self._finish_hide)

    def _finish_hide(self) -> None:
        self._bubble_shown = False
        self._update_mask()
        self.update()

    def _show_cost_bubble(self, amount: float) -> None:
        if not self._bubble_on or not self._turn_cost_on:
            return
        self._cost_bubble = True
        self._bubble_random = False
        self._gif_line = False
        self._stop_gif()
        self._bubble_lines = [
            ("上一轮对话消耗:", "A", False, ""),
            ("¥ " + (f"{amount:.2f}" if math.isfinite(amount) else "--"), "B", False, PEAK_COLOR),
        ]
        self._bubble_shown = True
        self._stop_bubble_timer()
        self._animate_opacity(0.0, 1.0, 200, lambda: None)
        if self._turn_cost_close_ms > 0:
            self._start_bubble_timer(self._turn_cost_close_ms)
        self._update_mask()
        self.update()

    def _hide_cost_bubble(self) -> None:
        self._cost_bubble = False
        self._hide_bubble()

    def _start_bubble_timer(self, ms: int) -> None:
        self._stop_bubble_timer()
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._on_bubble_timeout)
        self._bubble_timer.start(ms)

    def _restart_bubble_timer(self, ms: int) -> None:
        if self._bubble_timer:
            self._bubble_timer.start(ms)

    def _stop_bubble_timer(self) -> None:
        if self._bubble_timer:
            self._bubble_timer.stop()
            self._bubble_timer.deleteLater()
            self._bubble_timer = None

    def _on_bubble_timeout(self) -> None:
        if self._cost_bubble:
            self._hide_cost_bubble()
        else:
            self._hide_bubble()

    def _animate_opacity(self, start: float, end: float, ms: int, done) -> None:
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        def on_value(v):
            self._bubble_opacity = float(v)
            self.update()

        anim.valueChanged.connect(on_value)
        anim.finished.connect(lambda: (done(), anim.deleteLater()))
        anim.start()

    def _start_gif(self) -> None:
        if self._gif_movie:
            base = self._base()
            u = base / 1026.0
            w = int(560 * u)
            h = int(400 * u)
            self._gif_movie.setScaledSize(QSize(w, h))
            self._gif_movie.jumpToFrame(0)
            self._gif_movie.setPaused(False)
            self._gif_movie.start()

    def _stop_gif(self) -> None:
        if self._gif_movie:
            self._gif_movie.setPaused(True)
            self._gif_movie.stop()

    # ---------------- 随机台词 ----------------
    def _pick_random_lines(self) -> Tuple[bool, List[Tuple[str, str, bool, str]]]:
        groups: List[Tuple[int, Any]] = [
            (45, self._group1),
            (7, lambda: ([("好模型... ↓", "B", False, "")], False)),
            (7, lambda: ([(random.choice(RANDOM_TAUNTS), "A", True, "")], False)),
            (10, lambda: ([], True)),
            (3, lambda: ([(random.choice(RANDOM_TOKEN_LINES), "A", True, "")], False)),
            (1, lambda: ([("哦鲸鲸... ", "B", False, "")], False)),
        ]
        total = sum(g[0] for g in groups)
        r = random.random() * total
        for w, fn in groups:
            r -= w
            if r < 0:
                lines, gif = fn()
                return gif, lines
        lines, gif = groups[-1][1]()
        return gif, lines

    def _group1(self):
        peak = self._is_peak
        off_text, peak_text = "空闲时段", "高峰时段"
        if self._peak_mode == "liangwen":
            off_text, peak_text = "梁文谷", "梁文峰"
        elif self._peak_mode == "qiangqiang":
            off_text, peak_text = "!?谷谷?!", "!?峰峰?!"
        lines = [
            ("当前时间段为:", "A", False, ""),
            (peak_text if peak else off_text, "P", False, PEAK_COLOR if peak else OFFPEAK_COLOR),
            ("今日已用 " + fmt_amount(self._today_usage, self._currency), "C", False, ""),
        ]
        return lines, False

    # ---------------- 余额刷新 ----------------
    def refresh(self, manual: bool = False) -> None:
        if self._busy:
            return
        self._busy = True
        if manual or self._balance is None:
            self._status = "loading"
            self.update()
        threading.Thread(target=self._run_fetch, daemon=True).start()

    def _run_fetch(self) -> None:
        payload = self._fetch_payload()
        self.payload_ready.emit(payload)

    def _fetch_payload(self) -> Dict[str, Any]:
        try:
            creds = api.resolve_credentials()
            payload = api.fetch_balance(creds.get("api_key") or "")
            if payload.get("ok"):
                led = storage.record_ledger_usage(float(payload["totalBalance"]))
                payload["isPeak"] = is_peak_time(time.time())
                if self._usage_mode == "ledger":
                    payload["todayUsage"] = led["todayUsage"]
                    payload["usageMode"] = "ledger"
                else:
                    u = api.fetch_usage(creds.get("platform_token") or "")
                    if u.get("amount") is not None:
                        payload["todayUsage"] = u["amount"]
                        payload["usageMode"] = "token"
                    else:
                        payload["todayUsage"] = led["todayUsage"]
                        payload["usageMode"] = "ledger"
            return payload
        except Exception as e:  # pragma: no cover
            return {"ok": False, "code": "ERROR", "error": f"余额服务异常: {e}"}

    def _on_payload(self, payload: Dict[str, Any]) -> None:
        self._busy = False
        try:
            if payload.get("ok"):
                nb = float(payload["totalBalance"])
                nc = str(payload.get("currency") or "CNY")
                changed = self._balance is not None and (nb != self._balance or nc != self._currency)
                currency_changed = self._currency is not None and nc != self._currency
                self._balance = nb
                self._currency = nc
                self._message = ""
                self._today_usage = payload.get("todayUsage")
                self._is_peak = bool(payload.get("isPeak"))
                if changed and not currency_changed and self._shown is not None:
                    self.show_bubble()
                    self._status = "changing"
                    self.update()
                    QTimer.singleShot(300, lambda: self._roll_number(nb, nc))
                    QTimer.singleShot(CHANGE_MS + 300, self._settle_ok)
                else:
                    if not self._rolling:
                        self._shown = nb
                    self._status = "ok"
                    self._update_content()
            else:
                if payload.get("transient") and self._balance is not None:
                    # 瞬时网络抖动：沿用最近余额
                    self._status = "ok"
                    self._message = ""
                    self.update()
                else:
                    self._status = "error"
                    self._message = str(payload.get("error") or "获取失败")
                    self._update_content()
        except Exception:
            self._status = "error"
            self._message = "解析余额失败"
            self._update_content()

    def _settle_ok(self) -> None:
        if self._status == "changing":
            self._status = "ok"
            self._update_content()

    def _roll_number(self, to: float, currency: str) -> None:
        if self._cost_bubble:
            self._shown = to
            return
        start = self._shown if self._shown is not None else to
        if start == to:
            self._shown = to
            self._status = "ok"
            self._update_content()
            return
        self._rolling = True
        if getattr(self, "_roll_anim", None):
            try:
                self._roll_anim.stop()
            except Exception:
                pass
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(to)
        anim.setDuration(CHANGE_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def on_value(v):
            self._shown = float(v)
            self._update_content()

        def on_finish():
            self._rolling = False
            self._shown = to
            self._update_content()
            anim.deleteLater()

        anim.valueChanged.connect(on_value)
        anim.finished.connect(on_finish)
        self._roll_anim = anim
        anim.start()

    def _update_content(self) -> None:
        if self._cost_bubble:
            return
        if self._bubble_shown and not self._bubble_random and not self._gif_line:
            self._bubble_lines = self._default_lines()
        self.update()

    # ---------------- 每轮对话消耗（可选，读 DSH 导出的 JSON） ----------------
    def _last_turn_candidates(self) -> List[Path]:
        env = os.environ.get("DSHW_LAST_TURN_FILE")
        home = storage.dsh_home()
        return [
            Path(env) if env else None,
            home / ".dshw-last-turn.json",
            Path.home() / ".dshw-last-turn.json",
        ]

    def _poll_last_turn(self) -> None:
        for p in self._last_turn_candidates():
            if not p:
                continue
            try:
                if not p.is_file():
                    continue
                data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("seq"), (int, float)):
                    continue
                seq = int(data["seq"])
                if not self._last_cost_aligned:
                    self._last_cost_seq = seq
                    self._last_cost_aligned = True
                    return
                if seq > self._last_cost_seq:
                    self._last_cost_seq = seq
                    if data.get("turn") is not None and data.get("amount") is not None:
                        self._show_cost_bubble(float(data["amount"]))
                return
            except Exception:
                continue

    # ---------------- 菜单 ----------------
    def _toggle_menu(self) -> None:
        if self._menu_open:
            self._close_menu()
        else:
            self._open_menu()

    def _open_menu(self) -> None:
        if self._menu is None:
            self._menu = SettingsMenu(self)
        self._menu_open = True
        self._menu.refresh_values()
        self._menu.adjustSize()
        btn = self._btn_rect(self._base())
        global_tl = self.mapToGlobal(btn.topLeft())
        global_br = self.mapToGlobal(btn.bottomRight())
        screen = self._viewport()
        if self._left + self.width() / 2.0 < screen.center().x():
            # 挂件在左半边：菜单左上角对齐按钮右上角
            pos = QPoint(global_br.x(), global_br.y())
        else:
            # 挂件在右半边：菜单右下角对齐按钮左上角
            pos = QPoint(global_tl.x() - self._menu.width(), global_tl.y())
        self._menu.move(pos)
        self._menu.show()
        self._menu.raise_()
        self._menu.activateWindow()
        self.update()

    def _close_menu(self) -> None:
        self._menu_open = False
        if self._menu:
            self._menu.hide()
        self.update()

    def set_scale(self, scale: float) -> None:
        self._scale = max(MIN_SCALE, min(MAX_SCALE, scale))
        self._apply_size()
        self._save_position()

    def set_sound_set(self, name: str) -> None:
        self._sound_set = "fx1" if name == "fx1" else "duck"
        self._sound.set_sound_set(self._sound_set)
        self._save_position()

    def set_volume(self, vol: float) -> None:
        self._vol = max(0.0, min(1.0, vol))
        self._sound_on = self._vol > 0
        self._sound.set_volume(self._vol if self._sound_on else 0.0)
        self._save_position()

    def set_usage_mode(self, mode: str) -> None:
        mode = "token" if mode == "token" else "ledger"
        if mode != self._usage_mode:
            self._usage_mode = mode
            self._save_position()
            self.refresh(True)

    def set_peak_mode(self, mode: str) -> None:
        mode = mode if mode in ("liangwen", "qiangqiang") else "default"
        self._peak_mode = mode
        self._save_position()

    def set_bubble_on(self, on: bool) -> None:
        self._bubble_on = on
        if not on:
            self._hide_bubble()
        self._save_position()

    def set_turn_cost_on(self, on: bool) -> None:
        self._turn_cost_on = on
        self._save_position()

    def set_turn_cost_close_ms(self, ms: int) -> None:
        self._turn_cost_close_ms = ms
        self._save_position()

    def _save_position(self) -> None:
        cfg = storage.read_config()
        cfg.update(
            {
                "scale": self._scale,
                "sound": self._sound_on,
                "vol": self._vol,
                "soundSet": self._sound_set,
                "usageMode": self._usage_mode,
                "peakMode": self._peak_mode,
                "bubbleOn": self._bubble_on,
                "turnCostOn": self._turn_cost_on,
                "turnCostCloseMs": self._turn_cost_close_ms,
                "left": self._left,
                "top": self._top,
            }
        )
        storage.write_config(cfg)

    def open_credentials_dialog(self) -> None:
        dlg = CredentialsDialog(self)
        dlg.exec()


class SettingsMenu(QFrame):
    """挂件配置弹出菜单。"""

    def __init__(self, widget: WhaleWidget) -> None:
        super().__init__(widget)
        self._w = widget
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet(
            "QFrame#menu{background:#fff;border:1px solid rgba(32,49,112,.45);border-radius:10px;}"
            "QLabel{color:#203170;font-size:12px;} QComboBox,QSpinBox{border:1px solid rgba(32,49,112,.4);"
            "border-radius:6px;padding:2px 4px;font-size:12px;color:#203170;background:#fff;}"
            "QSlider::handle:horizontal{background:#203170;width:12px;height:12px;margin:-5px 0;border-radius:6px;}"
            "QSlider::groove:horizontal{height:4px;background:rgba(32,49,112,.25);border-radius:2px;}"
            "QPushButton{border:1px solid rgba(32,49,112,.4);border-radius:6px;padding:3px 8px;font-size:12px;color:#203170;background:rgba(32,49,112,.08);}"
            "QPushButton:hover{background:rgba(32,49,112,.16);}"
        )
        self.setObjectName("menu")
        self.setMinimumWidth(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)

        # 大小
        row = QHBoxLayout()
        row.addWidget(QLabel("大小"))
        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(60, 250)
        self.scale_slider.valueChanged.connect(self._on_scale_slider)
        row.addWidget(self.scale_slider, 1)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(1, 20)
        self.scale_spin.valueChanged.connect(self._on_scale_spin)
        row.addWidget(self.scale_spin)
        lay.addLayout(row)

        # 音效
        row = QHBoxLayout()
        row.addWidget(QLabel("音效"))
        self.sound_combo = QComboBox()
        self.sound_combo.addItem("小黄鸭", "duck")
        self.sound_combo.addItem("音效1", "fx1")
        self.sound_combo.currentIndexChanged.connect(self._on_sound)
        row.addWidget(self.sound_combo, 1)
        lay.addLayout(row)

        # 音量
        row = QHBoxLayout()
        row.addWidget(QLabel("音量"))
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.valueChanged.connect(self._on_vol)
        row.addWidget(self.vol_slider, 1)
        self.vol_label = QLabel()
        row.addWidget(self.vol_label)
        lay.addLayout(row)

        # 用量
        row = QHBoxLayout()
        row.addWidget(QLabel("用量"))
        self.usage_combo = QComboBox()
        self.usage_combo.addItem("小鲸鱼记账 (推荐)", "ledger")
        self.usage_combo.addItem("实时·令牌", "token")
        self.usage_combo.currentIndexChanged.connect(self._on_usage)
        row.addWidget(self.usage_combo, 1)
        lay.addLayout(row)

        # 峰谷
        row = QHBoxLayout()
        row.addWidget(QLabel("峰谷"))
        self.peak_combo = QComboBox()
        self.peak_combo.addItem("默认", "default")
        self.peak_combo.addItem("梁文峰谷", "liangwen")
        self.peak_combo.addItem("!?强强?!", "qiangqiang")
        self.peak_combo.currentIndexChanged.connect(self._on_peak)
        row.addWidget(self.peak_combo, 1)
        lay.addLayout(row)

        # 气泡
        self.bubble_check = QCheckBox("思考气泡")
        self.bubble_check.stateChanged.connect(self._on_bubble)
        lay.addWidget(self.bubble_check)

        # 每轮消耗提示
        row = QHBoxLayout()
        self.turn_check = QCheckBox("每轮消耗提示")
        self.turn_check.stateChanged.connect(self._on_turn)
        row.addWidget(self.turn_check)
        row.addWidget(QLabel("自动关闭"))
        self.turn_close = QSpinBox()
        self.turn_close.setRange(0, 600)
        self.turn_close.setSuffix(" 秒")
        self.turn_close.setToolTip("填 0 表示不自动关闭")
        self.turn_close.valueChanged.connect(self._on_turn_close)
        row.addWidget(self.turn_close)
        lay.addLayout(row)

        # 底部按钮
        row = QHBoxLayout()
        api_btn = QPushButton("API 设置…")
        api_btn.clicked.connect(self._w.open_credentials_dialog)
        quit_btn = QPushButton("退出")
        quit_btn.clicked.connect(QApplication.instance().quit)
        row.addWidget(api_btn)
        row.addWidget(quit_btn)
        lay.addLayout(row)

    def refresh_values(self) -> None:
        w = self._w
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(int(w._scale * 100))
        self.scale_slider.blockSignals(False)
        self.scale_spin.blockSignals(True)
        self.scale_spin.setValue(self._scale_to_display(w._scale))
        self.scale_spin.blockSignals(False)
        self.sound_combo.setCurrentIndex(0 if w._sound_set == "duck" else 1)
        self.vol_slider.setValue(int(w._vol * 100))
        self.vol_label.setText(f"{int(w._vol * 100)}%")
        self.usage_combo.setCurrentIndex(0 if w._usage_mode == "ledger" else 1)
        self.peak_combo.setCurrentIndex({"default": 0, "liangwen": 1, "qiangqiang": 2}.get(w._peak_mode, 0))
        self.bubble_check.setChecked(w._bubble_on)
        self.turn_check.setChecked(w._turn_cost_on)
        self.turn_close.setValue(int(w._turn_cost_close_ms / 1000) if w._turn_cost_close_ms > 0 else 0)

    @staticmethod
    def _scale_to_display(s: float) -> int:
        return int(round(1 + (s - MIN_SCALE) / (MAX_SCALE - MIN_SCALE) * 19))

    @staticmethod
    def _display_to_scale(v: int) -> float:
        return MIN_SCALE + max(0, min(20, v) - 1) * (MAX_SCALE - MIN_SCALE) / 19.0

    def _on_scale_slider(self, v: int) -> None:
        s = v / 100.0
        self._w.set_scale(s)
        self.scale_spin.blockSignals(True)
        self.scale_spin.setValue(self._scale_to_display(s))
        self.scale_spin.blockSignals(False)

    def _on_scale_spin(self, v: int) -> None:
        s = self._display_to_scale(v)
        self._w.set_scale(s)
        self.scale_slider.blockSignals(True)
        self.scale_slider.setValue(int(s * 100))
        self.scale_slider.blockSignals(False)

    def _on_sound(self, _: int) -> None:
        self._w.set_sound_set(self.sound_combo.currentData())

    def _on_vol(self, v: int) -> None:
        self._w.set_volume(v / 100.0)
        self.vol_label.setText(f"{v}%")

    def _on_usage(self, _: int) -> None:
        self._w.set_usage_mode(self.usage_combo.currentData())

    def _on_peak(self, _: int) -> None:
        self._w.set_peak_mode(self.peak_combo.currentData())

    def _on_bubble(self, state: int) -> None:
        self._w.set_bubble_on(state == Qt.CheckState.Checked.value)

    def _on_turn(self, state: int) -> None:
        self._w.set_turn_cost_on(state == Qt.CheckState.Checked.value)

    def _on_turn_close(self, v: int) -> None:
        self._w.set_turn_cost_close_ms(v * 1000)

    def hideEvent(self, event) -> None:  # noqa: N802
        # 用户点击外部 / 按 Esc 关闭 Popup 时同步挂件状态
        self._w._menu_open = False
        self._w.update()
        super().hideEvent(event)


class CredentialsDialog(QDialog):
    """API 凭据设置对话框。"""

    def __init__(self, widget: WhaleWidget) -> None:
        super().__init__(widget)
        self.setWindowTitle("DeepSeek API 设置")
        self.setModal(True)
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        creds = api.resolve_credentials()
        self.key_edit.setText(creds.get("api_key") or "")
        self.token_edit.setText(creds.get("platform_token") or "")
        form.addRow("DEEPSEEK_API_KEY", self.key_edit)
        form.addRow("DEEPSEEK_PLATFORM_TOKEN", self.token_edit)
        note = QLabel(
            "API Key 用于拉取余额（必需）。\n"
            "平台 Token（Bearer eyJ…）仅「实时·令牌」用量模式需要，可选。\n"
            "留空则回退到环境变量 / DSH 凭据。"
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9fb0d9;font-size:11px;")
        form.addRow(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _save(self) -> None:
        storage.write_credentials(
            {
                "DEEPSEEK_API_KEY": self.key_edit.text().strip(),
                "DEEPSEEK_PLATFORM_TOKEN": self.token_edit.text().strip(),
            }
        )
        self.accept()
