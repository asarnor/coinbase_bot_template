#!/usr/bin/env python3
"""
Generate a daily trading report from the structured event journal.
"""
import argparse
import base64
import html
import json
import os
from collections import Counter
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Dict, List
from urllib import error, request
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from portfolio_utils import fetch_portfolio_snapshot, fetch_symbol_market_snapshot, load_exchange_from_env, summarize_holdings
from trading_journal import TradingJournal


def parse_symbol_list(raw_value: str) -> List[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def money(value) -> str:
    if value is None:
        return "N/A"
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:.2f}"
    return f"${value:.8f}"


def pct(value) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def parse_payload(raw_payload: str) -> Dict:
    if not raw_payload:
        return {}
    try:
        return json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}


def render_html_report(report_text: str) -> str:
    escaped = html.escape(report_text)
    return (
        "<html><body>"
        "<p>Your Coinbase bot daily report is attached below.</p>"
        f"<pre style=\"font-family: Menlo, Consolas, monospace; white-space: pre-wrap;\">{escaped}</pre>"
        "</body></html>"
    )


def build_email_subject(report_date: date) -> str:
    subject_prefix = os.getenv("REPORT_SUBJECT_PREFIX", "Coinbase Bot Daily Report")
    return f"{subject_prefix} - {report_date.isoformat()}"


def send_via_resend(
    subject: str,
    report_text: str,
    report_filename: str,
    recipient_emails: List[str],
) -> Dict:
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM_EMAIL")
    reply_to = os.getenv("REPORT_REPLY_TO")

    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not set")
    if not from_email:
        raise RuntimeError("RESEND_FROM_EMAIL is not set")
    if not recipient_emails:
        raise RuntimeError("No recipient emails configured")

    payload = {
        "from": from_email,
        "to": recipient_emails,
        "subject": subject,
        "text": report_text,
        "html": render_html_report(report_text),
        "attachments": [
            {
                "filename": report_filename,
                "content": base64.b64encode(report_text.encode("utf-8")).decode("utf-8"),
            }
        ],
    }
    if reply_to:
        payload["reply_to"] = [reply_to]

    req = request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "coinbase-bot-daily-report/1.0",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Resend API error {exc.code}: {message}") from exc


def resolve_report_date(args, local_zone: ZoneInfo) -> date:
    if args.date:
        return date.fromisoformat(args.date)
    if args.yesterday:
        return (datetime.now(local_zone) - timedelta(days=1)).date()
    return datetime.now(local_zone).date()


