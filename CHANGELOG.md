# 変更履歴

このプロジェクトのすべての重要な変更を記録します。
形式は [Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) に基づき、
[セマンティック バージョニング](https://semver.org/lang/ja/) を採用します。

## [未リリース]

## [1.1.0] - 2026-06-22

### Added
- ZIPファイル名テンプレート設定（`zip_filename_template`）：作品ごとのZIP保存時に出力ZIPファイル名をテンプレートで指定可能。`{artist}` `{artist_id}` `{title}` `{illust_id}` `{date}` が利用可能。拡張子 `.zip` は自動付与。空欄時は従来の挙動（ファイル名テンプレートのディレクトリ構成＋デフォルト名）を維持

## [1.0.0] - 2026-06-20

初回公開リリース。GitHub (HYDE-Systems) で OSS 公開、GHCR で Docker イメージを配布。

### Added
- MIT ライセンス、CI/CD（GitHub Actions）による Docker イメージの自動ビルド・GHCR 公開
- `docker run` / `docker compose` 両対応のドキュメント、再起動ポリシー設定（`RESTART_POLICY`）
- ダッシュボードのログインゲート：APIトークンでログインし、認証をHttpOnly Cookieに保存（再読込しても維持）。サイドレールに「ロック」ボタン
- 全API（RSS・画像プロキシを除く）をCookieまたは`X-API-Token`ヘッダで保護。未認証時 `/api/status` はトークンを漏らさず `{dashboard_authenticated:false}` を返す
- 初回ログイン用トークンを起動時にバックエンドのログへ出力
- RSSフィード機能（配信のみ）：作家の新着 `GET /api/rss/user/{user_id}`、タグ/検索 `GET /api/rss/search?word=`、フォロー新着 `GET /api/rss/following`。RSS 2.0 XMLでサムネ(プロキシ経由)付き。外部RSSリーダー向けに `?token=` でも認証可
- ダッシュボードに「RSS」タブを追加（各フィードURLの生成・コピー・購読）。作品詳細モーダルに「作家RSS」リンクを追加
- 作品ごとのZIP保存オプション（`zip_per_work`）：全ページ＋メタデータを1つのzipにメモリ経由でSMBへストリーム書込み（無圧縮ZIP_STORED）。単ページ・多ページ作品で検証済み
- 検索結果クリックで作品詳細ポップアップ（ルーペ風ライトボックス：大プレビュー・複数ページ切替・タグ・統計・キャプション・その場でダウンロード）
- 作品詳細取得エンドポイント `GET /api/illust/{illust_id}`

### Fixed
- キュー投入APIが配列直接(`[...]`)や数値配列(`[id]`)を受け付けず422になる不具合を修正（`{items:[...]}`／素の配列／数値・文字列IDのいずれも受理）
- SMB保存で親ディレクトリが作成されずダウンロードが失敗する不具合を修正（ファイル名テンプレートの `/` 区切りをSMBの `\` 区切りへ正規化）。実作品で画像・メタデータのSMB書込みを検証済み
- `makedirs` のエラーを握りつぶしていた箇所を修正し、SMBエラーがそのまま表面化するように変更
- フロントのAPIエラー表示が「[object Object]」になる不具合を修正（422バリデーションエラーの配列を可読な文字列に整形）
- ダウンロード投入前に作品IDの妥当性を検証するガードを追加

### Changed
- 詳細ポップアップのレイアウトを修正：モーダルに明確な高さを与え、大画像を確実に縮小、サムネイル列を常時表示にして縦長画像でもページ遷移できるよう改善
- 検索結果の「＋」ダウンロードボタンを常時表示に変更（ホバー依存を廃止）
- pixiv 認証の code 取得を簡略化：リダイレクトURL全体を貼り付けると `code` を自動抽出（DevTools 不要、フロント/バック両方で解析）

### 既存
- FastAPI + pixivpy によるバックエンド（認証・検索・キュー・画像プロキシ）
- pixiv `refresh_token` のダッシュボード内取得（PKCE フロー / 直接入力）
- ダウンロードキューとワーカー（複数ページ・うごイラ・メタデータJSON対応）
- SMB 共有へのメモリ経由ストリーム書込み（サーバーに永続データを残さない）
- 設定とキューの Fernet 暗号化永続化（暗号化Dockerボリューム）
- Vanilla JS + Vite の「暗室スタジオ」ダッシュボード（フィルムストリップ監視・コンタクトシート検索）
- SSE によるキューのリアルタイム監視
- Chrome 拡張機能（複数タブの一括キュー投入・右クリックメニュー・接続テスト）
- Docker / Docker Compose による起動構成
- README・アーキテクチャ図(SVG)

[1.0.0]: https://github.com/HYDE-Systems/pixiv-downloader/releases/tag/v1.0.0
