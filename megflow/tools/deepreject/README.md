# DeepReject Standalone Torch Inference

这个目录是自包含 Torch 推理包，已包含 DeepReject 模型源码副本和默认权重。

- FIF 读取与切窗保持 m0 的全量窗口推理思路；
- PyG Data 构造使用 m0 同源的 `model.data_builder.build_recording_data_list(...)`；
- Torch forward 使用原始 DeepReject 模型和 `state_dict` 权重；
- 只包含 Torch 推理逻辑；
- 不包含自动坏道预检逻辑。

默认权重：

- `weights/best.pt`
- `weights/model_config.json`

模型结构参数会自动从 `weights/model_config.json` 读取，不需要手动传 m0 的一长串结构参数。

## 依赖

运行环境需要安装：

- `torch`
- `torch_geometric`
- `numpy`
- `mne`
- `scikit-learn`


## 调用方式

Python 调用：

```python
from pathlib import Path
from deepreject import DeepRejectPredictor

predictor = DeepRejectPredictor(device="cuda")
pred = predictor.predict_fif(
    Path("/path/to/sub-xx_preprocessed.fif"),
)

print(pred.backend)
print(pred.artifact_probs)
print(pred.bad_intervals)
print(pred.bad_channel_probs)
```

CPU 推理：

```python
predictor = DeepRejectPredictor(device="cpu")
```

GPU 推理：

```python
predictor = DeepRejectPredictor(device="cuda")
```

## 参数说明

- `device`: `cpu`、`cuda` 或 `gpu`。
- `backend`: 仅支持 `torch` 或 `auto`，两者等价。
- `ckpt_path`: 可替换为其他 `best.pt`。
- `model_config_path`: 可替换为对应 `model_config.json`。
- `batch_size`: 默认 `0`，表示整条 recording 一次输入模型，保留训练时 temporal context。若显存不足，可设置为正整数按窗口切块，但会改变长程上下文。

## 输出

`predict_fif(...)` 返回 `DeepRejectPrediction`：

- `artifact_logits`: 每个窗口的坏段 logits。
- `artifact_probs`: 每个窗口为坏段的概率。
- `artifact_pred`: 每个窗口的坏段预测标签。
- `bad_channel_logits`: 每个通道的坏道 logits。
- `bad_channel_probs`: 每个通道为坏道的概率。
- `bad_channel_pred`: 每个通道的坏道预测标签。
- `bad_intervals`: 合并后的坏段时间区间。
- `ch_names`: FIF 中的 MEG 通道名。


