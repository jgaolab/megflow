# DeepReject Standalone Inference

`deepreject_inference/` 是一个可独立拷贝的 DeepReject runtime 推理包。它只使用已经导出的 ONNX/OpenVINO artifact，不加载 Torch 训练权重，也不需要 DeepReject Torch 模型源码。


## Runtime 必要文件

拷贝部署时，至少保留这些文件/目录：

- `__init__.py`
- `runtime.py`
- `accelerated.py`
- `postprocess.py`
- `preprocessing.py`

以及已验证的导出物：

- `exported/<model_name>_fold<k>/model.onnx`
- `exported/<model_name>_fold<k>/openvino/model.xml`
- `exported/<model_name>_fold<k>/openvino/model.bin`
- `exported/<model_name>_fold<k>/metadata.json`

如果只用 `predict_inputs(...)`，runtime 环境需要 `numpy`、`onnxruntime` / `onnxruntime-gpu`、`openvino`。如果使用 `predict_fif(...)`，还需要 `mne` 和 `scikit-learn`。


## Runtime 调用

把 `deepreject_inference/` 的父目录加入 `PYTHONPATH`，然后：

```python
from pathlib import Path
from deepreject_inference import DeepRejectPredictor

predictor = DeepRejectPredictor(device="cuda", backend="auto")
pred = predictor.predict_fif(
    Path("/path/to/sub-xx_preprocessed.fif"),
    category="task",
    dataset="1_26723708",
)

print(pred.backend)
print(pred.artifact_probs)
print(pred.bad_intervals)
print(pred.bad_channel_probs)
```

如果其他代码已经构造好导出模型所需的 numpy 输入字典：

```python
pred = predictor.predict_inputs(inputs)
```

## 后端策略

`backend="auto"` 的优先级：

- 检测到 GPU 且 ONNX 导出物已通过数值验证：使用 ONNX Runtime GPU。
- 否则，检测到 Intel/x86 CPU 且 OpenVINO 导出物已通过数值验证：使用 OpenVINO。
- 否则，使用已通过数值验证的 ONNX Runtime CPU。
- 如果导出物缺失、未验证或当前输入 shape 不匹配，会抛出明确错误；runtime 不提供 Torch fallback。

显式指定：

- `backend="torch"`：runtime 不支持，会报错。
- `backend="onnx"`：优先 ONNX Runtime；`device="cuda"` 时尝试 ONNX Runtime GPU。
- `backend="openvino"`：尝试 OpenVINO CPU。