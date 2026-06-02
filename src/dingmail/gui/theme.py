from __future__ import annotations

from PySide6 import QtWidgets


STATUS_TONES = {
    "已停用": "neutral",
    "未校验": "neutral",
    "校验失败": "danger",
    "已加入定时队列": "warning",
    "发送中": "info",
    "草稿保存中": "info",
    "发送成功": "success",
    "发送失败": "danger",
    "草稿已保存": "draft",
    "草稿保存失败": "danger",
    "可发送": "success",
}


def status_tone(status: str) -> str:
    return STATUS_TONES.get(status, "neutral")


def repolish(widget: QtWidgets.QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_variant(widget: QtWidgets.QWidget, variant: str) -> None:
    widget.setProperty("variant", variant)
    repolish(widget)


WORKBENCH_QSS = """
        QMainWindow, QWidget {
            background: #f5f7fb;
            color: #1f2937;
            font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            font-size: 13px;
        }
        QFrame#Topbar, QFrame#Runbar {
            background: #ffffff;
            border: 1px solid #d8e0ea;
            border-radius: 8px;
        }
        QFrame#Panel, QFrame#MetricTile {
            background: #ffffff;
            border: 1px solid #d8e0ea;
            border-radius: 8px;
        }
        QFrame#PanelHeader {
            background: #f8fafc;
            border-bottom: 1px solid #d8e0ea;
        }
        QLabel#AppTitle {
            font-size: 18px;
            font-weight: 700;
            color: #172033;
        }
        QLabel#SectionTitle {
            font-size: 15px;
            font-weight: 700;
            color: #172033;
        }
        QLabel#DialogTitle {
            font-size: 17px;
            font-weight: 700;
            color: #172033;
        }
        QLabel#SectionHint, QLabel#MutedLabel, QLabel#MetricDetail, QLabel#DialogHint, QLabel#InlineTip {
            color: #64748b;
            line-height: 1.45;
        }
        QLabel#ErrorLabel {
            color: #9b2f25;
            background: #fdecea;
            border-radius: 8px;
            padding: 8px 10px;
        }
        QLabel#MetricTitle {
            color: #64748b;
            font-size: 12px;
            font-weight: 600;
        }
        QLabel#MetricValue {
            color: #172033;
            font-size: 24px;
            font-weight: 700;
        }
        QLabel#StatusTag {
            border-radius: 10px;
            padding: 4px 9px;
            font-weight: 700;
            border: 1px solid transparent;
        }
        QLabel#StatusTag[variant="success"] {
            background: #e9f7ef;
            color: #17663a;
            border-color: #b7e2c6;
        }
        QLabel#StatusTag[variant="draft"] {
            background: #e8f5fb;
            color: #1b5c75;
            border-color: #b9ddea;
        }
        QLabel#StatusTag[variant="warning"] {
            background: #fff4d7;
            color: #7a5200;
            border-color: #ead38b;
        }
        QLabel#StatusTag[variant="danger"] {
            background: #fdecea;
            color: #9b2f25;
            border-color: #e8b8b2;
        }
        QLabel#StatusTag[variant="info"] {
            background: #eaf0ff;
            color: #2457a6;
            border-color: #bcccf4;
        }
        QLabel#StatusTag[variant="neutral"] {
            background: #eef2f6;
            color: #526173;
            border-color: #d5dde6;
        }
        QPushButton {
            background: #ffffff;
            border: 1px solid #c8d2df;
            border-radius: 8px;
            padding: 7px 12px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #f4f7fb;
            border-color: #aebdcd;
        }
        QPushButton:disabled {
            color: #99a5b4;
            background: #eef2f6;
            border-color: #d8e0ea;
        }
        QPushButton[variant="primary"] {
            background: #2864c8;
            color: white;
            border-color: #2864c8;
        }
        QPushButton[variant="primary"]:hover {
            background: #2257ae;
            border-color: #2257ae;
        }
        QPushButton[variant="danger"] {
            background: #fdecea;
            color: #9b2f25;
            border-color: #e8b8b2;
        }
        QPushButton[variant="ghost"] {
            background: transparent;
            border-color: transparent;
            color: #526173;
        }
        QLineEdit, QTextBrowser, QPlainTextEdit, QListWidget, QTableWidget, QDateTimeEdit, QComboBox {
            background: #ffffff;
            border: 1px solid #c8d2df;
            border-radius: 8px;
            padding: 6px 8px;
        }
        QTableWidget {
            gridline-color: #e4e9f0;
            alternate-background-color: #f8fafc;
            selection-background-color: #eaf0ff;
            selection-color: #172033;
            font-size: 12px;
        }
        QHeaderView::section {
            background: #f3f6fa;
            color: #526173;
            border: none;
            border-bottom: 1px solid #d8e0ea;
            padding: 7px 6px;
            font-weight: 700;
        }
        QScrollBar:vertical {
            background: #eef2f6;
            width: 12px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background: #c5cfdb;
            border-radius: 6px;
            min-height: 28px;
        }
        QScrollBar:horizontal {
            background: #eef2f6;
            height: 12px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background: #c5cfdb;
            border-radius: 6px;
            min-width: 28px;
        }
        QSplitter#WorkspaceSplitter::handle {
            background: #d8e0ea;
            margin: 2px 5px;
            border-radius: 4px;
        }
        """


def apply_workbench_theme(widget: QtWidgets.QWidget) -> None:
    widget.setStyleSheet(WORKBENCH_QSS)
