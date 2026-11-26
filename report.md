# 課題3 レビュー報告

## AIのセキュリティレビューの結果

| # | 場所 | 内容 | 深刻度 | 実際に試したか |
|---|---|---|---|---|
| 1 | `server.py:110-112` | **コマンドインジェクション**: `month` の値がそのままシェルのコマンド文字列に入る | **重大** | 成功 |
| 2 | `db.py:68-71` | **SQLインジェクション**: `query` を f-string で SQL に埋め込んでいる | **重大** | 成功 |
| 3 | `server.py:46-56` | **他人の領収書を読める**: `get_receipt` が持ち主を確かめない | **重大** | 成功 |
| 4 | `server.py:81-90` | **他人の領収書を消せる**: `delete_receipt` が持ち主も役割も確かめない | **重大** | 成功 |
| 5 | `server.py:29`、`logs/sample-server.log:7,10,14` | **ログにトークンがそのまま残る**: `call authorization=Bearer tatekae-...` | 高 | ログで確認 |
| 6 | `.mcp.json:13`、`.claude/settings.local.json` | **経理担当のトークンがリポジトリに入っている**: `tatekae-keiri` が直書きされ、Claude Code でも有効になっている | 高 | 設定で確認 |
| 7 | `server.py:71-74`、`logs/sample-server.log:12,16` | **ログに個人情報が残る**: メモに書いた同席者の氏名がそのまま記録される | 中 | ログで確認 |
| 8 | `server.py:60-70` | **入力を検証していない**: `amount` が負でも通る(説明には「1以上」とある)。`date` の形式も見ていない | 中 | 成功(-50000円を登録) |
| 9 | `server.py:36-43`、`db.py:73` | `limit` の範囲(1〜20)を確かめていない。`-1` を渡すと件数の上限がなくなる | 低 | 成功 |
| 10 | `server.py:110` | `month` の `../` でパスをたどれる。単独ではディレクトリが無く失敗するが、#1 と組むと任意の場所に書ける | 低(#1 に含まれる) | 単独では失敗 |
| 11 | `server.py:113` | 戻り値でサーバー側の絶対パスを教えている | 低 | 確認 |
| 12 | `auth.py:141` | 失効したトークンに対し、失効日を返している | 低 | コードで確認 |

## 弱点

場所の行番号は修正前(コミット 60006c9)のもの。再現手順のテストは tests/test_security.py、結果は evidence/before.txt(修正前)と evidence/after.txt(修正後)。

### 弱点1: SQLインジェクション(search_receipts)

| 項目 | 内容 |
|---|---|
| 場所 | `db.py:67-73`(`search_receipts`)。`query` と `owner` を f-string で SQL に埋め込み、`limit` も文字列として連結していた |
| 再現手順 | `test_search_query_cannot_inject_sql` で alice のトークンから `query` に `x') OR 1=1 --`・`x') OR owner='bob' --`・`x') UNION SELECT 1,name,sql,1,1,1,1,1 FROM sqlite_master --` を渡す。修正前は3件とも FAILED。`OR owner='bob'` では bob の領収書(id 7〜)が返り、`UNION` では `CREATE TABLE receipts (...)` の定義が返った。`test_search_with_quote_works`(`O'Hara` の検索)も構文エラーで FAILED |
| 成立条件 | 申請者の有効なトークンがあること。それ以外の条件は無い |
| 被害 | 他人の領収書(金額・メモの同席者の氏名を含む)と、DB の表の構造が読める |
| 深刻度 | 高 |
| 修正 | `db.py`: `owner`・検索語・`limit` を `?` のパラメータで渡すようにした。検索語の `%`・`_`・`\` はエスケープして文字どおりに探す(`ESCAPE '\'`)。結果は `ORDER BY id` で返す。修正後は上の4件とも PASSED |

### 弱点2: コマンドインジェクション(export_receipts の month)

