# Stock Bottom Watch

日本株のウォッチリストをCSVで管理し、日足データから `DANGER` / `WAIT` / `BUY_CANDIDATE` / `MOMENTUM` / `OVERHEATED` / `NO_SIGNAL` をルール判定してDiscordに通知するアプリケーションです。AI予測やWebアプリ化はまだ行わず、まず3営業日Discord通知を観察して、誤判定と通知ノイズを調整する方針です。

## できること

- `watchlist.csv` の日本株tickerを yfinance 形式で管理します。
- 移動平均、RSI、出来高倍率、52週安値、年初来安値、20日安値、60日安値、52週高値からの下落率を計算します。
- どの安値に近いかを `判定安値` と `最寄り安値` として表示します。
- `DANGER` / `WAIT` / `BUY_CANDIDATE` は必ず通知します。
- `MOMENTUM` / `OVERHEATED` は `config.yaml` の設定で表示を切り替えます。
- `NO_SIGNAL` は原則表示せず、主要シグナルから解除された場合だけ表示します。
- 前回ステータスを `data/state.json` に保存し、ステータス変化を `NEW` / `CHANGED` で強調します。

## セットアップ

```powershell
cd stock-bottom-watch
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` にDiscord Webhook URLを入れます。

```env
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Webhook URLが空の場合はDiscord送信せず、標準出力にレポートを表示します。

## watchlist.csv

```csv
ticker,name,theme,avg_price,memo
9503.T,関西電力,電力・原子力,,
7011.T,三菱重工,重工・原子力・防衛,4000,
```

- `ticker`: yfinance形式です。日本株は `9503.T` のように `.T` を付けます。
- `name`: 通知に表示する銘柄名です。
- `theme`: 電力、半導体、防衛などのテーマです。
- `avg_price`: 任意の平均取得単価です。今のMVPでは保持のみです。
- `memo`: 任意メモです。

## ローカル手動実行

通常実行して、Webhook URLがあればDiscordへ送信します。

```powershell
.\scripts\run_now.ps1
```

Discord送信せずに内容だけ確認します。`--dry-run` では `data/state.json` を更新しません。

```powershell
.\scripts\dry_run.ps1
```

直接Pythonで実行する場合は以下です。

```powershell
python src/main.py
python src/main.py --dry-run
python src/main.py --reset-state
```

`--reset-state` は `data/state.json` を削除してから通常実行し、初回扱いに戻します。

## 設定

`config.yaml` で判定しきい値と表示対象を変更できます。

```yaml
lookback_days: 260
near_low_threshold: 0.03
rsi_oversold: 30
rsi_recover: 35
volume_spike_multiplier: 2.0
ma_short: 25
ma_mid: 75
ma_long: 200
max_discord_items: 10
show_momentum: false
show_overheated: false
ma25_overheat_threshold: 0.08
fetch_batch_size: 100
fetch_threads: true
use_history_cache: true
history_cache_dir: data/history
discord_report_mode: buy_candidates_summary
```

`fetch_batch_size` と `fetch_threads` は yfinance のまとめ取り設定です。`use_history_cache: true` の場合、取得した日足は `history_cache_dir` にCSVで保存され、次回以降はキャッシュへ直近分をマージして使います。
`discord_report_mode: buy_candidates_summary` では、通常通知を `BUY_CANDIDATE` の銘柄名一覧に絞ります。`BUY_CANDIDATE` は買い指示ではなく、底値圏に来たため深掘り候補に入れるシグナルです。詳細版に戻す場合は `full` を指定します。

## ステータス変化

通常実行後、各銘柄の判定ステータスを `data/state.json` に保存します。次回実行時に `previous_status` と現在ステータスを比較し、変化した銘柄をDiscord本文で強調します。

- `UNTRACKED → DANGER`: `NEW` / 表示は `未記録 → DANGER`
- `UNTRACKED → WAIT`: `NEW` / 表示は `未記録 → WAIT`
- `UNTRACKED → BUY_CANDIDATE`: `NEW`
- `NO_SIGNAL → DANGER`: `NEW`
- `NO_SIGNAL → WAIT`: `NEW`
- `WAIT → BUY_CANDIDATE`: `CHANGED` / 反転候補として強調
- `MOMENTUM → DANGER`: `CHANGED` / トレンド崩れ警戒
- `DANGER → WAIT`: `CHANGED` / 下落加速が一服

`state.json` に前回データがない銘柄は `previous_status: UNTRACKED` として扱います。既存銘柄が前回 `NO_SIGNAL` だった場合だけ `NO_SIGNAL → DANGER` のように表示します。`UNTRACKED → NO_SIGNAL` は表示しません。

前回 `DANGER` / `WAIT` / `BUY_CANDIDATE` だった銘柄が `NO_SIGNAL` になった場合は `CHANGED / 解除` として表示します。

## GitHub Actions 毎日自動通知

[daily.yml](.github/workflows/daily.yml) は平日15:45 JST相当で自動実行します。cronはUTCなので `45 6 * * MON-FRI` です。GitHub側の混雑により開始は遅れることがあります。

GitHub Actionsでは `data/state.json` と `data/history/` を `actions/cache/restore@v5` と `actions/cache/save@v5` で保持します。cache keyは `stock-state-${{ runner.os }}-${{ github.run_id }}` で、`github.run_id` を含むユニークkeyです。`restore-keys` は `stock-state-` プレフィックスで最新のstate/cacheを復元します。

復旧確認では、ログと実行Summaryにcacheの復元key、stateの銘柄数・更新日時、日足CSV数、必要なSecretの有無を表示します。`dry_run` は通知・state/history更新・cache保存を行わず、実行前後のファイルハッシュでも保存状態の不変を確認します。`daily.yml` をmainへ更新したときも自動的にdry_runで検証します。

GitHubのcacheは7日間アクセスがないと削除されます。長期停止後にcacheがない場合、過去のステータスは復元できません。日足は再取得でき、次の通常実行成功後に新しいstate/cacheを保存します。初回は各銘柄を未記録として扱います。

公開リポジトリの定期実行は60日間リポジトリ活動がないと自動停止します。再発時はActions画面でEnable workflowを押すか、書き込み権限のあるユーザーがcronを編集してください。

### GitHub Secrets

Discordへ通知するには、GitHub repositoryのSecretsに `DISCORD_WEBHOOK_URL` を登録します。定期・通常手動実行では、このSecretが空なら送信前に失敗させます。dry_runでは未設定を警告し、送信せず内容を確認できます。毎日通知にSlash command用のSecretsは不要です。

1. GitHub repositoryを開く
2. `Settings` → `Secrets and variables` → `Actions`
3. `New repository secret`
4. Name: `DISCORD_WEBHOOK_URL`
5. Value: Discord Webhook URL

### GitHub Actions から手動実行

1. GitHub repositoryの `Actions` タブを開く
2. `Daily Stock Bottom Watch` を選ぶ
3. `Run workflow` を押す
4. 必要に応じてinputを選ぶ

Inputs:

- `dry_run: true`: `python src/main.py --dry-run` を実行します。Discord送信せず、stateも更新しません。
- `reset_state: true`: `python src/main.py --reset-state` を実行します。stateを削除してから通常実行します。

`dry_run` と `reset_state` は同時に `true` にしないでください。同時指定時はWorkflowを失敗させます。

## Discord送信

- Webhook URLがない場合は標準出力に表示します。
- Webhook URLがある場合はDiscordへ送信します。
- 長文は1900文字以内のchunkに分割して送信します。
- DiscordがHTTP 4xx/5xxを返した場合は、HTTPステータスコードとレスポンス本文をログに出して失敗させます。

## Discord Slash Command

Webhook通知とSlash commandは役割が違います。

- 毎日自動通知: GitHub Actionsから `DISCORD_WEBHOOK_URL` へ投稿します。
- 欲しいときの手動確認: Discordで `/stockwatch` を実行し、FastAPIのInteractions Endpointがその場で応答します。

Slash commandは常時起動Botではなく、Discord InteractionsのHTTPエンドポイントとして実装しています。エンドポイントは [bot_server.py](src/bot_server.py) の `/interactions` です。

### ローカル起動

```powershell
uvicorn src.bot_server:app --host 0.0.0.0 --port 8000
```

DiscordからローカルPCへ直接アクセスはできないため、開発時はngrokなどで公開URLを作ります。

```powershell
ngrok http 8000
```

Discord Developer Portalで対象Applicationを開き、`Interactions Endpoint URL` に以下のように設定します。

```text
https://your-ngrok-domain.ngrok-free.app/interactions
```

### 必要な環境変数

`.env` またはホスティング環境のSecretsに以下を設定します。

```env
DISCORD_WEBHOOK_URL=
DISCORD_PUBLIC_KEY=
DISCORD_APPLICATION_ID=
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
```

- `DISCORD_PUBLIC_KEY`: Interactions署名検証に使います。
- `DISCORD_APPLICATION_ID`: slash command登録に使います。
- `DISCORD_BOT_TOKEN`: slash command登録に使います。
- `DISCORD_GUILD_ID`: 開発用Guild Command登録に使います。

Bot TokenやWebhook URLは絶対にGitHubへコミットしないでください。

### コマンド登録

最初はグローバルコマンドではなく、反映が速いGuild Commandとして `/stockwatch` を登録します。

```powershell
python scripts/register_commands.py
```

登録されるコマンド:

- `/stockwatch`: 全体レポート
- `/stockwatch ticker:9503.T`: 指定銘柄だけ表示
- `/stockwatch status:DANGER`: 指定ステータスだけ表示
- `/stockwatch dry_run:true`: stateを更新せず確認

DiscordのInteraction応答は2000文字制限があるため、本文は1900文字以内に短縮します。長い場合、Webhook URLが設定されていて `dry_run` でなければ詳細レポートをWebhookへ分割投稿し、Interaction側では要約版を返します。Interaction応答はデフォルトでチャンネルに見える `ephemeral=false` です。将来非公開にしたい場合は `DISCORD_INTERACTION_EPHEMERAL=true` で切り替えられるようにしています。

### 本番運用

本番でSlash commandを使う場合は、FastAPIアプリをRender / Railway / Fly.io / Cloud Runなど、HTTPSで公開できる環境に置いてください。毎日通知は引き続きGitHub Actions + Webhookで動かし、Slash commandは「必要なときだけDiscordから確認する」補助ルートとして使います。

## テスト

```powershell
pytest
```

## 注意

このツールは投資助言ではありません。株価監視と分析補助を目的としたルールベース通知です。実際の売買判断は、決算、適時開示、需給、リスク許容度などを確認したうえでご自身の責任で行ってください。
