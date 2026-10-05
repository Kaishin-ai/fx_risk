"""
Phase 1: USD/JPY を取得してデータベース（PostgreSQL / Neon）に貯める

毎日1回 GitHub Actions から実行される想定。初回も2回目以降も同じスクリプトで動く。
  - DBが空（初回）       → 1999年から全期間を取得 ＝ 過去データの投入
  - DBにデータがある     → 最新日の翌日から今日までを取得 ＝ 毎日の更新
実行するたびに、結果（成功/失敗・何件入れたか）を fetch_runs 表に記録する。

実行:
  .venv/bin/python fetch_daily.py            # 本番（DATABASE_URL が必要）
  .venv/bin/python fetch_daily.py --dry-run  # DBに触らず、取得部分だけ試す
"""

import os
import sys
from datetime import date, timedelta

import psycopg
import requests
from dotenv import load_dotenv

API_URL = "https://api.frankfurter.dev/v1/{start}..{end}"
PAIR = "USDJPY"
FIRST_DATE = date(1999, 1, 1)  # Frankfurter（欧州中央銀行のデータ）が持っている最初の年


# ---------------------------------------------------------------------------
# 表の定義
# ---------------------------------------------------------------------------
# IF NOT EXISTS: すでに表があれば何もしない。毎回実行しても安全
CREATE_FX_RATES = """
CREATE TABLE IF NOT EXISTS fx_rates (
    pair       TEXT          NOT NULL,              -- 'USDJPY'。後で他の通貨を足せるように列にしておく
    date       DATE          NOT NULL,
    rate       NUMERIC(12,4) NOT NULL,              -- NUMERIC = 小数を誤差なく持つ型（お金・レート向き）
    fetched_at TIMESTAMPTZ   NOT NULL DEFAULT now(),-- いつ取得したか（入れた瞬間の時刻が自動で入る）
    PRIMARY KEY (pair, date)                        -- 同じ通貨・同じ日付は1行だけ ＝ 重複をDBが防ぐ
)
"""

CREATE_FETCH_RUNS = """
CREATE TABLE IF NOT EXISTS fetch_runs (
    id            SERIAL      PRIMARY KEY,          -- 1, 2, 3, ... と自動で振られる番号
    started_at    TIMESTAMPTZ NOT NULL,
    finished_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status        TEXT        NOT NULL,             -- 'success' または 'failed'
    rows_inserted INTEGER,                          -- 今回新しく入った行数（週末は0が正常）
    latest_date   DATE,                             -- 実行後、DBにある最新の日付
    error         TEXT                              -- 失敗したときのエラー内容
)
"""


# ---------------------------------------------------------------------------
# 取得
# ---------------------------------------------------------------------------
def fetch_rates(start: date, end: date) -> list[tuple[date, float]]:
    """start〜end の USD/JPY を [(日付, レート), ...] で返す"""
    url = API_URL.format(start=start.isoformat(), end=end.isoformat())
    res = requests.get(url, params={"from": "USD", "to": "JPY"}, timeout=30)
    res.raise_for_status()
    rates = res.json()["rates"]
    # 注意: 範囲内に新しいデータが無い（週末など）と、APIは直近の営業日の1件を返してくる。
    #       それはDBに入っている日付なので、保存時に重複として無視される
    return sorted((date.fromisoformat(d), v["JPY"]) for d, v in rates.items())


# ---------------------------------------------------------------------------
# DB操作
# ---------------------------------------------------------------------------
def latest_date(conn) -> date | None:
    """DBに入っている最新の日付。空なら None"""
    return conn.execute("SELECT max(date) FROM fx_rates WHERE pair = %s", (PAIR,)).fetchone()[0]


def save_rates(conn, rows: list[tuple[date, float]]) -> int:
    """rows を保存し、新しく入った行数を返す"""
    before = conn.execute("SELECT count(*) FROM fx_rates WHERE pair = %s", (PAIR,)).fetchone()[0]
    with conn.cursor() as cur:
        # %s はプレースホルダ。値を文字列で埋め込まず psycopg に渡すことで、SQLインジェクションを防ぐ
        # ON CONFLICT DO NOTHING: 同じ (pair, date) がすでにあればエラーにせず飛ばす
        cur.executemany(
            "INSERT INTO fx_rates (pair, date, rate) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            [(PAIR, d, r) for d, r in rows],
        )
    after = conn.execute("SELECT count(*) FROM fx_rates WHERE pair = %s", (PAIR,)).fetchone()[0]
    return after - before


def record_run(url: str, started_at, status: str, rows: int | None, latest: date | None, error: str | None):
    """実行結果を fetch_runs に1行記録する

    本体とは別の接続を使う。本体が失敗してやり直し（ロールバック）になっても、
    「失敗した」という記録だけは残したいから。
    """
    with psycopg.connect(url, connect_timeout=30) as conn:
        conn.execute(
            "INSERT INTO fetch_runs (started_at, status, rows_inserted, latest_date, error)"
            " VALUES (%s, %s, %s, %s, %s)",
            (started_at, status, rows, latest, error),
        )


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------
def main() -> None:
    today = date.today()

    # --dry-run: DBに触らず、取得がうまくいくかだけ確かめる（直近7日分）
    if "--dry-run" in sys.argv:
        rows = fetch_rates(today - timedelta(days=7), today)
        for d, r in rows:
            print(d, r)
        print(f"取得 {len(rows)}件（DBには保存していない）")
        return

    load_dotenv(".env")  # 手元では .env から読む。GitHub Actions では環境変数が直接渡される
    url = os.environ["DATABASE_URL"]

    with psycopg.connect(url, connect_timeout=30) as conn:
        started_at = conn.execute("SELECT now()").fetchone()[0]  # DBの時計で開始時刻を取る
        try:
            # with conn.transaction(): このブロックの中は「全部成功」か「全部なかったこと」のどちらか
            with conn.transaction():
                conn.execute(CREATE_FX_RATES)
                conn.execute(CREATE_FETCH_RUNS)

                last = latest_date(conn)
                start = FIRST_DATE if last is None else last + timedelta(days=1)

                if start > today:
                    # 今日の分まで入っている。未来の日付を聞くとAPIがエラーを返すので、聞かない
                    inserted = 0
                else:
                    rows = fetch_rates(start, today)
                    inserted = save_rates(conn, rows)

                new_latest = latest_date(conn)
        except Exception as e:
            try:
                record_run(url, started_at, "failed", None, None, f"{type(e).__name__}: {e}")
            except Exception:
                pass  # 記録すら失敗したら諦める。下の raise で元のエラーを優先して見せる
            raise  # エラーを握りつぶさない → GitHub Actions 上で「失敗（赤）」として見える

    record_run(url, started_at, "success", inserted, new_latest, None)
    print(f"成功: {inserted}件追加 / DBの最新日 {new_latest}（取得開始日 {start}）")


if __name__ == "__main__":
    main()