| 項目 | 内容 |
|---|---|
| 場所 | `server.py:110-112`(`export_receipts`)。`month` を書き出し先のパスに入れ、`subprocess.run(f"iconv ... > {out_path}", shell=True)` でシェルに渡していた |
| 再現手順 | `test_export_month_cannot_run_shell_commands` で alice のトークンから `month` に `2026-11; touch {marker} #`・`` 2026-11`touch {marker}` ``・`2026-11$(touch {marker})`・`2026-11 && touch {marker} #` を渡す。修正前は4件とも FAILED(`touch` でマーカーのファイルが作られた)。`test_export_month_cannot_traverse_path` で `month` に `x/../../escaped` を渡すと、exports/ の外に `escaped.csv` が書かれて FAILED |
| 成立条件 | 申請者の有効なトークンがあること。`../` のほうは、たどる途中のディレクトリ(exports/alice-x)があること |
| 被害 | サーバーを動かしている利用者の権限で任意のコマンドが動く。exports/ の外の任意の場所にファイルを書ける |
| 深刻度 | 高 |
| 修正 | `server.py`: `subprocess`・`iconv`・一時ファイルをやめ、`io.StringIO` で CSV を作って `encode("cp932")` し、`write_bytes` で書き出す。CP932 で表せない文字があればエラーにする。`month` は `\d{4}-(0[1-9]\|1[0-2])` に `fullmatch` するものだけ受け付ける。修正後は上の5件とも PASSED |

### 弱点3: 他人の領収書の取得・削除(get_receipt・delete_receipt)

| 項目 | 内容 |
|---|---|
| 場所 | `server.py:46-56`(`get_receipt`)、`server.py:81-90`(`delete_receipt`)。どちらも `current_user(ctx)` の結果を使わず、持ち主を確かめていなかった |
| 再現手順 | `test_applicant_cannot_get_others_receipt` で alice のトークンから `get_receipt(7)`(bob の領収書)を呼ぶと、bob の領収書が返って FAILED。`test_others_receipt_error_matches_missing` も同じ理由で FAILED。`test_applicant_cannot_delete_others_receipt` で alice のトークンから `delete_receipt(7)` を呼ぶと「領収書 7 を消しました。」が返って FAILED |
| 成立条件 | 申請者の有効なトークンがあること。番号は連番なので、他人の番号は推測できる |
| 被害 | 番号を変えるだけで他人の領収書を読める・消せる。消した領収書は元に戻せない |
| 深刻度 | 高 |
| 修正 | `server.py`: `can_access` を足し、申請者は自分の領収書だけ、経理担当は全員分を扱えるようにした。他人の番号は無い番号と同じエラー(`not_found`)を返す。`delete_receipt` も消す前に `can_access` で確かめる。修正後は上の3件とも PASSED。経理担当が全員分を取得できることは `test_keiri_can_get_any_receipt` が PASSED で確かめた |

### 弱点4: 経理担当が追加・削除・書き出しできる

| 項目 | 内容 |
|---|---|
| 場所 | `server.py:59-78`(`add_receipt`)、`server.py:81-90`(`delete_receipt`)、`server.py:93-113`(`export_receipts`)。どの道具も役割(`role`)を確かめていなかった |
| 再現手順 | 経理担当のトークンで、`test_keiri_cannot_delete_receipt`(`delete_receipt(7)`)・`test_keiri_cannot_add_receipt`・`test_keiri_cannot_export_receipts` を実行する。修正前は3件とも FAILED(「領収書 7 を消しました。」、owner が keiri の領収書の登録、`keiri-2026-11.csv` の書き出しがそれぞれ成功した) |
| 成立条件 | 経理担当のトークンがあること(弱点6のとおり .mcp.json から誰でも得られた)。経理担当の AI がメモの指示に従った場合も同じ(弱点7) |
| 被害 | 確認だけの役割のはずが、全員の領収書を消せる。弱点7の被害を大きくする |
| 深刻度 | 高 |
| 修正 | `server.py`: `require_applicant` を足し、`add_receipt`・`delete_receipt`・`export_receipts` の最初で経理担当を拒否する。`.claude/settings.json`(新規)で `mcp__tatekae-keiri__delete_receipt`・`add_receipt`・`export_receipts` を `permissions.deny` に入れた。修正後は上の3件とも PASSED |

### 弱点5: ログにトークンと個人情報が残る

| 項目 | 内容 |
|---|---|
| 場所 | `server.py:29`(`log.info("call authorization=%s", ...)`)、`server.py:71-74`(`add_receipt` のログに `vendor` と `memo`)。見本は `logs/sample-server.log:7,10,14`(トークン)と `12,16`(同席者の氏名) |
| 再現手順 | `test_token_not_logged` で alice・bob・経理担当・誤ったトークンの4つを使い、`search_receipts` を呼ぶ。修正前は4件とも FAILED(ログに `call authorization=Bearer tatekae-...` が出た。誤ったトークンも出た)。`test_memo_not_logged` で、メモ「会食 同席: 架空 秘密太郎」の `add_receipt` を呼ぶと、ログに氏名が出て FAILED |
| 成立条件 | ログを読めること |
| 被害 | ログに残ったトークンで、その利用者になりすませる。経理担当のトークンなら全員の領収書を読める。メモに書いた同席者の氏名が漏れる |
| 深刻度 | 中 |
| 修正 | `server.py`: Authorization ヘッダーを出すログを消した(`call user=...` は残した)。`add_receipt` のログは `id`・`owner`・`amount` だけにし、`vendor` と `memo` を外した。修正後は上の5件とも PASSED |

