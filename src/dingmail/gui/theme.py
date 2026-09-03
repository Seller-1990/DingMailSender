"""设计 token 与全局样式。

新前端采用统一的语义色 token：所有颜色在此定义，QSS 由 build_qss() 生成，
组件代码只引用常量，不允许出现硬编码色值（除个别像素级特例）。
"""
from __future__ import annotations

from PySide6 import QtWidgets

from ..task_status import TaskStatus

# ---- 色板 token ----
BG = "#f4f6fa"            # 页面背景
SURFACE = "#ffffff"       # 卡片/面板
SURFACE_ALT = "#f8fafc"   # 次级表面（表头/斑马纹）
BORDER = "#e4e8f0"
BORDER_STRONG = "#cbd5e1"

TEXT = "#111827"
TEXT_MUTED = "#6b7280"
TEXT_FAINT = "#9ca3af"
TEXT_ON_DARK = "#f8fafc"

RAIL_BG = "#111827"       # 左导航深色底
RAIL_ACTIVE = "#4f46e5"   # 导航激活项

PRIMARY = "#4f46e5"
PRIMARY_HOVER = "#4338ca"
PRIMARY_SOFT = "#eef2ff"
PRIMARY_BORDER = "#c7d2fe"

# 语义色: (文字色, 背景色, 边框色)
TONES: dict[str, tuple[str, str, str]] = {
    "success": ("#047857", "#ecfdf5", "#a7f3d0"),
    "danger": ("#b91c1c", "#fef2f2", "#fecaca"),
    "warning": ("#b45309", "#fffbeb", "#fde68a"),
    "info": ("#1d4ed8", "#eff6ff", "#bfdbfe"),
    "draft": ("#0e7490", "#ecfeff", "#a5f3fc"),
    "neutral": ("#475569", "#f1f5f9", "#e2e8f0"),
}

# 任务状态 -> 语义 tone
STATUS_TONES = {
    TaskStatus.DISABLED: "neutral",
    TaskStatus.UNCHECKED: "neutral",
    TaskStatus.VALIDATION_FAILED: "danger",
    TaskStatus.QUEUED: "warning",
    TaskStatus.SENDING: "info",
    TaskStatus.DRAFTING: "info",
    TaskStatus.SENT: "success",
    TaskStatus.SEND_FAILED: "danger",
    TaskStatus.DRAFT_SAVED: "draft",
    TaskStatus.DRAFT_FAILED: "danger",
    TaskStatus.READY: "info",
}

STATUS_ROW_COLORS = {tone: bg for tone, (_fg, bg, _border) in TONES.items()}

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", sans-serif'


def status_tone(status: TaskStatus | str) -> str:
    try:
        normalized = status if isinstance(status, TaskStatus) else TaskStatus(status)
    except ValueError:
        return "neutral"
    return STATUS_TONES.get(normalized, "neutral")


def tone_color(tone: str) -> tuple[str, str, str]:
    return TONES.get(tone, TONES["neutral"])


def repolish(widget: QtWidgets.QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_variant(widget: QtWidgets.QWidget, variant: str) -> None:
    widget.setProperty("variant", variant)
    repolish(widget)


def build_qss() -> str:
    return f"""
    QMainWindow, QDialog, QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}
    QFrame#Surface {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    QFrame#Surface QWidget {{
        background: transparent;
        border: none;
    }}
    QFrame#NavRail {{
        background: {RAIL_BG};
        border: none;
    }}
    QLabel#AppTitle {{
        font-size: 15px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#SectionTitle {{
        font-size: 14px;
        font-weight: 700;
        color: {TEXT};
    }}
    QLabel#MutedLabel, QLabel#MetricDetail, QLabel#InlineTip {{
        color: {TEXT_MUTED};
    }}
    QLabel#Banner {{
        background: {PRIMARY_SOFT};
        color: {PRIMARY_HOVER};
        border: 1px solid {PRIMARY_BORDER};
        border-radius: 8px;
        padding: 8px 12px;
    }}
    QLabel#Banner[severity="warning"] {{
        background: {"#fffbeb"};
        color: {"#b45309"};
        border-color: {"#fde68a"};
    }}
    QLabel#Banner[severity="danger"] {{
        background: {"#fef2f2"};
        color: {"#b91c1c"};
        border-color: {"#fecaca"};
    }}
    QLabel#StatusTag {{
        border-radius: 10px;
        padding: 3px 9px;
        font-weight: 700;
        border: 1px solid transparent;
    }}
    QPushButton {{
        background: {SURFACE};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 6px 12px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {SURFACE_ALT}; border-color: #aebdcd; }}
    QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE_ALT}; border-color: {BORDER}; }}
    QPushButton[variant="primary"] {{
        background: {PRIMARY}; color: white; border-color: {PRIMARY};
    }}
    QPushButton[variant="primary"]:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
    QPushButton[variant="danger"] {{
        background: {"#fef2f2"}; color: {"#b91c1c"}; border-color: {"#fecaca"};
    }}
    QPushButton[variant="ghost"] {{
        background: transparent; border-color: transparent; color: {TEXT_MUTED};
    }}
    QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QDateTimeEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {SURFACE};
        border: 1px solid {BORDER_STRONG};
        border-radius: 8px;
        padding: 5px 8px;
    }}
    QTableView {{
        background: {SURFACE};
        border: none;
        gridline-color: {BORDER};
        alternate-background-color: {SURFACE_ALT};
        selection-background-color: {PRIMARY_SOFT};
        selection-color: {TEXT};
        font-size: 12px;
    }}
    QHeaderView::section {{
        background: {SURFACE_ALT};
        color: {TEXT_MUTED};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 6px;
        font-weight: 700;
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #c5cfdb; border-radius: 4px; min-height: 28px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: #c5cfdb; border-radius: 4px; min-width: 28px; }}
    QProgressBar {{
        background: {SURFACE_ALT};
        border: 1px solid {BORDER};
        border-radius: 7px;
        text-align: center;
        font-size: 11px;
        color: {TEXT_MUTED};
    }}
    QProgressBar::chunk {{
        background: {PRIMARY};
        border-radius: 6px;
    }}
    QGroupBox {{
        border: 1px solid {BORDER};
        border-radius: 8px;
        margin-top: 12px;
        padding-top: 6px;
        font-weight: 700;
    }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT_MUTED}; }}
    QToolButton {{ background: transparent; border: none; border-radius: 8px; color: {TEXT_MUTED}; padding: 4px; }}
    """


def apply_theme(widget: QtWidgets.QWidget) -> None:
    widget.setStyleSheet(build_qss())
