# 検証記録

対象：ALRemover v1.4.0-beta.1。Windows / RTX 5070 12GB。

- 画像・アルファ・局所修正・順送り／逆送り・ComfyUIのバッチ処理に関する単体テスト15件。
- ComfyUIでモデル取得、4方式の切り抜き、標準マスクエディターでの修正、キャラクター・背景のRGBA保存を確認。[詳細](docs/comfyui-verified.md)
- NeoのScriptによる切り抜きを継続。専用タブと複数人分離は削除した。

[旧v1.3.0の新規Neo環境の検証記録](https://github.com/dr1610/ALRemover/blob/v1.3.0-beta.1/VERIFIED.md) は、その版にあった専用タブの検証も含む。現行版の画面構成とは異なる。

正解マスクによる大規模な精度評価や、別OS・別GPUでの動作確認はしていない。