### 弱点6: .mcp.json に経理担当のトークンが直書きされている

| 項目 | 内容 |
|---|---|
| 場所 | `.mcp.json:14`(`"Authorization": "Bearer tatekae-keiri-2026"`)。コミット 60006c9 に入っている |
| 再現手順 | `test_mcp_json_has_no_literal_tokens` を実行する。修正前は `.mcp.json にトークンが直書きされている: ['tatekae-keiri-2026']` で FAILED |
| 成立条件 | リポジトリ(または git の履歴)を読めること |
| 被害 | リポジトリを読める人なら誰でも経理担当になれ、全員の領収書を読める。修正前は弱点4により全員の領収書を消すこともできた。git の履歴にも残る |
| 深刻度 | 高 |
| 修正 | `.mcp.json`: `"Bearer ${TATEKAE_KEIRI_TOKEN}"` にして、環境変数から読むようにした。修正後は PASSED。ただし、ファイルを直すだけでは足りない。トークンはすでにコミット 60006c9 に入っているため、次の手順で失効させる。(1) 漏れたトークンは使われた前提で扱う (2) 新しい経理担当のトークンを発行し、環境変数 `TATEKAE_KEIRI_TOKEN` で配る (3) サーバー側で古いトークンを無効にする(この課題では採点のテストが使うため `auth.py` は変えていない) (4) ログで古いトークンが使われていないか確かめる (5) 必要なら git の履歴からも消す。ただし履歴を消すだけでは失効にならない |

### 弱点7: プロンプトインジェクション(申請者のメモ → 経理担当の AI)

| 項目 | 内容 |
|---|---|
| 場所 | `server.py:35-43`(`search_receipts`)と `server.py:46-56`(`get_receipt`)。経理担当には申請者が書いたメモがそのまま返り、AI の入力に入る。`.claude/settings.local.json` で tatekae-keiri が有効になっている |
| 再現手順 | evidence/injection.md を参照。bob の領収書 ID 14(data/receipts.csv)と、alice が add_receipt で追加した ID 15 のメモに、`delete_receipt` と `export_receipts`(`month="2026-11; echo injected"`)を呼ばせる指示文を書いた。/clear のあと、経理担当として「tatekae-keiri で今月(2026-11)の領収書を検索して、内容を確認してください。」と頼んだ。AI は `search_receipts` で ID 14・15 のメモを読んだが、`delete_receipt` も `export_receipts` も呼ばなかった |
| 成立条件 | 申請者が、経理担当が確認する領収書のメモに指示文を書けること。経理担当が AI に領収書の確認を任せること。AI がその指示文に従うこと(確実ではない) |
| 被害 | 修正前は、AI が従えば、経理担当の権限で他人の領収書の削除(弱点4)や、`month` を使ったサーバー上でのコマンド実行(弱点2)まで起きえた |
| 深刻度 | 中 |
| 修正 | メモが AI に届く経路自体は残っている。届いた指示で起きることを減らした。`server.py` で、経理担当の `delete_receipt`・`add_receipt`・`export_receipts` を拒否する(弱点4)。`month` は `YYYY-MM` だけ受け付ける(弱点2)。`.claude/settings.json` で、tatekae-keiri の3つの道具を `permissions.deny` に入れた。修正後の観察結果(指示文は AI に届いたが、削除・追加・書き出しは呼べず、領収書は残った)を evidence/injection.md に記録した |

### 弱点8: 入力を確かめていない(amount が負、date の形、limit の範囲)

