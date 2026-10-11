#!/usr/bin/env python3
"""AI/Tech 趋势监控工具"""

import argparse
import os

from collectors import fetch_trending_repos, fetch_product_hunt_posts, fetch_hackernews_posts, fetch_ai_tools, fetch_chrome_extensions
from collectors import source_status
from collectors.adapters import fetch_all as fetch_adapter_signals
from collectors.adapters import fetch_browser_all as fetch_browser_signals
from collectors.adapters import reddit_api
from collectors.toolify import fetch_toolify_tools
from reporters import generate_markdown_report
from reporters.html_generator import generate_html_report
from analyzers.indie_analyzer import generate_indie_report
from analyzers.indie_html_generator import generate_indie_html
from senders import send_email_report
from storage import save_daily_data
from config import timeutil


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="AI/Tech 趋势监控工具")
    parser.add_argument("--no-email", action="store_true", help="跳过发送邮件")
    args = parser.parse_args()

    print("正在采集数据...")

    # 采集Product Hunt
    print("  - 抓取 Product Hunt...")
    product_hunt_data = fetch_product_hunt_posts(limit=5)
    print(f"    获取到 {len(product_hunt_data)} 个产品")

    # 采集Toolify Trending
    print("  - 抓取 Toolify Trending...")
    toolify_data = fetch_toolify_tools()
    print(f"    获取到 {len(toolify_data)} 个工具")

    # 采集There's An AI For That
    print("  - 抓取 There's An AI For That...")
    ai_tools_data = fetch_ai_tools(limit=5)
    print(f"    获取到 {len(ai_tools_data)} 个工具")

    # 采集Chrome Extensions
    print("  - 抓取 Chrome Extensions...")
    chrome_extensions_data = fetch_chrome_extensions(limit=5)
    print(f"    获取到 {len(chrome_extensions_data)} 个扩展")

    # 采集GitHub Trending
    print("  - 抓取 GitHub Trending...")
    github_trending_data = fetch_trending_repos(limit=5)
    print(f"    获取到 {len(github_trending_data)} 个项目")

    # 采集Hacker News
    print("  - 抓取 Hacker News...")
    hackernews_data = fetch_hackernews_posts(limit=5)
    print(f"    获取到 {len(hackernews_data)} 个热门")

    # 采集 Phase 6 信号适配器（失败不影响主流程）
    print("  - 采集机会信号适配器（GitHub 搜索 / HN 需求）...")
    try:
        adapter_signals, adapter_rows = fetch_adapter_signals(limit_per_source=15)
    except Exception as exc:               # 适配器绝不能中断日报
        adapter_signals, adapter_rows = [], []
        print(f"    ⚠️  适配器整体失败，已跳过: {type(exc).__name__}: {exc}")
    for row in adapter_rows:
        print(f"    {row['source']}: {row['items_fetched']} signal(s) [{row['status']}]")

    # Phase 6.1: 客户端渲染源（浏览器渲染，失败不影响主流程）
    print("  - 采集浏览器渲染源（TrustMRR / DevHunt / BetaList / Build or Skip）...")
    try:
        browser_signals, browser_rows = fetch_browser_signals(limit_per_source=10)
    except Exception as exc:
        browser_signals, browser_rows = [], []
        print(f"    ⚠️  浏览器采集整体失败，已跳过: {type(exc).__name__}: {exc}")
    for row in browser_rows:
        print(f"    {row['source']}: {row['items_fetched']} item(s) [{row['status']}] "
              f"{row.get('runtime_seconds', 0)}s")
    adapter_signals = adapter_signals + browser_signals
    adapter_rows = adapter_rows + browser_rows

    # Phase 7: Reddit 官方 API 需求信号（未配置凭证则跳过）
    print("  - 采集 Reddit 需求信号（官方 API）...")
    try:
        reddit_signals, reddit_health = reddit_api.fetch()
    except Exception as exc:
        reddit_signals = []
        reddit_health = {"source": "reddit", "status": "API_ERROR", "auth_status": "UNKNOWN",
                         "requests_made": 0, "posts_fetched": 0, "posts_accepted": 0,
                         "comments_fetched": 0, "last_error": f"{type(exc).__name__}: {exc}",
                         "runtime_seconds": 0.0, "render_mode": "PUBLIC_JSON",
                         "signal_types": []}
    print(f"    reddit: {len(reddit_signals)} signal(s) [{reddit_health.get('status')}]")
    adapter_signals = adapter_signals + reddit_signals
    adapter_rows = adapter_rows + [reddit_health]

    # 生成报告
    print("正在生成报告...")
    report = generate_markdown_report(
        github_trending_data,
        product_hunt_data,
        hackernews_data,
        ai_tools_data,
        chrome_extensions_data,
        toolify_data,
    )

    # 写入文件
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report)

    print("✅ 报告已生成：report.md")

    # 生成HTML报告
    html_report = generate_html_report(
        product_hunt_data,
        toolify_data,
        ai_tools_data,
        chrome_extensions_data,
        github_trending_data,
        hackernews_data,
    )
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_report)

    print("✅ HTML report saved to docs/index.html")

    # 存储每日数据
    print("正在存储数据...")
    today = timeutil.today_str()
    daily_data = {
        "product_hunt": product_hunt_data,
        "toolify": toolify_data.get("new", []) + toolify_data.get("trending", []),
        "ai_tools": ai_tools_data,
        "chrome_extensions": chrome_extensions_data,
        "github_trending": github_trending_data,
        "hacker_news": hackernews_data,
    }
    if save_daily_data(today, daily_data):
        print(f"✅ 数据已存储：data/daily/{today}.json")
    else:
        print("⚠️  数据存储失败，继续执行...")

    # 生成 Indie Hacker 机会分析报告
    print("正在生成 Indie 分析报告...")
    indie_report = generate_indie_report(
        product_hunt_data,
        toolify_data,
        ai_tools_data,
        chrome_extensions_data,
        github_trending_data,
        hackernews_data,
        record_verdicts=True,
        source_errors=source_status(),
        signals=adapter_signals,
        adapter_rows=adapter_rows,
        reddit_health=reddit_health,
    )
    os.makedirs("analysis/daily", exist_ok=True)
    indie_path = f"analysis/daily/{today}-indie.md"
    with open(indie_path, "w", encoding="utf-8") as f:
        f.write(indie_report)
    print(f"✅ Indie analysis saved to {indie_path}")

    # 生成 Indie HTML 报告
    indie_product_data = {
        "product_hunt": product_hunt_data,
        "toolify": toolify_data,
        "ai_tools": ai_tools_data,
        "chrome_extensions": chrome_extensions_data,
        "github": github_trending_data,
        "hackernews": hackernews_data,
    }
    indie_html = generate_indie_html(indie_report, indie_product_data)
    with open("docs/indie.html", "w", encoding="utf-8") as f:
        f.write(indie_html)
    print("✅ Indie HTML saved to docs/indie.html")

    # 发送邮件
    if not args.no_email:
        print("正在发送邮件...")
        sent = False
        try:
            sent = send_email_report(report)
        except Exception as exc:  # 邮件是可选功能，绝不能中断日报流程
            print(f"⚠️  邮件发送异常，已跳过: {type(exc).__name__}: {exc}")
        if sent:
            print("✅ 邮件发送成功")
    else:
        print("⏭️  跳过邮件发送")


if __name__ == "__main__":
    main()
