from __future__ import annotations

import logging
from pathlib import Path

from .config_io import load_campaign_config
from .email_builder import build_email_message, load_attachments
from .paths import campaigns_dir, detect_home_dir, ensure_layout
from .recipients_excel import Recipient, load_recipients
from .rendering import (
    embed_cid_images,
    markdown_to_html,
    render_subject_and_markdown,
    rewrite_local_images_for_preview,
    wrap_email_html,
)
from .run_store import RunPaths, append_manifest_row, create_run_paths, snapshot_file
from .smtp_sender import SmtpSession, rate_limit_sleep


def _ensure_campaign_under_home(campaign_dir: Path, home_dir: Path) -> None:
    campaign_dir = campaign_dir.resolve()
    allowed_root = campaigns_dir(home_dir).resolve()
    if allowed_root not in campaign_dir.parents and campaign_dir != allowed_root:
        raise ValueError(f"活动目录必须位于 {allowed_root} 下：当前为 {campaign_dir}")


def _safe_filename(text: str) -> str:
    out = []
    for c in text:
        if c.isalnum() or c in ("-", "_", "."):
            out.append(c)
        else:
            out.append("_")
    return "".join(out).strip("_") or "item"


def _check_recipient_domain(recipient: Recipient, allow_domains: list[str]) -> None:
    if not allow_domains:
        return
    domain = recipient.email.split("@")[-1].lower()
    allow = {d.lower().lstrip("@") for d in allow_domains if str(d).strip()}
    if domain not in allow:
        raise ValueError(f"收件人域名不在白名单：{recipient.email}（允许：{sorted(allow)}）")


def render_previews(*, campaign_dir: Path, home_dir: Path | None = None) -> tuple[RunPaths, list[Recipient]]:
    home = ensure_layout(home_dir or detect_home_dir())
    _ensure_campaign_under_home(campaign_dir, home)

    cfg, cfg_path = load_campaign_config(campaign_dir)
    if cfg_path is None:
        raise FileNotFoundError("未找到 campaign.yml，请先在活动目录中创建配置文件")

    recipients = load_recipients(campaign_dir, cfg.recipients)
    run_paths = create_run_paths(home_dir=home, campaign_dir=campaign_dir)

    snapshot_file(cfg_path, run_paths.run_dir, "campaign.yml")
    snapshot_file((campaign_dir / cfg.body_template_file).resolve(), run_paths.run_dir, "template.md")
    excel_path = (campaign_dir / cfg.recipients.file).resolve()
    snapshot_file(excel_path, run_paths.run_dir, "recipients.xlsx")

    attachments = load_attachments(campaign_dir, cfg.attachments)

    log_path = run_paths.logs_dir / "render.log"
    logger = logging.getLogger(f"dingmail.render.{run_paths.run_dir.name}")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.handlers = [handler]
    logger.propagate = False

    for idx, r in enumerate(recipients, start=1):
        try:
            _check_recipient_domain(r, cfg.allow_recipient_domains)

            subject, body_md = render_subject_and_markdown(campaign_dir, cfg, r)
            body_html = wrap_email_html(markdown_to_html(body_md))

            preview_html = rewrite_local_images_for_preview(body_html, campaign_dir)

            email_html, inline_images = embed_cid_images(body_html, campaign_dir)
            msg = build_email_message(
                from_email=cfg.from_email,
                to_email=[r.email],
                subject=subject,
                text_body=body_md,
                html_body=email_html,
                inline_images=inline_images,
                attachments=attachments,
            )

            base = f"{idx:03d}_{_safe_filename(r.email)}"
            (run_paths.previews_dir / f"{base}.preview.html").write_text(preview_html, encoding="utf-8")
            (run_paths.eml_dir / f"{base}.eml").write_bytes(msg.as_bytes())

            append_manifest_row(
                run_paths.manifest_csv,
                idx=idx,
                to_email=r.email,
                subject=subject,
                status="rendered",
                message_id=msg.get("Message-ID"),
                error=None,
            )
            logger.info("rendered idx=%s to=%s", idx, r.email)
        except Exception as e:
            append_manifest_row(
                run_paths.manifest_csv,
                idx=idx,
                to_email=r.email,
                subject="",
                status="render_error",
                message_id=None,
                error=str(e),
            )
            logger.exception("render_error idx=%s to=%s: %s", idx, r.email, e)

    return run_paths, recipients


def send_bulk(
    *,
    campaign_dir: Path,
    smtp_password: str,
    home_dir: Path | None = None,
    reuse_run_paths: RunPaths | None = None,
) -> RunPaths:
    home = ensure_layout(home_dir or detect_home_dir())
    _ensure_campaign_under_home(campaign_dir, home)

    cfg, cfg_path = load_campaign_config(campaign_dir)
    if cfg_path is None:
        raise FileNotFoundError("未找到 campaign.yml，请先在活动目录中创建配置文件")
    cfg.validate_for_send()

    recipients = load_recipients(campaign_dir, cfg.recipients)
    run_paths = reuse_run_paths or create_run_paths(home_dir=home, campaign_dir=campaign_dir)

    snapshot_file(cfg_path, run_paths.run_dir, "campaign.yml")
    snapshot_file((campaign_dir / cfg.body_template_file).resolve(), run_paths.run_dir, "template.md")
    excel_path = (campaign_dir / cfg.recipients.file).resolve()
    snapshot_file(excel_path, run_paths.run_dir, "recipients.xlsx")

    attachments = load_attachments(campaign_dir, cfg.attachments)

    log_path = run_paths.logs_dir / "send.log"
    logger = logging.getLogger(f"dingmail.send.{run_paths.run_dir.name}")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.handlers = [handler]
    logger.propagate = False

    with SmtpSession(cfg.smtp, smtp_password) as smtp:
        for idx, r in enumerate(recipients, start=1):
            try:
                _check_recipient_domain(r, cfg.allow_recipient_domains)

                subject, body_md = render_subject_and_markdown(campaign_dir, cfg, r)
                body_html = wrap_email_html(markdown_to_html(body_md))

                preview_html = rewrite_local_images_for_preview(body_html, campaign_dir)
                email_html, inline_images = embed_cid_images(body_html, campaign_dir)

                msg = build_email_message(
                    from_email=cfg.from_email,
                    to_email=[r.email],
                    subject=subject,
                    text_body=body_md,
                    html_body=email_html,
                    inline_images=inline_images,
                    attachments=attachments,
                )

                base = f"{idx:03d}_{_safe_filename(r.email)}"
                (run_paths.previews_dir / f"{base}.preview.html").write_text(preview_html, encoding="utf-8")
                (run_paths.eml_dir / f"{base}.eml").write_bytes(msg.as_bytes())

                result = smtp.send(msg)
                append_manifest_row(
                    run_paths.manifest_csv,
                    idx=idx,
                    to_email=r.email,
                    subject=subject,
                    status="sent",
                    message_id=result.message_id,
                    error=None,
                )
                logger.info("sent idx=%s to=%s", idx, r.email)
            except Exception as e:
                append_manifest_row(
                    run_paths.manifest_csv,
                    idx=idx,
                    to_email=r.email,
                    subject="",
                    status="send_error",
                    message_id=None,
                    error=str(e),
                )
                logger.exception("send_error idx=%s to=%s: %s", idx, r.email, e)
            finally:
                rate_limit_sleep(cfg.rate_limit_seconds)

    return run_paths
