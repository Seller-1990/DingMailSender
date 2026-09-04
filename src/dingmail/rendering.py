from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

_MD_RENDERER = MarkdownIt("default", {"html": False})


@dataclass(frozen=True)
class InlineImage:
    cid: str
    mime_type: str
    filename: str
    data: bytes


def markdown_to_html(md_text: str) -> str:
    return _MD_RENDERER.render(md_text)


def _is_external_image_source(src: str) -> bool:
    return src.startswith(("cid:", "data:", "http://", "https://"))


def _decode_image_src(src: str) -> str:
    """markdown-it 会把中文/空格编码为 percent-encoding；解码回本地路径形式。

    file:// URI（预览回写后的 src）同样在此归一化。
    """
    value = str(src or "").strip()
    if value.lower().startswith("file://"):
        value = urlsplit(value).path
    return unquote(value)


def _resolve_local_image(src: str, base_dir: Path, *, containment_root: Path | None = None) -> Path | None:
    """解析正文图片路径：相对 markdown 所在目录，越界检查针对任务包根目录。

    base_dir 与 containment_root 分离；相对路径先按 markdown 所在目录解析，
    不存在时回退到任务包根（README 文档化的 `assets/pic.png` 写法），
    两种布局都支持；解析结果与越界判定始终以包根为界。
    """
    value = _decode_image_src(src)
    if not value or _is_external_image_source(value):
        return None

    source_path = Path(value)
    root = base_dir.resolve()
    check_root = (containment_root or base_dir).resolve()

    def _check(resolved: Path) -> Path:
        if check_root not in resolved.parents and resolved != check_root:
            raise ValueError(f"图片路径不允许越界：{value!r} -> {resolved}")
        return resolved

    if source_path.is_absolute():
        return _check(source_path.resolve())

    beside_markdown = _check((root / source_path).resolve())
    if beside_markdown.is_file():
        return beside_markdown
    if check_root != root:
        # markdown 同目录下没有该文件：按任务包根再解析一次（assets/ 布局）
        return _check((check_root / source_path).resolve())
    return beside_markdown


def inspect_local_images(
    html: str,
    base_dir: Path,
    *,
    containment_root: Path | None = None,
) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    errors: list[str] = []
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        try:
            resolved = _resolve_local_image(src, base_dir, containment_root=containment_root)
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
            continue
        paths.append(resolved)
    return paths, errors


def collect_local_image_errors(html: str, base_dir: Path) -> list[str]:
    return inspect_local_images(html, base_dir)[1]


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


def embed_cid_images(
    html: str,
    base_dir: Path,
    *,
    containment_root: Path | None = None,
) -> tuple[str, list[InlineImage]]:
    soup = BeautifulSoup(html, "html.parser")
    images: list[InlineImage] = []
    seen: dict[Path, str] = {}

    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        resolved = _resolve_local_image(src, base_dir, containment_root=containment_root)
        if resolved is None:
            continue
        if not resolved.is_file():
            raise FileNotFoundError(f"未找到图片文件：{resolved}")

        mime_type, _ = mimetypes.guess_type(resolved.name)
        if not mime_type or not mime_type.startswith("image/"):
            raise ValueError(f"不支持的图片类型：{resolved.name}（{mime_type}）")

        existing_cid = seen.get(resolved)
        if existing_cid is not None:
            img["src"] = f"cid:{existing_cid}"
            continue

        cid = f"{uuid.uuid4().hex}@dingmail"
        seen[resolved] = cid
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


def rewrite_local_images_for_preview(
    html: str,
    base_dir: Path,
    *,
    containment_root: Path | None = None,
) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        try:
            resolved = _resolve_local_image(src, base_dir, containment_root=containment_root)
        except ValueError:
            continue
        if resolved is None:
            continue
        if not resolved.is_file():
            continue
        img["src"] = resolved.as_uri()

    return str(soup)
