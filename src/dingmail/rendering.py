from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt


@dataclass(frozen=True)
class InlineImage:
    cid: str
    mime_type: str
    filename: str
    data: bytes


def markdown_to_html(md_text: str) -> str:
    md = MarkdownIt("default", {"html": False})
    return md.render(md_text)


def _is_external_image_source(src: str) -> bool:
    return src.startswith(("cid:", "data:", "http://", "https://"))


def _resolve_local_image(src: str, base_dir: Path) -> Path | None:
    value = str(src or "").strip()
    if not value or _is_external_image_source(value):
        return None

    source_path = Path(value)
    root = base_dir.resolve()
    resolved = (root / source_path).resolve() if not source_path.is_absolute() else source_path.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"图片路径不允许越界：{value!r} -> {resolved}")
    return resolved


def collect_local_image_errors(html: str, base_dir: Path) -> list[str]:
    errors: list[str] = []
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        try:
            resolved = _resolve_local_image(src, base_dir)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if resolved is None:
            continue
        if not resolved.is_file():
            errors.append(f"图片文件不存在：{resolved}")
            continue
        mime_type, _ = mimetypes.guess_type(resolved.name)
        if not mime_type or not mime_type.startswith("image/"):
            errors.append(f"不支持的图片类型：{resolved.name}（{mime_type}）")
    return errors


def wrap_email_html(body_html: str) -> str:
    return (
        "<!doctype html>"
        "<html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<style>"
        "body{font-family:Segoe UI,Arial,Helvetica,sans-serif;font-size:14px;line-height:1.6;color:#111;}"
        "table{border-collapse:collapse;}"
        "th,td{border:1px solid #ddd;padding:6px 8px;vertical-align:top;}"
        "</style></head><body>"
        f"{body_html}"
        "</body></html>"
    )


def embed_cid_images(html: str, base_dir: Path) -> tuple[str, list[InlineImage]]:
    soup = BeautifulSoup(html, "html.parser")
    images: list[InlineImage] = []

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        resolved = _resolve_local_image(src, base_dir)
        if resolved is None:
            continue
        if not resolved.is_file():
            raise FileNotFoundError(f"未找到图片文件：{resolved}")

        mime_type, _ = mimetypes.guess_type(resolved.name)
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError(f"不支持的图片类型：{resolved.name}（{mime_type}）")

        cid = f"{uuid.uuid4().hex}@dingmail"
        img["src"] = f"cid:{cid}"
        images.append(
            InlineImage(
                cid=cid,
                mime_type=mime_type,
                filename=resolved.name,
                data=resolved.read_bytes(),
            )
        )

    return str(soup), images


def rewrite_local_images_for_preview(html: str, base_dir: Path) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        try:
            resolved = _resolve_local_image(src, base_dir)
        except ValueError:
            continue
        if resolved is None:
            continue
        if not resolved.is_file():
            continue
        img["src"] = resolved.as_uri()

    return str(soup)
