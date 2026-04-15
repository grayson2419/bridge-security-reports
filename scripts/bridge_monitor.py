import os
import json
import re
import requests
from datetime import datetime, timezone
from pathlib import Path

from ddgs import DDGS


def search_ddg(query: str, max_results: int = 5) -> list[dict]:
    try:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        print(f"Search failed for '{query}': {e}")
        return []


def call_groq(prompt: str, groq_api_key: str) -> str:
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {groq_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 8000,
            "temperature": 0.1,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


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
    groq_api_key = os.environ["GROQ_API_KEY"]
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)

    existing = {f.stem.lower() for f in reports_dir.glob("*.md")}

    # Search for bridge security incidents
    queries = [
        "cross-chain bridge hack exploit drained stolen 2026",
        "跨链桥 攻击 安全事件 漏洞 被盗 2026",
        "bridge exploit drained crypto security incident",
        "PeckShield OR BlockSec OR SlowMist bridge hack alert",
    ]

    print("Searching for bridge security incidents...")
    all_results = []
    for query in queries:
        results = search_ddg(query, max_results=5)
        for r in results:
            all_results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        print(f"Query '{query[:40]}...' → {len(results)} results")

    if not all_results:
        print("No search results found")
        return

    # Format results for analysis
    results_text = "\n\n".join(
        f"[{i+1}] {r['title']}\nURL: {r['url']}\n{r['snippet']}"
        for i, r in enumerate(all_results)
    )

    prompt = f"""You are a Web3 bridge security analyst. Today is {today}.

Analyze these search results and identify cross-chain bridge security incidents from the last 7 days.

SEARCH RESULTS:
{results_text}

ALREADY REPORTED (skip these): {sorted(existing)}

INSTRUCTIONS:
1. Identify NEW bridge/cross-chain security incidents (hacks, exploits, vulnerabilities). Include OFT adapters (LayerZero), messaging protocols (Wormhole, IBC, Hyperbridge, Axelar), etc.
2. Include incidents with any recency signal. Do NOT skip due to unconfirmed exact date.
3. For each NEW incident, write a bilingual Chinese+English report in this format:

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
- [URL from search results]

---

After all reports, output this JSON block (empty array [] if no new incidents):
```json
[
  {{
    "filename": "{today}-ProjectName-AttackType.md",
    "project": "Project Name",
    "chain": "Chain Name",
    "loss": "$X,XXX,XXX",
    "severity": "Critical",
    "report_content": "...full markdown report..."
  }}
]
```"""

    print("Analyzing with Groq...")
    full_text = call_groq(prompt, groq_api_key)
    print(f"Response received ({len(full_text)} chars)")

    json_match = re.search(r"```json\s*(\[.*?\])\s*```", full_text, re.DOTALL)
    if not json_match:
        print("No JSON block found in response")
        print(f"Preview: {full_text[:300]}")
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
