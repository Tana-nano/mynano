# 無意識デーモン

`nano chat` は話しかけられたときだけ動く。デーモンは、その裏で動き続ける方。

```bash
python -m nano daemon              # 常駐
python -m nano daemon --once       # 1 tick だけ
python -m nano daemon --once --now # 間隔とアイドルを無視して即座に動かす
python -m nano jobs                # キューの状態
python -m nano review              # 人格変更の提案を承認/却下
```

## 何をしているか

1 tick ごとに、取り残されたジョブを回収し、期限の来た仕事を積み、**1件だけ**実行する。
1 tick 1 ジョブなのは、対話にいつでも道を空けておくため。

| 仕事 | いつ | 内容 |
|---|---|---|
| `write` | 会話が途切れて30秒後 | 生ログを記憶に変える（要約→原子化→埋め込み→リンク） |
| `ingest` | 10分ごと | `soul/inbox/` のファイルを外界からの記憶として取り込む |
| `associate` | 15分ごと（アイドル時） | 記憶を無作為に2〜3引き合わせ、繋がりがあれば結ぶ |
| `reflect` | 30分ごと（アイドル時） | 前回以降の重要度の蓄積が閾値を超えていたら、一段高い気づきを作る |
| `decay` | 日次（アイドル時） | 忘却曲線の再計算、cold化、統合 |
| `curate` | 週次（アイドル時） | 矛盾の解決、`current_focus`/`mood` の更新、人格変更の提案 |

**アイドル**とは「最後の発話から90秒以上経った」状態（`config.toml` の `idle_seconds`）。
相手が話している最中に GPU を背景処理で埋めないための線引き。

`associate` が M2 の主役。想起は「いま話していること」に引きずられるので、
誰も探しにいかない組み合わせの記憶は永遠に出会わない。それを無作為に引き合わせるのがこの仕事で、
**「寝ている間に何か考えていた」の実体**はここにある。

## 対話とデーモンはどう譲り合うか

GPU は1枚しかないので、対話とデーモンは同じモデルを奪い合う。
`soul.db` の `model_lease`（1行だけの表）をリースとして使って調停している。

```
デーモンが生成中 ──▶ あなたが話しかける ──▶ preempt_requested が立つ
                                              │
        ジョブは pending に戻る ◀── 生成を中断 ◀┘  （0.2秒以内）
```

割り込まれたジョブは失敗扱いにならず、リトライ回数も消費しない。
**考えかけたことは、あとで考え直される。**

リースには10秒の期限がある。デーモンのプロセスが強制終了されても、
期限切れでモデルは自動的に戻ってくる。

## 人格に触れる部分の扱い

無意識が直接書き換えるのは `current_focus` と `mood` だけ。

`identity`（自己像）と `user_model`（あなた像）は**提案するだけ**で、
`proposals` テーブルに積まれる。反映されるのは `nano review` で承認したときだけ。

```
$ nano review

── 提案 #3 [identity] 2026-09-06T04:12:00+09:00
いま  : (未設定)
提案  : わたしは即答するより、少し黙って考える方が多い
理由  : 最近の会話で、返答の前に間を置く場面が続いた
承認する? [y/n/s=保留/q=終了]
```

承認されたものは `working_state_log` に `updated_by='human'` として残る。
無意識が勝手に書いた形跡と区別がつくので、**気づかないうちに別人になっていた**が起きない。

```bash
python -m nano state identity --history   # 誰がいつ書き換えたか
```

## 外界の取り込み

`soul/inbox/` にファイルを置くと、次の `ingest` で読まれる。

- 対象: `.txt` `.md` `.json` `.log` `.csv`（1回あたり5ファイルまで、各2万文字まで）
- 読んだファイルは `soul/inbox/processed/` へ移動する
- 同じ内容のファイルは二度取り込まない（内容のダイジェストで判定）
- 取り込まれた内容は `role='world'` のイベントになり、通常の書き込みパイプラインが記憶にする

「自分で話したこと」と「外から入ってきたこと」が同じ記憶として扱われるので、
`/why` の想起にも普通に混ざってくる。

## Windows に常駐させる

前提として **llama-server が先に起動していること**。デーモンは LLM が居なければ
ジョブを失敗させ、5分後に再試行する（落ちはしないが、何も進まない）。

1. `deploy/windows/nano-unconscious.bat` を開き、`NANO_HOME` を自分の環境に書き換える
2. `deploy/windows/nano-unconscious.xml` の `<Command>` を bat の絶対パスに書き換える
3. 取り込む:

```
schtasks /create /tn "nano-unconscious" /xml deploy\windows\nano-unconscious.xml
```

| やること | コマンド |
|---|---|
| 今すぐ起動 | `schtasks /run /tn "nano-unconscious"` |
| 止める | `schtasks /end /tn "nano-unconscious"` |
| 自動起動をやめる | `schtasks /change /tn "nano-unconscious" /disable` |
| 消す | `schtasks /delete /tn "nano-unconscious" /f` |

ログオンの1分後に起動し、異常終了したら5分後に3回まで再起動する設定にしてある。
多重起動は `IgnoreNew` で防いでいるが、仮に二重で走ってもジョブキューが
同じ仕事を二度実行させないので、記憶が壊れることはない。

ログは `soul\log\unconscious-YYYYMMDD.log` に溜まる。

## うまく動かないとき

| 症状 | 見るところ |
|---|---|
| 何も起きない | `nano jobs` でキューを見る。全部 `done` なら、まだ間隔が来ていないだけ |
| 記憶が増えない | アイドル待ちかもしれない。`nano daemon --once --now` で確かめる |
| ジョブが `failed` | `nano jobs` に直近のエラーが出る。たいてい llama-server が落ちている |
| 対話の返事が遅い | デーモンを止めて比べる。リースが効いていれば0.2秒程度しか変わらないはず |
