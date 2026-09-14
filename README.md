# ALRemover

**キャラクターを切り抜いて、必要な所だけ直して保存する、Forge Neo用の背景分離拡張です。**

公開ベータ **v1.3.0-beta.1**。一人のキャラクターを中心とした使い方を想定しています。既定モデルはBEN2です。髪・白い服・肌・背景の線などは部分修正が必要になる場合があります。

ALRemover is a local extension for [Forge Neo](https://github.com/Haoming02/sd-webui-forge-classic/tree/neo): remove a character's background with BEN2, correct selected areas with keep/erase brushes, and save transparent character/background PNGs. The UI and detailed guide are currently in Japanese. Multi-person separation is experimental.

## 導入

対象は **Forge Neo（neoブランチ）** です。通常のA1111、旧Forge、reForgeでの動作は未確認です。

1. Neoの **Extensions → Install from URL** に `https://github.com/dr1610/ALRemover.git` を入力してインストールします。
2. **Apply and restart UI**、またはNeoを終了して再起動します。
3. **ALRemover** タブへ画像を読み込み、**切り抜く** を押します。

手動導入の場合は、Neoのフォルダーで次を実行して再起動してください。

```shell
git clone https://github.com/dr1610/ALRemover.git extensions/ALRemover
```

ZIPを使う場合も、`extensions/ALRemover/install.py` が存在する配置にします。ZIP内のフォルダーを二重にしないでください。

初回のBEN2使用時には約363 MiBのモデルをHugging Faceから取得します。コードの導入と初回モデル取得にはインターネット接続が必要です。配置後の推論はローカルで行い、入力画像を外部サービスへ送信しません。起動しただけでは切り抜きモデルを読み込みません。

開発版 `anime-layer-remover-neo` が既に入っている場合は旧版を無効化してください。同時に有効にしないでください。旧版の画像・モデルは削除しません。モデル保存先は互換性のため `models/AnimeLayerRemoverNeo/` を引き続き使用します。

## まず一人を切り抜く

1. **ALRemover** タブへ元画像を読み込みます。
2. 方式は **BEN2**、輪郭の調整は **0** のまま、**切り抜く** を押します。
3. **部分修正（緑＝残す／赤＝消す）** を開き、**修正ブラシ**で「緑：残す」または「赤：消す」を選んで塗ります。欠けた所を緑、背景の消し残しを赤で直します。
4. **修正を反映** を押し、結果を確認します。
5. **保存する画像**で種類を選び、**選択した画像を PNG 保存** を押します。

キャラクター・背景・元画像・マスクを選べます。表示と保存の選択は独立しており、キャラクターと背景の両方を表示・保存できます。保存後はファイルのリンクが表示されます。

保存先は `Neo/outputs/ALRemover/日付/` です。PNGは入力と同じ大きさ・位置で、元のRGBと既存の透過を保持します。原寸で処理したい画像には、このタブを使ってください。

ブラシの変更は塗った範囲だけに適用されます。消しゴムで線を消して再度反映するとその部分を戻せます。**修正をリセット**で最初の切り抜き結果へ戻ります。

**背景出力は、キャラクターがいた場所が透明になった画像です。隠れていた背景を生成して埋める機能はありません。**

## txt2img・img2imgから使う

旧ABGに近い操作として、txt2imgまたはimg2imgの **Script → ALRemover** を選べます。

- **txt2img**：通常どおり生成した画像を切り抜きます。
- **img2img**：既定では **入力画像をそのまま切り抜く（再生成しない）** がオンです。オフにするとimg2imgの生成結果を切り抜きます。
- 表示と自動保存をそれぞれ選び、通常の生成ボタンを押します。保存のチェックをすべて外すと、このScriptは自動保存しません。
- 保存先はNeoの通常のサンプル出力先です。バッチ画像ごとのseed・生成情報・方式をPNGに記録し、グリッドを切り抜き対象から外します。

img2img本体がScriptへ渡す前に入力をリサイズする場合があります。元の大きさと既存の透過を厳密に保ちたい場合は **ALRemover** タブを使ってください。

## 方式の選択

| 方式 | 用途と制限 |
|---|---|
| **BEN2** | 既定の単独処理。まずこの方式で確認します |
| ToonOut | 別モデルでの比較。画像によって背景を広く残します |
| ToonOut → BEN2（灰色背景） | 順送りの比較用モード。細い髪が薄くなる場合があります |
| BEN2 → ToonOut（灰色背景） | 逆送りの比較用モード。同様に髪が薄くなる場合があります |

順送り・逆送りは一段目の結果を灰色背景に合成して二段目へ渡し、二つのマスクを乗算します。BEN2単独より良くなるとは限りません。最終画像には元のRGBを使用し、既定ではぼかしや二値化を加えません。

輪郭の調整はマスクを指定ピクセル数だけ広げる／縮める処理です。細い髪へ影響するため、まず0で処理し、局所的な問題はブラシで直してください。

## 実験的な人物別編集

**ALRemover 人物別（実験）** タブでは、GroundingDINOとSAM2.1を使って人物ごとに調整・保存できます。[操作説明](docs/experimental-people.md)

接触する腕・手・髪の所属や人数を誤ることがあります。Scriptの **実験的な機能 → 人物ごとに分ける** は既定でオフです。一人の切り抜きでは有効にする必要がありません。RT-DETRと検出枠のドラッグ編集は、この版には含みません。

## モデルとメモリ

使用する方式のモデルだけを初回利用時に取得します。固定リビジョンを使用し、Hugging Faceのremote codeは実行しません。

| 機能 | 重みの目安 | 保存先（Neo内） |
|---|---:|---|
| BEN2 | 363 MiB | `models/AnimeLayerRemoverNeo/ben2/` |
| ToonOut | 844 MiB | `models/AnimeLayerRemoverNeo/toonout/` |
| 人物別：SAM2.1 | 856 MiB | `models/AnimeLayerRemoverNeo/sam2/` |
| 人物別：GroundingDINO | 657 MiB | `models/AnimeLayerRemoverNeo/grounding_dino/` |

推論後はモデルをGPUからCPUへ退避し、次回用にCPUメモリへ保持します。**切り抜きモデルをメモリから解放**でCPUからも解放できます。順送りも一モデルずつGPUへ載せます。Neoと処理キューを共有し、処理に伴う乱数・計算設定の変更は元へ戻します。

不足する補助ライブラリをインストーラーで追加します。ホストのPyTorchやTransformersは拡張側から入れ替えません。

## 品質と対応環境

- 単一人物でも、白い服・肌の半透明化、髪の欠け、背景の消し残しが起こり得ます。
- 元の境界画素に混ざっている背景色を自動除去する色補正は行いません。必要に応じて合成先の背景色でも確認してください。
- キャラクターと背景のアルファの和は入力アルファと一致します。ただし通常の重ね合わせだけで半透明の境界を厳密に元へ戻せるという意味ではありません。
- Windows・Forge Neo・RTX 5070 12GBで検証しています。別OS・別GPUの動作を保証するものではありません。
- 実測条件と未検証の範囲は [VERIFIED.md](VERIFIED.md) に記録しています。

## テスト

NeoのPython環境で、リポジトリのフォルダーから実行します。

```shell
python -m unittest discover -s tests -p "test_*.py"
```

起動中のローカルNeoに画像を渡し、切り抜き・ブラシ・保存・リセットを検証する場合：

```shell
python tests/verify_single_person.py --url http://127.0.0.1:7860 --image path/to/your-image.png
```

この検証は画像を処理し、Neoの出力フォルダーにPNGを保存します。画像は各自で用意してください。モデル重み、個人の画像、生成情報、検証出力はリポジトリへ同梱していません。

## ライセンス

ALRemoverの独自コードは [MIT License](LICENSE) です。利用コード・モデルの出典とライセンスは [THIRD_PARTY.md](THIRD_PARTY.md) と `licenses/` に記載しています。
