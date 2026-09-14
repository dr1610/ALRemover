# ComfyUIで使う

ALRemoverは、**切り抜き → 必要な所だけ修正 → キャラクターと背景を透過PNGで保存**する3つのカスタムノードを追加します。生成したIMAGEにも既存画像にも使えます。一人用が中心で、人物ごとの分離はComfyUI版には含みません。

## 導入

ComfyUIフォルダーから実行します。

```shell
git clone https://github.com/dr1610/ALRemover.git custom_nodes/ALRemover
```

続いて **ComfyUIが使用するPython** で不足ライブラリを追加し、ComfyUIを再起動します。

```shell
python custom_nodes/ALRemover/install.py
```

Stability MatrixのWindows環境では、ComfyUIフォルダーで次を実行できます。

```powershell
.\venv\Scripts\python.exe custom_nodes/ALRemover/install.py
```

公式Windows Portableでは、`ComfyUI_windows_portable` フォルダーで次を実行します。

```powershell
.\python_embeded\python.exe -s ComfyUI\custom_nodes\ALRemover\install.py
```

Manager等でrequirements.txtから導入する場合の依存一覧も同梱しています。Registryへの登録・Managerの検索一覧への掲載はしていません。TorchやTransformersを指定バージョンへ入れ替える処理はありません。

## まず一枚切り抜く

1. [ALRemover-basic.json](../examples/ALRemover-basic.json) をComfyUIへドラッグするか、Ctrl+Oで開きます。
2. **元画像 / Original** に画像を選びます。
3. 方式はBEN2、expandは0のまま実行します。
4. キャラクターと背景を `ComfyUI/output/ALRemover/` にPNG保存し、ノード内へ表示します。

モデルは初回実行時にHugging Faceから取得します。BEN2は約363 MiB、ToonOutは約844 MiB。保存先は **ComfyUI/models/ALRemover/** です。推論はローカルで行い、画像を外部へ送信しません。起動時には重みを読み込みません。

保存先は各Save Imageノードの `filename_prefix` で変えられます。保存せず表示だけにする場合は標準の **Preview Image** に接続します。キャラクター・背景はそれぞれ独立して接続できます。

## 必要な所だけ直す

1. [ALRemover-correction.json](../examples/ALRemover-correction.json) を開きます。
2. **元画像 / Original**、**残す部分を塗る / Keep**、**消す部分を塗る / Erase** に同じ元画像を選びます。修正ノードの `enabled` は最初はオフです。一度実行して切り抜きを確認します。
3. Keepを右クリックし **Open in MaskEditor | Image Canvas** を開きます。**クリア**で初期マスクを消し、マスク用ブラシで「残したい部分」だけ塗って保存します。
4. Eraseも同様に、クリアしてから「消したい部分」だけ塗って保存します。片方しか必要なければ、不要な方のMASK接続を外せます。
5. **ALRemover 部分修正**の `enabled` をオンにして再実行します。修正済みのキャラクター・背景が保存されます。

**元画像 / Original のマスクは編集しません。** 入力に既存の透過がある場合は特に、Keep/Erase側の初期マスクをクリアしてから塗ってください。RGBペイント用の筆ではなく、マスク用の筆を使います。ComfyUI標準エディターの操作は [公式ガイド](https://docs.comfy.org/interface/maskeditor) を参照してください。

完全に残す／消す場合はブラシ不透明度を1にします。部分修正は塗った範囲だけに作用し、薄く塗れば中間の強さで反映します。KeepとEraseが重なった場所はEraseが優先です。消しゴム・Undoは標準マスクエディター内で使います。修正ノードの `enabled` をオフにすると元の切り抜きへ戻ります。

修正だけを変えて再実行した場合は、ComfyUIのキャッシュに残っている切り抜き結果を再利用します。画像・方式・輪郭の設定を変えた場合やキャッシュが解放された場合は再推論します。

## ノードの役割

| ノード | 入力 | 出力 |
|---|---|---|
| ALRemover 切り抜き / Cutout | IMAGE、方式、輪郭調整、任意の入力透過 | キャラクターを白で表すMASK |
| ALRemover 部分修正 / Correct Mask | 切り抜きMASK、任意のKeep/Eraseマスク | 修正したMASK |
| ALRemover キャラクター・背景 / Layers | 元IMAGE、切り抜きMASK、任意の入力透過 | 人物RGBA、背景RGBA、人物アルファ |

`input_transparency` には、元画像を読み込んだ **Load ImageのMASK** を接続します。これは白が透明の逆アルファで、切り抜き出力の「白が人物」とは向きが異なります。[公式の画像・マスク仕様](https://docs.comfy.org/custom-nodes/backend/images_and_masks)

RGBAのIMAGEを直接渡した場合は、そのアルファを使います。`input_transparency` も接続した場合は、そちらを入力透過として採用します。8bit PNGの保存時には人物と背景のアルファの和が入力アルファと一致し、RGBは元画像を保持します。

生成後のIMAGEをCutoutとLayersへつなぐこともできます。透過のない生成画像なら `input_transparency` は未接続で構いません。MASKをinpaintや合成へ使う場合は、接続先で白が何を意味するか確認してください。

## 制限と検証

- 背景出力は人物部分が透明な画像です。隠れた背景の補完は行いません。
- BEN2が既定です。ToonOut・順送り・逆送りは比較用で、髪が薄くなる場合があります。
- 修正用マスクは元画像と同じ大きさにしてください。単一のマスクを画像バッチへ共通適用できます。同じバッチ数なら各画像のマスクを個別適用します。
- ComfyUIが選択したデバイスを使い、推論後はモデルをGPU・CPUキャッシュから解放します。動作確認したGPUはRTX 5070です。
- [ComfyUI版の検証記録](comfyui-verified.md) に確認済み・未確認の範囲を記載しています。

起動中のローカルComfyUIを検証する場合：

```shell
python custom_nodes/ALRemover/tests/verify_comfyui.py --image path/to/your-image.png
```

このテストは入力画像と修正用画像をローカルComfyUIへ読み込み、PNGを保存します。モデル重み・個人の画像・検証出力は配布物に含めません。
