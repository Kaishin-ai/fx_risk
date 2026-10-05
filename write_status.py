"""
稼働状況を STATUS.md に書き出す

GitHub Actions から毎月1日に実行され、結果がリポジトリにコミットされる。目的は2つ。
  1. 稼働実績を誰でも見られる形で公開する
  2. 公開リポジトリは60日間コミットが無いと自動実行が止まるので、それを防ぐ

実行:  .venv/bin/python write_status.py   （DATABASE_URL が必要）
"""

import os
from datetime import datetime, timedelta, timezone

import psycopg
from dotenv import load_dotenv

JST = timezone(timedelta(hours=9))


def consecutive_days(days: list) -> int:
    """日付のリスト（新しい順）から、最新日から何日途切れずに続いているかを数える

    例: [10/7, 10/6, 10/5, 10/3] → 10/7, 10/6, 10/5 は連続、10/4 が抜けているので 3
    """
    count = 0
    expected = days[0] if days else None
    for d in days:
        if d != expected:
            break
        count += 1
        expected = d - timedelta(days=1)
    return count


def main() -> None:
    load_dotenv(".env")
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as conn:
        # 成功した実行があった「日」（日本時間）を新しい順に。1日に何回成功しても1日と数える
        success_days = [row[0] for row in conn.execute(
            "SELECT DISTINCT (started_at AT TIME ZONE 'Asia/Tokyo')::date AS d"
            " FROM fetch_runs WHERE status = 'success' ORDER BY d DESC"
        )]
        total, ok, ng = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE status = 'success'),"
            " count(*) FILTER (WHERE status = 'failed') FROM fetch_runs"
        ).fetchone()
        n_rates, first_rate, last_rate = conn.execute(
            "SELECT count(*), min(date), max(date) FROM fx_rates"
        ).fetchone()
        # 失敗した日だけ載せる。エラー文には接続先のホスト名などが入りうるので公開しない
        failed_days = [row[0] for row in conn.execute(
            "SELECT DISTINCT (started_at AT TIME ZONE 'Asia/Tokyo')::date AS d"
            " FROM fetch_runs WHERE status = 'failed' ORDER BY d DESC LIMIT 10"
        )]

    streak = consecutive_days(success_days)
    lines = [
        "# 稼働状況",
        "",
        f"毎日 7:00（日本時間）に GitHub Actions で為替レートを取得している。このファイルは毎月1日に自動更新される。",
        f"（最終更新: {datetime.now(JST):%Y-%m-%d %H:%M} JST）",
        "",
        "| 項目 | 値 |",
        "|---|---|",
        f"| 稼働開始日 | {success_days[-1] if success_days else '—'} |",
        f"| 最終成功日 | {success_days[0] if success_days else '—'} |",
        f"| 連続稼働日数 | {streak}日 |",
        f"| 稼働日数（累計） | {len(success_days)}日 |",
        f"| 実行回数 | {total}回（成功 {ok} / 失敗 {ng}） |",
        f"| 保存済みデータ | {n_rates:,}件（{first_rate} 〜 {last_rate}） |",
        "",
        "## 失敗した日（直近10件）",
        "",
        "\n".join(f"- {d}" for d in failed_days) if failed_days else "なし",
        "",
    ]
    with open("STATUS.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