def build_report_markdown(
    report_date: date,
    timezone_name: str,
    start_iso: str,
    end_iso: str,
    events: List[Dict],
    current_snapshot: Dict,
    start_snapshot: Dict,
    end_snapshot: Dict,
    market_rows: List[Dict],
) -> str:
    effective_end_snapshot = end_snapshot or current_snapshot
    buys = [event for event in events if event["event_type"] == "entry_executed"]
    sells = [event for event in events if event["event_type"] == "exit_executed"]
    warnings = [event for event in events if event["event_type"] in {"warning", "runtime_error"}]

    blocked_counts = Counter()
    realized_pnl = 0.0
    entry_candidates = 0
    regime_changes = []

    for event in events:
        payload = parse_payload(event.get("payload_json"))
        if event["event_type"] == "signal_evaluation":
            if payload.get("entry_ready"):
                entry_candidates += 1
            for reason in payload.get("blocked_reasons", []):
                blocked_counts[reason] += 1
        elif event["event_type"] == "exit_executed":
            realized_pnl += payload.get("estimated_pnl_usd", 0.0) or 0.0
        elif event["event_type"] == "regime_changed":
            regime_value = payload.get("regime") or event.get("regime")
            if regime_value:
                regime_changes.append(str(regime_value))

    start_total = start_snapshot.get("total_estimated_usd") if start_snapshot else None
    end_total = effective_end_snapshot.get("total_estimated_usd") if effective_end_snapshot else None
    day_change = (end_total - start_total) if start_total is not None and end_total is not None else None

    lines = [
        f"# Daily Trading Report - {report_date.isoformat()}",
        "",
        f"- Timezone: `{timezone_name}`",
        f"- Window: `{start_iso}` to `{end_iso}`",
        "",
        "## Summary",
        f"- Current estimated account value: {money(current_snapshot.get('total_estimated_usd'))}",
        f"- Current free USD: {money(current_snapshot.get('free_usd'))}",
        f"- Estimated realized P/L from bot exits: {money(realized_pnl)}",
        f"- Entries executed: {len(buys)}",
        f"- Exits executed: {len(sells)}",
        f"- Entry-ready signals seen: {entry_candidates}",
    ]

    if day_change is not None:
        lines.append(f"- Snapshot-to-snapshot account change: {money(day_change)}")
    else:
        lines.append("- Snapshot-to-snapshot account change: N/A (need more snapshot history)")

    if regime_changes:
        lines.append(f"- Regime changes observed: {', '.join(regime_changes)}")

    lines.extend(
        [
            "",
            "## Current Account",
        ]
    )
    for holding in summarize_holdings(current_snapshot.get("positions", [])):
        lines.append(
            f"- {holding['currency']}: {holding['amount']:.8f}".rstrip("0").rstrip(".")
            + f" worth {money(holding['usd_value'])}"
        )

    lines.extend(
        [
            "",
            "## Transactions",
        ]
    )
    if not buys and not sells:
        lines.append("- No executed trades were recorded in this window.")
    else:
        for event in buys + sells:
            payload = parse_payload(event.get("payload_json"))
            lines.append(
                f"- {event['created_at']}: `{event['event_type']}` {event.get('symbol') or 'N/A'} "
                f"price={money(event.get('price'))} amount={event.get('amount') or 0:.6f} "
                f"reason={event.get('reason') or payload.get('reason') or 'N/A'}"
            )

    lines.extend(
        [
            "",
            "## Filter Pressure",
        ]
    )
    if blocked_counts:
        for reason, count in blocked_counts.most_common():
            lines.append(f"- {reason}: {count} blocked checks")
    else:
        lines.append("- No signal evaluation data recorded yet.")

    lines.extend(
        [
            "",
            "## Market Snapshot",
        ]
    )
    for row in market_rows:
        lines.append(
            f"- {row['symbol']}: {money(row['price'])} | 24h {pct(row['change_24h_pct'])} | 7d {pct(row['change_7d_pct'])}"
        )

    lines.extend(
        [
            "",
            "## Warnings",
        ]
    )
    if warnings:
        for event in warnings:
            payload = parse_payload(event.get("payload_json"))
            lines.append(
                f"- {event['created_at']}: {event.get('reason') or payload.get('message') or event['event_type']}"
            )
    else:
        lines.append("- No warnings or runtime errors were recorded in this window.")

    return "\n".join(lines) + "\n"


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Generate a daily trading report")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD format (defaults to local today)")
    parser.add_argument("--yesterday", action="store_true", help="Generate the report for the previous local day")
    parser.add_argument("--sandbox", action="store_true", help="Use sandbox credentials")
    parser.add_argument("--stdout", action="store_true", help="Print report to stdout even when writing file")
    parser.add_argument("--email", action="store_true", help="Send the report by email using Resend")
    parser.add_argument("--recipient", action="append", default=[], help="Override recipient email(s)")
    parser.add_argument("--output", help="Optional output path override")
    args = parser.parse_args()

    timezone_name = os.getenv("REPORT_TIMEZONE", os.getenv("TZ", "America/Los_Angeles"))
    local_zone = ZoneInfo(timezone_name)

    report_date = resolve_report_date(args, local_zone)

    start_local = datetime.combine(report_date, dt_time.min, tzinfo=local_zone)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    journal = TradingJournal.from_env()
    events = journal.get_events_between(start_utc.isoformat(), end_utc.isoformat())
    start_snapshot = journal.get_first_snapshot_after(start_utc.isoformat())
    end_snapshot = journal.get_latest_snapshot_before(end_utc.isoformat())

    exchange = load_exchange_from_env(use_sandbox=args.sandbox)
    current_snapshot = fetch_portfolio_snapshot(exchange)

    tracked_symbols = parse_symbol_list(
        os.getenv("TRADING_SYMBOLS", "ETH/USD,BTC/USD,LINK/USD,SHIB/USD,ALGO/USD,FET/USD")
    )
    market_rows = [fetch_symbol_market_snapshot(exchange, symbol) for symbol in tracked_symbols]

    report_text = build_report_markdown(
        report_date=report_date,
        timezone_name=timezone_name,
        start_iso=start_utc.isoformat(),
        end_iso=end_utc.isoformat(),
        events=events,
        current_snapshot=current_snapshot,
        start_snapshot=start_snapshot or {},
        end_snapshot=end_snapshot or {},
        market_rows=market_rows,
    )

    output_path = args.output or os.path.join("reports", f"daily_report_{report_date.isoformat()}.md")
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(report_text)

    print(f"Report written to {output_path}")

    if args.email:
        configured_recipients = parse_symbol_list(os.getenv("REPORT_RECIPIENT_EMAILS", ""))
        recipient_emails = args.recipient or configured_recipients
        subject = build_email_subject(report_date)
        response = send_via_resend(
            subject=subject,
            report_text=report_text,
            report_filename=os.path.basename(output_path),
            recipient_emails=recipient_emails,
        )
        print(
            f"Email sent via Resend to {', '.join(recipient_emails)} "
            f"(id: {response.get('id', 'N/A')})"
        )

    if args.stdout:
        print()
        print(report_text)


if __name__ == "__main__":
    main()
