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


def _read_campaign_config(config_path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("campaign.yml 顶层必须是 dict")
    return raw


def _dict_section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    section = raw.get(key) or {}
    if not isinstance(section, dict):
        raise ValueError(f"{key} 必须是 dict")
    return section


def _load_smtp_config(raw: dict[str, Any]) -> SmtpConfig:
    default_smtp = SmtpConfig()
    smtp_raw = _dict_section(raw, "smtp")
    return SmtpConfig(
        host=str(smtp_raw.get("host") or default_smtp.host),
        port=int(smtp_raw.get("port") or default_smtp.port),
        security=str(smtp_raw.get("security") or default_smtp.security).strip().lower(),  # type: ignore[arg-type]
        username=str(smtp_raw.get("username") or default_smtp.username),
    )


def _load_recipients_config(raw: dict[str, Any]) -> RecipientsConfig:
    default_recipients = RecipientsConfig()
    recipients_raw = _dict_section(raw, "recipients")
    columns = recipients_raw.get("columns") or default_recipients.columns
    if not isinstance(columns, dict):
        raise ValueError("recipients.columns 必须是 dict")
    normalized_columns = {str(k): str(v) for k, v in columns.items() if v is not None}
    return RecipientsConfig(
        file=str(recipients_raw.get("file") or default_recipients.file),
        sheet=recipients_raw.get("sheet") if recipients_raw.get("sheet") not in ("", None) else None,
        header_row=int(recipients_raw.get("header_row") or default_recipients.header_row),
        columns=normalized_columns,
    )


def _string_list(raw: dict[str, Any], key: str) -> list[str]:
    values = raw.get(key) or []
    if not isinstance(values, list):
        raise ValueError(f"{key} 必须是 list")
    return [str(value) for value in values if value is not None]


def load_campaign_config(campaign_dir: Path) -> tuple[CampaignConfig, Path | None]:
    config_path = find_campaign_config_file(campaign_dir)
    if not config_path:
        return CampaignConfig(), None

    raw = _read_campaign_config(config_path)
    default_campaign = CampaignConfig()
    rate_limit_raw = raw.get("rate_limit_seconds")
    rate_limit_seconds = float(default_campaign.rate_limit_seconds) if rate_limit_raw is None else float(rate_limit_raw)

    cfg = CampaignConfig(
        from_email=str(raw.get("from_email") or default_campaign.from_email),
        subject_template=str(raw.get("subject_template") or default_campaign.subject_template),
        body_template_file=str(raw.get("body_template_file") or default_campaign.body_template_file),
        assets_dir=str(raw.get("assets_dir") or default_campaign.assets_dir),
        attachments=_string_list(raw, "attachments"),
        allow_recipient_domains=_string_list(raw, "allow_recipient_domains"),
        rate_limit_seconds=rate_limit_seconds,
        recipients=_load_recipients_config(raw),
        smtp=_load_smtp_config(raw),
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
