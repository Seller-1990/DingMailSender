from __future__ import annotations

import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import Environment, StrictUndefined
from markdown_it import MarkdownIt

from .model import CampaignConfig
from .recipients_excel import Recipient


@dataclass(frozen=True)
class InlineImage:
    cid: str
    mime_type: str
    filename: str
    data: bytes


def _jinja_env() -> Environment:
    return Environment(undefined=StrictUndefined, autoescape=False)


def read_body_template(campaign_dir: Path, cfg: CampaignConfig) -> str:
    path = (campaign_dir / cfg.body_template_file).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"未找到 Markdown 模板文件：{path}")
    return path.read_text(encoding="utf-8")


def render_subject_and_markdown(
    campaign_dir: Path, cfg: CampaignConfig, recipient: Recipient
) -> tuple[str, str]:
    env = _jinja_env()
    variables = dict(recipient.variables)
    variables["__row__"] = str(recipient.row_number)

    subject = env.from_string(cfg.subject_template).render(**variables).strip()
    body_md = env.from_string(read_body_template(campaign_dir, cfg)).render(**variables).strip()
    if not subject:
        raise ValueError(f"主题渲染结果为空（收件人：{recipient.email}）")
    if not body_md:
        raise ValueError(f"正文渲染结果为空（收件人：{recipient.email}）")
    return subject, body_md


def markdown_to_html(md_text: str) -> str:
    # "default" preset includes tables; keep HTML enabled for rich content.
    md = MarkdownIt("default", {"html": True})
    return md.render(md_text)


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
        if not src:
            continue
        if src.startswith(("cid:", "data:", "http://", "https://")):
            continue

        src_path = Path(src)
        resolved = (base_dir / src_path).resolve() if not src_path.is_absolute() else src_path.resolve()
        if base_dir not in resolved.parents and resolved != base_dir:
            raise ValueError(f"图片路径不允许越界：{src!r} -> {resolved}")
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
        if not src:
            continue
        if src.startswith(("cid:", "data:", "http://", "https://")):
            continue

        src_path = Path(src)
        resolved = (base_dir / src_path).resolve() if not src_path.is_absolute() else src_path.resolve()
        if base_dir not in resolved.parents and resolved != base_dir:
            continue
        if not resolved.is_file():
            continue
        img["src"] = resolved.as_uri()

    return str(soup)
