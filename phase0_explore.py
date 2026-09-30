"""
Phase 0: USD/JPY の「振れ幅」を眺める

やること（これだけ。DBもWebもまだ使わない）
  1. Frankfurter API から USD/JPY の日次レートを全期間取得
  2. ローカルに CSV で保存
  3. 対数収益率を計算
  4. 図を描く … 左: 日次収益率のヒストグラム / 右: ボラティリティの推移

実行:  .venv/bin/python phase0_explore.py
出力:  data/usdjpy.csv, output/phase0.png
"""

from datetime import date
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
# api.frankfurter.app は 2026-09 時点で .dev/v1 へ 301 リダイレクトされるため、移転先を直接叩く
API_URL = "https://api.frankfurter.dev/v1/1999-01-01..{end}"
DATA_PATH = Path("data/usdjpy.csv")
FIG_PATH = Path("output/phase0.png")

TRADING_DAYS = 252          # 1年の営業日数。日次ボラを年率に直すのに使う（√252 倍）
WINDOWS = [20, 60]          # 移動標準偏差の窓。20営業日≒1ヶ月、60営業日≒3ヶ月

# 日本語フォント（mac標準）。見つからなければ sans-serif にフォールバック
# ※ "Hiragino Kaku Gothic Pro" は標準の太さ(400)を持たず findfont 警告が出るので候補に入れない
matplotlib.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]


# ---------------------------------------------------------------------------
# 1. 取得
# ---------------------------------------------------------------------------
def fetch_usdjpy() -> pd.Series:
    """1999年〜今日までの USD/JPY を取得し、日付をindexにした Series で返す"""
    url = API_URL.format(end=date.today().isoformat())
    # params で from/to を渡すと requests が ?from=USD&to=JPY を組み立ててくれる
    res = requests.get(url, params={"from": "USD", "to": "JPY"}, timeout=30)
    res.raise_for_status()  # 4xx/5xx なら例外にして止める（黙って空データで進まないため）

    # レスポンスの形: {"rates": {"1999-01-04": {"JPY": 113.44}, ...}}
    rates = res.json()["rates"]
    s = pd.Series({d: v["JPY"] for d, v in rates.items()}, name="usdjpy")
    s.index = pd.to_datetime(s.index)  # 文字列 → 日付型（並び替え・期間指定ができるように）
    s.index.name = "date"
    return s.sort_index()


# ---------------------------------------------------------------------------
# 2. 保存
# ---------------------------------------------------------------------------
def save(s: pd.Series) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    s.to_csv(DATA_PATH)
    print(f"保存: {DATA_PATH}  {len(s)}行  {s.index[0].date()} 〜 {s.index[-1].date()}")


# ---------------------------------------------------------------------------
# 3. 収益率とボラティリティ
# ---------------------------------------------------------------------------
def log_returns(price: pd.Series) -> pd.Series:
    """対数収益率 r_t = ln(P_t / P_{t-1})

    単純な変化率 (P_t - P_{t-1}) / P_{t-1} でなく対数を使う理由:
      - 足し算できる: 20日分の r を足すと「20日間の収益率」になる → 後のモンテカルロで日次を積み上げやすい
      - 上げと下げが対称: 100→110→100 が +9.53% と -9.53% で打ち消し合う
    """
    return np.log(price / price.shift(1)).dropna()  # shift(1) = 前日の値。初日は前日が無いので NaN → 落とす


def rolling_vol(r: pd.Series, window: int) -> pd.Series:
    """直近 window 日の標準偏差を、年率(%)に換算したもの

    日次の標準偏差 σ_day を √252 倍すると年率ボラになる。
    （日々の変動が独立なら、分散は日数に比例 → 標準偏差は √日数 に比例、という仮定）
    """
    return r.rolling(window).std() * np.sqrt(TRADING_DAYS) * 100


# ---------------------------------------------------------------------------
# 4. 描画
# ---------------------------------------------------------------------------
def plot(r: pd.Series) -> None:
    r_pct = r * 100  # 見やすさのため % 表記に
    mu, sigma = r_pct.mean(), r_pct.std()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # --- 左: 日次収益率のヒストグラム ---
    ax1.hist(r_pct, bins=200, density=True, color="#4C72B0", alpha=0.7, label="実績")
    # 比較用に「同じ平均・標準偏差の正規分布」を重ねる。
    # 実績の方が中心が尖り・裾が厚ければ、「正規分布で見積もると大きな変動を過小評価する」ということ
    x = np.linspace(r_pct.min(), r_pct.max(), 500)
    ax1.plot(x, np.exp(-((x - mu) ** 2) / (2 * sigma**2)) / (sigma * np.sqrt(2 * np.pi)),
             color="#DD8452", lw=2, label="正規分布（同じ平均・標準偏差）")
    ax1.set_xlim(-4, 4)
    ax1.set_title("USD/JPY 日次対数収益率の分布")
    ax1.set_xlabel("日次収益率 (%)")
    ax1.set_ylabel("密度")
    ax1.legend()

    # --- 右: ボラティリティの推移 ---
    for w in WINDOWS:
        ax2.plot(rolling_vol(r, w), lw=1, label=f"{w}営業日")
    ax2.axhline(sigma * np.sqrt(TRADING_DAYS), color="gray", ls="--", lw=1, label="全期間平均")
    ax2.set_title("ボラティリティの推移（移動標準偏差・年率換算）")
    ax2.set_ylabel("年率ボラティリティ (%)")
    ax2.legend()

    fig.tight_layout()
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_PATH, dpi=120)
    print(f"図: {FIG_PATH}")


def summarize(r: pd.Series) -> None:
    """数字でも確認する。図だけだと「なんとなく」で終わるので"""
    vol = rolling_vol(r, 20)
    print(f"日次標準偏差      : {r.std() * 100:.3f} %")
    print(f"年率ボラ（全期間）: {r.std() * np.sqrt(TRADING_DAYS) * 100:.1f} %")
    print(f"年率ボラ（直近20日）: {vol.iloc[-1]:.1f} %")
    print(f"尖度（正規分布なら0）: {r.kurt():.1f}")   # pandas の kurt は「超過尖度」。大きいほど裾が厚い
    print(f"歪度（正規分布なら0）: {r.skew():.2f}")   # マイナス = 大きく下げる日の方が極端
    # 裾の厚さを具体的に: 「4σを超える日」は正規分布なら約0.006%しか起きない
    n_tail = (r.abs() > 4 * r.std()).sum()
    print(f"4σ超えの日数       : {n_tail}日 / {len(r)}日（正規分布なら期待値 {len(r) * 6.3e-5:.1f}日）")


if __name__ == "__main__":
    price = fetch_usdjpy()
    save(price)
    r = log_returns(price)
    summarize(r)
    plot(r)
