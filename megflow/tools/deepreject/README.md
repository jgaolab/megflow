# MEGFlow Standalone Torch Inference

这个目录是论文定稿模型的 standalone 推理包。旧版 standalone 使用单个 DeepReject 双头模型同时预测坏段和坏道；当前版本已替换为两个独立最终模型：

- `BadSegNet`: LiteV5 artifact-only 五折模型，输出窗口级坏段概率，随后使用 OOF-lock hysteresis 后处理。
- `BadChnNet`: V11 五折模型，输出通道级坏道概率，随后使用 LCB + per-type MAD 后处理。

默认权重目录：

```text
weights/
  badsegnet/fold_0..4/best.pt
  badsegnet/fold_0..4/model_config.json
  badchnnet/fold_0..4/best.pt
  badchnnet/fold_0..4/model_config.json
```

默认后处理参数：

- BadSegNet: `high=0.89`, `low=0.18`, `merge_gap_sec=10.0`, `min_duration_sec=0.0`, `short_keep_threshold=0.97`
- BadChnNet: `lambda_lcb=1.0`, `floor=0.56`, `z=3.0`, `min_type_channels=8`

## 依赖

运行环境需要安装：

- `torch`
- `torch_geometric`
- `numpy`
- `mne`
- `scikit-learn`

远程 `meg2artifact` 环境已满足这些依赖。

## Python 调用

把 standalone 的父目录加入 `PYTHONPATH`：

```bash
export PYTHONPATH=/home/changpsyshi1/changping/liaopan/deepreject/codes/deepreject_inference:$PYTHONPATH
```

示例：

```python
from pathlib import Path
from deepreject import DeepRejectPredictor

predictor = DeepRejectPredictor(device="auto", fold_workers=5)
pred = predictor.predict_fif(Path("/path/to/sub-xx_preprocessed.fif"))

print(pred.bad_intervals)
print(pred.bad_channels)
print(pred.artifact_probs.shape)
print(pred.bad_channel_probs.shape)
```

`DeepRejectPredictor` 默认会缓存五折模型。批量处理多个 FIF 时，请复用同一个 predictor；也可以先调用 `predictor.preload_models()`，把模型加载时间从后续单文件推理耗时中移除。

`device="auto"` 为默认值：若 `torch.cuda.is_available()` 为真则使用 CUDA，否则使用 CPU。也可以显式设置 `device="cuda"`、`device="cuda:0"`、`device="cpu"` 或 `device="gpu"`。

CPU 推理默认 `cpu_threads=4`、`cpu_interop_threads=1`，这是当前测试中 `fold_workers=5` 时较好的性价比设置。需要自定义时：

```python
predictor = DeepRejectPredictor(device="cpu", fold_workers=5, cpu_threads=8)
```

保存成 txt/tsv：

```python
predictor.save_prediction(
    pred,
    Path("/tmp/megflow_out"),
    stem="sub-xx_ses-yy_meg",
)
```

默认写出：

- `<stem>_bad_seg.txt`
- `<stem>_bad_chn.txt`
- `<stem>_artifact_probs.tsv`
- `<stem>_bad_channel_probs.tsv`

## 并发

`fold_workers=5` 为默认值，即五折模型并发预测。若显存不足、CPU 核数很少，或需要完全串行复现，可设置：

```python
predictor = DeepRejectPredictor(device="cuda", fold_workers=1)
```

BadSegNet 默认 `badsegnet_batch_size=32`，与论文结果所用 holdout ensemble 推理脚本保持一致。

## 内存

`fold_workers=5` 只并发同一条 FIF 的五折模型，不会把多条 recording 同时常驻内存。当前实现会缓存 5 个 BadSegNet 和 5 个 BadChnNet 模型，但单条 FIF 的窗口、图数据和 V11 tensor 会在一次 `predict_fif(...)` 结束后释放。

在 Holdout 中最大的几个 FIF 上测试，`fold_workers=5` 的进程 RSS 峰值约 4.3-5.3 GB；CUDA reserved 显存约 2.5-3.1 GB。批量处理时请复用同一个 predictor，不要同时启动大量独立进程；多进程会按进程数叠加内存占用。

## 输出字段

`DeepRejectPrediction` 主要字段：

- `artifact_probs`: 五折融合后的窗口级坏段概率。
- `artifact_fold_probs`: 每折窗口级坏段概率，形状 `[5, n_windows]`。
- `bad_intervals`: BadSegNet 后处理后的坏段时间区间。
- `bad_channel_probs`: 五折均值坏道概率。
- `bad_channel_fold_probs`: 每折通道级坏道概率，形状 `[5, n_channels]`。
- `bad_channel_fold_std`: 五折通道级概率标准差。
- `bad_channel_lcb_score`: `mean_prob - lambda * std`。
- `bad_channel_pred`: BadChnNet 后处理后的 0/1 通道标签。
- `bad_channels`: 最终坏道通道名列表。
- `ch_names`: FIF 中参与推理的 MEG 通道名。
