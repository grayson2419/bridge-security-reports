import anthropic
import os
import json
import re
import requests
from datetime import datetime
from pathlib import Path


def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"Telegram notification failed: {e}")


def main() -> None:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    today = datetime.utcnow().strftime("%Y-%m-%d")
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    existing = {f.stem.lower() for f in reports_dir.glob("*.md")}

    system_prompt = (
        "You are a Web3 bridge security analyst. "
        "Be factual and cite sources. "
        "Always end your response with a JSON block containing structured incident data."
    )

    user_prompt = f"""Search for cross-chain bridge security incidents from the last 24 hours.

Run these 4 searches:
1. cross-chain bridge hack exploit drained stolen compromised 2026
2. 跨链桥 攻击 安全事件 漏洞 被盗 被黑 2026
3. bridge exploit drained site:x.com OR site:twitter.com
4. (PeckShield OR BlockSec OR Cyvers OR SlowMist OR CertiK) bridge alert hack 2026

Scope: ALL chains and ALL cross-chain infrastructure — Ethereum, BSC, Solana, Arbitrum, Optimism, Polygon, Avalanche, Base, zkSync, Starknet, Cosmos, Polkadot, Near, Aptos, Sui, TON, Tron, plus OFT adapters (LayerZero), messaging protocols (Wormhole, IBC, Hyperbridge, Axelar), etc.

Date policy: Include incidents with ANY recency signal (recent tweet, article published today/this week, "just happened", tweet IDs suggesting recency). Do NOT skip due to unconfirmed exact date.

Already-reported incidents to skip: {sorted(existing)}

For each NEW incident, write a bilingual (Chinese + English) report using this exact format:

# [项目名] 安全事件 | [Project] Security Incident

**日期|Date:** {today} | **链|Chain:** X | **损失|Loss:** $X | **等级|Severity:** Critical/High/Medium

## 概述 | Overview
[2-3句中文]
[2-3 sentences English]

## 攻击手法 | Attack Vector
- [步骤1 | Step 1]
- [步骤2 | Step 2]
- [步骤3 | Step 3]
**根因 | Root Cause:** [1句中英]

## 资金流向 | Fund Flow
[1-2句中英]

## 项目响应 | Response
[1-2句中英]

## 监控指标 | Monitoring Indicators
- [Indicator 1 + threshold]
- [Indicator 2 + threshold]
- [Indicator 3 + threshold]

## 关联项目 | Associated Projects
- **[Project 1]**: [相似漏洞 | similar vulnerability] — [建议 | recommendation]
- **[Project 2]**: [相似漏洞 | similar vulnerability] — [建议 | recommendation]

## 参考 | References
- [URL1]
- [URL2]

---

After all reports, output this JSON block (no incidents = empty array):
```json
[
  {{
    "filename": "{today}-ProjectName-AttackType.md",
    "project": "Project Name",
    "chain": "Chain Name",
    "loss": "$X,XXX,XXX",
    "severity": "Critical",
    "report_content": "...full markdown..."
  }}
]
```"""

    print("Searching for bridge security incidents...")

    messages = [{"role": "user", "content": user_prompt}]
    response = None

    for _ in range(5):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            system=system_prompt,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=messages,
        )
        if response.stop_reason != "pause_turn":
            break
        messages = [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": response.content},
        ]
        print("Continuing after pause_turn...")

    full_text = "".join(
        block.text for block in response.content if block.type == "text"
    )

    json_match = re.search(r"```json\s*(\[.*?\])\s*```", full_text, re.DOTALL)
    if not json_match:
        print("No JSON block found in response")
        return

    try:
        incidents = json.loads(json_match.group(1))
    except json.JSONDecodeError as e:
        print(f"JSON parse error: {e}")
        return

    if not incidents:
        print("No new incidents in the last 24 hours")
        return

    print(f"Found {len(incidents)} new incident(s)")
    new_reports = []

    for incident in incidents:
        filename = incident.get("filename", "").strip()
        content = incident.get("report_content", "").strip()
        if not filename or not content:
            continue

        filepath = reports_dir / filename
        if filepath.exists():
            print(f"Skipping {filename} — already exists")
            continue

        filepath.write_text(content, encoding="utf-8")
        new_reports.append(incident)
        print(f"Saved: {filename}")

    if new_reports and bot_token and chat_id:
        repo = "https://github.com/grayson2419/bridge-security-reports"
        for r in new_reports:
            msg = (
                f"🚨 <b>跨链桥安全事件</b>\n\n"
                f"📌 项目: {r.get('project', '?')}\n"
                f"⛓ 链: {r.get('chain', '?')}\n"
                f"💰 损失: {r.get('loss', '?')}\n"
                f"🔴 等级: {r.get('severity', '?')}\n\n"
                f"📄 报告: {repo}/blob/main/reports/{r['filename']}"
            )
            send_telegram(bot_token, chat_id, msg)
            print(f"Notified: {r.get('project')}")

    print(f"Done — {len(new_reports)} report(s) created")


if __name__ == "__main__":
    main()
