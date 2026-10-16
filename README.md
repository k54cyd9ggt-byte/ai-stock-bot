# AI Stock Paper Trader / AI株式仮想売買ボット

**Research / paper trading only. NO live broker orders.** 日本株・米国株の株価を用い、ランダムフォレストで翌日方向を推定し、仮想ポートフォリオを更新します。投資利益は保証されません。

## ローカル実行

Python 3.11以上をインストールして、このフォルダで実行します。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pytest -q
python bot.py backtest
python bot.py paper
```

バックテストは `output/backtest.csv`、仮想売買履歴は `state/paper.json` に出力します。GitHub Actionsでは平日23:30 UTCに仮想売買を実行し、状態ファイルをリポジトリへコミットします（スケジュールは遅延・スキップされる場合あり）。Actionsタブの `Daily AI Paper Trading` → `Run workflow` で手動実行できます。

## GitHubで公開

1. GitHubで新規リポジトリを作成（仮想資金の履歴を公開したくなければPrivate推奨）。
2. このフォルダの中身をリポジトリのルートへアップロード。`.github/workflows/paper.yml` も含める。
3. Settings → Actions → General → Workflow permissions で **Read and write permissions** を許可。
4. Actionsでワークフローを手動実行。`state/paper.json` が更新されることを確認。
5. バックテストはローカルで `python bot.py backtest` を実行。設定は `config.json` を編集。

## 重要な制約

- `yfinance` は研究用の非公式データ取得で、遅延・欠損・仕様変更があります。価格取得失敗時は実行を停止します。
- 米国株のリターンは**為替変動を反映しない**ため、JPY表示は仮想的な参考値です。税金、スプレッド、約定ずれ、配当課税は未反映。手数料は概算です。
- バックテストは共通取引日で比較し、現実の取引所ごとの注文時刻や祝日、流動性は再現しません。終値で判断して次の終値まで保有する理論モデルです。
- ペーパー運用は銘柄ごとの最新終値で日付がずれる場合があります。週末・休場・データ遅延時に更新されない銘柄があり、現実の売買成績と一致しません。
- モデルは過去データに学習しますが、過学習の可能性があります。銘柄は固定で、銘柄選択バイアスがあります。
- `max_drawdown` または `max_daily_loss` に到達すると**停止状態が継続**します。再開は手動審査の上で状態をリセットしてください。
- ワークフローのGit pushがブランチ保護などで拒否される場合は状態を保存できません。実行ログを確認してください。
- これは**完全自動の仮想売買**であり、実注文機能はありません。実売買には対応証券会社API、為替換算、注文執行管理、追加検証が必要です。
