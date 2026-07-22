"""Read-only single-leg shadow experiment report.

Examples::

    python scripts/analytics/single_leg_shadow_report.py \
        --user-id <uuid> --json-out report.json --markdown-out report.md

The script performs SELECTs only. Every table is fetched independently so an
absent/unreadable sink stays FAILED-FETCH rather than becoming a false zero.
Raw user IDs and row payloads are not emitted into the report artifacts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from packages.quantum.services.single_leg_shadow_reader import (
    read_single_leg_shadow_evidence,
)
from packages.quantum.supabase_env import get_sanitized_supabase_env


def redacted_report_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop row-level/private data while preserving section truth."""

    sections = payload.get("sections") or {}
    return {
        "epoch": payload.get("epoch"),
        "generated_at": payload.get("generated_at"),
        "summary": payload.get("summary") or {},
        "sections": {
            name: {
                "status": section.get("status"),
                "row_count": len(section.get("rows") or []),
                "error": section.get("error"),
            }
            for name, section in sorted(sections.items())
        },
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    headline = summary["headline"]
    epoch = summary["epoch"]
    policies = summary["policy_counts"]
    bindings = summary["binding_counts"]

    lines = [
        "# Single-Leg Shadow Experiment Evidence",
        "",
        f"- Generated at: `{payload['generated_at']}`",
        f"- Epoch: `{payload['epoch']}`",
        f"- Reader status: **{summary['status']}**",
        f"- Epoch state: `{epoch.get('state')}`",
        (
            f"- Routing / execution: `{epoch.get('routing_mode')}` / "
            "`internal_paper`"
        ),
        (
            f"- Max contracts / live submit: `{epoch.get('max_contracts')}` / "
            f"`{epoch.get('live_submit_allowed')}`"
        ),
        "",
        "## Headline",
        "",
        (
            "| runs | attempts | candidates | internal fills | open | closed | "
            "outcomes | realized P&L |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {headline['runs']} | {headline['attempts']} | "
            f"{headline['generated_candidates']} | "
            f"{headline['internal_fills']} | {headline['open_positions']} | "
            f"{headline['closed_positions']} | {headline['outcomes']} | "
            f"${headline['realized_pnl']:.2f} |"
        ),
        "",
        "## Policy and binding state",
        "",
        (
            f"- Policies: total={policies['total']}, "
            f"approved={policies['approved']}, draft={policies['draft']}, "
            f"opt-in={policies['opt_in']}"
        ),
        (
            "- Opt-in IDs: `"
            + (", ".join(policies["opt_in_policy_ids"]) or "<none>")
            + "`"
        ),
        (
            f"- Bindings: total={bindings['total']}, "
            f"experimental={bindings['experimental']}, "
            f"enabled={bindings['enabled']}"
        ),
        "",
        "## Attempts by stage",
        "",
        "| stage | count |",
        "|---|---:|",
    ]
    for row in summary["attempts_by_stage"]:
        lines.append(f"| {row['key']} | {row['count']} |")

    lines.extend(
        [
            "",
            "## Typed rejections",
            "",
            "| stage | reason | count |",
            "|---|---|---:|",
        ]
    )
    for row in summary["rejections"]:
        lines.append(
            f"| {row['stage']} | {row['reason_code']} | {row['count']} |"
        )

    lines.extend(
        [
            "",
            "## Policy arms",
            "",
            (
                "| policy | matched control | runs | attempts | candidates | "
                "fills | open | closed | outcomes | P&L |"
            ),
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for policy_id, row in summary["policies"].items():
        lines.append(
            f"| {policy_id} | {row.get('matched_control_family') or ''} | "
            f"{row['runs']} | {row['attempts']} | "
            f"{row['generated_candidates']} | {row['internal_fills']} | "
            f"{row['open_positions']} | {row['closed_positions']} | "
            f"{row['outcomes']} | ${row['realized_pnl']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Isolation checks",
            "",
            (
                "- Routing modes observed: "
                f"`{summary['isolation']['routing_modes']}`"
            ),
            (
                "- Execution modes observed: "
                f"`{summary['isolation']['execution_modes']}`"
            ),
            (
                "- live_submit_allowed=true rows: "
                f"**{summary['isolation']['live_submit_true_rows']}**"
            ),
            (
                "- non-one-contract orders: "
                f"**{summary['isolation']['non_one_contract_orders']}**"
            ),
            "",
            "## Section status",
            "",
            "| section | status |",
            "|---|---|",
        ]
    )
    for name, status in summary["section_status"].items():
        lines.append(f"| {name} | {status} |")
    if summary["failed_sections"]:
        lines.extend(
            [
                "",
                (
                    "**FAILED-FETCH sections:** `"
                    + ", ".join(summary["failed_sections"])
                    + "`"
                ),
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--json-out")
    parser.add_argument("--markdown-out")
    args = parser.parse_args()

    url, key = get_sanitized_supabase_env()
    if not url or not key:
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required"
        )
    from supabase import create_client

    client = create_client(url, key)
    raw_payload = read_single_leg_shadow_evidence(client, args.user_id)
    payload = redacted_report_payload(raw_payload)
    json_text = json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n"
    markdown = render_markdown(payload)

    if args.json_out:
        Path(args.json_out).write_text(json_text, encoding="utf-8")
    else:
        print(json_text, end="")
    if args.markdown_out:
        Path(args.markdown_out).write_text(markdown, encoding="utf-8")
    elif args.json_out:
        print(markdown)
    return 0 if payload["summary"]["status"] == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
