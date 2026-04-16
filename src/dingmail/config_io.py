from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .model import CampaignConfig, RecipientsConfig, SmtpConfig

DEFAULT_CONFIG_FILENAMES = ("campaign.yml", "campaign.yaml")


def find_campaign_config_file(campaign_dir: Path) -> Path | None:
    for name in DEFAULT_CONFIG_FILENAMES:
        candidate = campaign_dir / name
        if candidate.is_file():
            return candidate
    return None


def load_campaign_config(campaign_dir: Path) -> tuple[CampaignConfig, Path | None]:
    config_path = find_campaign_config_file(campaign_dir)
    if not config_path:
        cfg = CampaignConfig()
        return cfg, None

    default_smtp = SmtpConfig()
    default_recipients = RecipientsConfig()
    default_campaign = CampaignConfig()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("campaign.yml 顶层必须是 dict")

    smtp_raw = raw.get("smtp") or {}
    recipients_raw = raw.get("recipients") or {}

    smtp = SmtpConfig(
        host=str(smtp_raw.get("host") or default_smtp.host),
        port=int(smtp_raw.get("port") or default_smtp.port),
        security=str(smtp_raw.get("security") or default_smtp.security).strip().lower(),  # type: ignore[arg-type]
        username=str(smtp_raw.get("username") or default_smtp.username),
    )

    columns = recipients_raw.get("columns") or default_recipients.columns
    if not isinstance(columns, dict):
        raise ValueError("recipients.columns 必须是 dict")
    columns = {str(k): str(v) for k, v in columns.items() if v is not None}

    recipients = RecipientsConfig(
        file=str(recipients_raw.get("file") or default_recipients.file),
        sheet=recipients_raw.get("sheet") if recipients_raw.get("sheet") not in ("", None) else None,
        header_row=int(recipients_raw.get("header_row") or default_recipients.header_row),
        columns=columns,
    )

    attachments = raw.get("attachments") or []
    if not isinstance(attachments, list):
        raise ValueError("attachments 必须是 list")

    allow_domains = raw.get("allow_recipient_domains") or []
    if not isinstance(allow_domains, list):
        raise ValueError("allow_recipient_domains 必须是 list")

    rate_limit_raw = raw.get("rate_limit_seconds")
    rate_limit_seconds = float(default_campaign.rate_limit_seconds) if rate_limit_raw is None else float(rate_limit_raw)

    cfg = CampaignConfig(
        from_email=str(raw.get("from_email") or default_campaign.from_email),
        subject_template=str(raw.get("subject_template") or default_campaign.subject_template),
        body_template_file=str(raw.get("body_template_file") or default_campaign.body_template_file),
        assets_dir=str(raw.get("assets_dir") or default_campaign.assets_dir),
        attachments=[str(x) for x in attachments if x is not None],
        allow_recipient_domains=[str(x) for x in allow_domains if x is not None],
        rate_limit_seconds=rate_limit_seconds,
        recipients=recipients,
        smtp=smtp,
    )
    cfg.validate()
    return cfg, config_path


def _dict_without_nones(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _dict_without_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_dict_without_nones(x) for x in obj]
    return obj


def campaign_config_to_dict(cfg: CampaignConfig) -> dict[str, Any]:
    data = asdict(cfg)
    return _dict_without_nones(data)


def save_campaign_config(campaign_dir: Path, cfg: CampaignConfig, path: Path | None = None) -> Path:
    cfg.validate()
    out_path = path or (campaign_dir / "campaign.yml")
    data = campaign_config_to_dict(cfg)
    out_path.write_text(
        yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    return out_path