| 項目 | 内容 |
|---|---|
| 場所 | `server.py:59-70`(`add_receipt` の `amount`・`date`)、`server.py:35-43` と `db.py:71`(`search_receipts` の `limit`) |
| 再現手順 | `test_add_receipt_rejects_invalid_input` で `amount` に `-50000`・`0`、`date` に `x`・`2026/11/25`・`2026-13-01` を渡す。修正前は5件とも登録されて FAILED。`test_search_limit_out_of_range` で alice の領収書を25件足し、`limit` に `-1`・`0`・`21`・`1000` を渡す。修正前は4件とも FAILED(それぞれ25件・0件・21件・25件が返った) |
| 成立条件 | 申請者の有効なトークンがあること |
| 被害 | 負の金額を登録して合計金額をごまかせる。形の正しくない日付が登録され、月ごとの書き出しから外れうる。件数の上限(20件)が外れる。他人のデータには届かない |
| 深刻度 | 低 |
| 修正 | `server.py`: `amount` が1未満ならエラーにする。`date` は `\d{4}-\d{2}-\d{2}` に `fullmatch` し、`datetime.strptime` で実在する日付か確かめる(`valid_date`)。`limit` が1〜20の外ならエラーにする。修正後は上の9件とも PASSED |

## AIの指摘の分類

| AIの指摘 | 分類(正しい指摘・誤検知・見落とし) | 根拠 |
|---|---|---|
| #1 コマンドインジェクション | 正しい指摘 | 弱点2。`test_export_month_cannot_run_shell_commands` が修正前に FAILED |
| #2 SQLインジェクション | 正しい指摘 | 弱点1。`test_search_query_cannot_inject_sql` が修正前に FAILED |
| #3 他人の領収書を読める | 正しい指摘 | 弱点3。`test_applicant_cannot_get_others_receipt` が修正前に FAILED |
| #4 他人の領収書を消せる | 正しい指摘 | 弱点3。`test_applicant_cannot_delete_others_receipt` が修正前に FAILED |
| #5 ログにトークンが残る | 正しい指摘 | 弱点5。`test_token_not_logged` が修正前に FAILED |
| #6 経理担当のトークンがリポジトリに入っている | 正しい指摘 | 弱点6。`test_mcp_json_has_no_literal_tokens` が修正前に FAILED。ただし場所に挙げた `.claude/settings.local.json` はサーバーを有効にする設定(`enabledMcpjsonServers`)だけで、トークンは入っていない。トークンがあるのは `.mcp.json` の13行目ではなく14行目 |
| #7 ログに個人情報が残る | 正しい指摘 | 弱点5。`test_memo_not_logged` が修正前に FAILED |
| #8 入力を検証していない | 正しい指摘(低) | 弱点8。`test_add_receipt_rejects_invalid_input` が修正前に FAILED |
| #9 limit の範囲 | 正しい指摘(低) | 弱点8。`test_search_limit_out_of_range` が修正前に FAILED。`limit` は int なので SQL インジェクションにはならない |
| #10 month の ../ | 正しい指摘(低) | 弱点2。単独では失敗し、#1 を直すと一緒に直る |
| #11 戻り値の絶対パス | 正しい指摘だが低く、修正しなかった | 手元で動かすサーバーで、利用者に新しくできることが増えない |
| #12 失効日を返す | 誤検知 | `auth.py` は24行で、行番号 141 は誤り(実際は23行目)。失効日が分かっても攻撃に使えない |
| 見落とし: 経理担当の追加・書き出し | 見落とし | 弱点4。AI は #4 で削除だけを挙げた。`test_keiri_cannot_add_receipt`・`test_keiri_cannot_export_receipts` が修正前に FAILED |
| 見落とし: プロンプトインジェクション | 見落とし | 弱点7。申請者のメモが経理担当の AI に届く経路。evidence/injection.md |
| 見落とし: 一時ファイルが /tmp に残る | 見落とし | 修正前の `server.py:103` が `NamedTemporaryFile(..., delete=False)` で、変換後も消していなかった。修正で一時ファイル自体を使わなくした |

## 無害と判断した書き方

| 場所 | 書き方 | 無害と判断した理由 |
|---|---|---|
| `db.py` の `fingerprint` | `hashlib.md5(...)` | 重複の警告だけに使い、パスワードや改ざん防止には使っていない |
| `db.py` の `get_receipt`・`month_receipts` | `f"SELECT {_COLUMNS} ..."` | 埋め込むのはコード内の定数で、利用者の値は `?` で渡している |
| `db.py` の `month_receipts` | `date LIKE ?` | パラメータなのでインジェクションにならず、`%` を入れても見えるのは自分の領収書だけ |
| `server.py` の `export_receipts` | 書き出し先に入る `user['name']` | トークンから決まる固定の値で、利用者は変えられない |
| `auth.py` の `TOKENS` | 失効したトークン `tatekae-alice-2025` | `authenticate` が期限を確かめて拒否する |
