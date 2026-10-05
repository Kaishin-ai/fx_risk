# fx_risk

価格の不確実性を、意思決定できる確率に翻訳するシステム（開発中）。

## 何をするか / しないか

- **する**: 価格の振れ幅（リスク量）を測り、「N日後に◯◯を下回る確率は△%」の形で出す。
  過去に出した予測区間に実績が入ったかを毎日記録し、モデルの外れ具合を公開する。
- **しない**: 相場の予想、銘柄の選定・推奨、利益の最大化。本リポジトリの出力は投資助言ではない。

## 進捗

| Phase | 内容 | 状態 |
|---|---|---|
| 0 | USD/JPY の取得、日次対数収益率の分布とボラティリティの推移を可視化 | ✅ `phase0_explore.py` |
| 1 | PostgreSQL 化＋毎日1回の自動取得（GitHub Actions / Neon） | ✅ `fetch_daily.py`（稼働状況は [STATUS.md](STATUS.md)） |
| 2 | モンテカルロ、積立シミュレーション、Web画面、答え合わせ | — |

## データ

- USD/JPY 日次: [Frankfurter API](https://frankfurter.dev/)（欧州中央銀行の参照レート。市場の終値ではない。
  中央ヨーロッパ時間16時ごろ公表、土日・欧州の祝日は欠ける）

## 実行（Phase 0）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python phase0_explore.py
```
