# ALRemover

キャラクターと背景を分離して透過PNGで保存する、Forge Neo・ComfyUI用の拡張です。既定モデルはBEN2。公開ベータ **v1.4.0-beta.1**。

**複数人の分離機能や、Neo上部への専用タブ追加はありません。**

## Forge Neo

1. Extensions → Install from URLへ `https://github.com/dr1610/ALRemover.git` を入力し、導入後に再起動します。
2. txt2img / img2imgの **Script → ALRemover** を選びます。
3. 方式・表示・保存する画像を選んで実行します。

キャラクター・背景・元画像・マスクを選べます。表示と自動保存は独立しています。保存先はNeoの通常の画像出力先です。

img2imgは既定で **入力画像をそのまま切り抜く（再生成しない）** がオンです。オフにすると生成結果を切り抜きます。入力サイズはimg2imgの幅・高さを確認してください。

旧開発版 `anime-layer-remover-neo` と同時に有効にしないでください。モデル保存先は互換性のため `models/AnimeLayerRemoverNeo/` を継続します。

## ComfyUI

**[導入と使い方](docs/comfyui.md)** に従って `custom_nodes/ALRemover` へ導入してください。

- [基本ワークフロー](examples/ALRemover-basic.json)：切り抜きと透過PNG保存。
- [部分修正ワークフロー](examples/ALRemover-correction.json)：標準マスクエディターで残す／消す部分を指定して保存。

生成後のIMAGEにも既存画像にも使用できます。表示・保存は標準のPreview Image / Save Imageへ接続します。

## 方式と制限

- **BEN2**が既定。ToonOut・順送り・逆送りも比較用に選べます。
- 髪の欠け、白い服や肌の半透明化、背景の消し残しは起こり得ます。順送り・逆送りでは細い髪が薄くなる場合があります。
- 元のRGBを保持してアルファを分離します。境界色の自動補正はしません。
- 背景出力は人物部分が透明な画像です。隠れた背景の生成補完はありません。
- 初回にモデルを取得します。BEN2は約363 MiB、ToonOutは約844 MiB。推論はローカルで行い、入力画像を外部へ送信しません。

[検証記録](VERIFIED.md) · [ComfyUIの検証](docs/comfyui-verified.md) · [変更履歴](CHANGELOG.md)

## ライセンス

独自コードは [MIT](LICENSE)。モデル・利用コードは [THIRD_PARTY.md](THIRD_PARTY.md) を参照してください。
