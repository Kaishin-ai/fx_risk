"""
データベースにつながるかだけを確認する（接続文字列そのものは表示しない）

実行:  .venv/bin/python db_check.py
"""

import os
import time

import psycopg
from dotenv import load_dotenv

load_dotenv()  # 同じフォルダの .env を読み、中の DATABASE_URL=... を環境変数にする

url = os.environ.get("DATABASE_URL")
if not url:
    raise SystemExit(".env に DATABASE_URL がありません")

start = time.time()
# with を使うと、ブロックを抜けたとき自動で接続を閉じてくれる
with psycopg.connect(url, connect_timeout=30) as conn:
    version = conn.execute("SELECT version()").fetchone()[0]
    db, user = conn.execute("SELECT current_database(), current_user").fetchone()

print("接続OK")
print(f"  PostgreSQL : {version.split(',')[0]}")
print(f"  データベース: {db}")
print(f"  かかった時間: {time.time() - start:.1f}秒（休止中だった場合は起動に数秒かかる）")
