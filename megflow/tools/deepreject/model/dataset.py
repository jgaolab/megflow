# -*- coding: utf-8 -*-
"""
RecordingDataset_ArtifactDetection 与 collate_fn_for_artifact_detection。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, Tuple, FrozenSet
from pathlib import Path

try:
    import torch
    from torch.utils.data import Dataset
    from torch_geometric.data import Data, Batch
except ImportError:
    Dataset = object


class RecordingDataset_ArtifactDetection(Dataset):
    """
    每个 item 为一条记录：(recording_data_list, recording_window_labels)。
    recording_data_list: List[Data]，每个 Data 对应 1 秒窗口；
    recording_window_labels: (L,) 窗口级伪迹标签 0/1。
    """

    def __init__(
        self,
        recordings: List[List[Data]],
        labels: Optional[List[torch.Tensor]] = None,
    ):
        """
        recordings: list of list of Data；labels: list of (L,) tensor，若为 None 则仅推理。
        """

        self.recordings = recordings
        self.labels = labels
        if labels is not None:
            assert len(recordings) == len(labels)

    def __len__(self) -> int:
        return len(self.recordings)

    def __getitem__(self, idx: int) -> Tuple[List[Data], Optional[torch.Tensor]]:
        rec = self.recordings[idx]
        lab = self.labels[idx] if self.labels is not None else None
        return rec, lab


class RecordingFileManifestDataset(Dataset):
    """
    图缓存：默认 clean_ratio=2 为 graph_cache/unified/manifest.tsv，否则多为 unified_c<ratio>/（或 --graph-unified-subdir），
    第 0 列为相对 manifest 所在目录的 .pt 路径；
    第 3 列为 dataset，第 4 列为 filename（与 demographic FileName 一致）。
    训练时可用 dataset_allowlist（按数据集名过滤），或 recording_key_allowlist（(dataset, filename) 精确到条，供 multilabel kfold）。
    二者勿同时传入；recording_key_allowlist 优先。
    """

    def __init__(
        self,
        manifest_path: str,
        *,
        root_dir: Optional[str] = None,
        dataset_allowlist: Optional[Set[str]] = None,
        recording_key_allowlist: Optional[Set[Tuple[str, str]]] = None,
    ):
        mp = Path(manifest_path)
        self.manifest_path = str(mp)
        self.root = Path(root_dir) if root_dir is not None else mp.parent
        self._rel_paths: List[str] = []
        self._lines: List[str] = []
        keys: Optional[FrozenSet[Tuple[str, str]]] = None
        if recording_key_allowlist is not None:
            keys = frozenset(
                (str(a).strip(), str(b).strip()) for a, b in recording_key_allowlist
            )
        allow = dataset_allowlist
        with mp.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                if keys is not None:
                    if len(parts) < 4:
                        continue
                    rec_key = (parts[2].strip(), parts[3].strip())
                    if rec_key not in keys:
                        continue
                elif allow is not None and len(parts) >= 3:
                    if parts[2].strip() not in allow:
                        continue
                self._rel_paths.append(parts[0])
                self._lines.append(line)

    def __len__(self) -> int:
        return len(self._rel_paths)

    def lines_at_indices(self, indices: List[int]) -> List[str]:
        return [self._lines[i] for i in indices if 0 <= i < len(self._lines)]

    def dataset_id_at(self, idx: int) -> str:
        """manifest 第 3 列（0-based 索引 2）为 dataset id；缺失时返回空串。"""
        if idx < 0 or idx >= len(self._lines):
            return ""
        parts = self._lines[idx].split("\t")
        if len(parts) >= 3:
            return parts[2].strip()
        return ""

    def n_windows_at(self, idx: int) -> int:
        """manifest 第 2 列（索引 1）为窗口数；缺失或解析失败返回 0。"""
        if idx < 0 or idx >= len(self._lines):
            return 0
        parts = self._lines[idx].split("\t")
        if len(parts) >= 2:
            try:
                return int(parts[1].strip())
            except ValueError:
                return 0
        return 0

    def __getitem__(self, idx: int) -> Tuple[List[Data], torch.Tensor]:
        rel = self._rel_paths[idx]
        full_path = str(self.root / rel)
        obj = torch.load(full_path, map_location="cpu")
        data_list: List[Data] = obj["data_list"]
        labels: torch.Tensor = obj["labels"]
        return data_list, labels


class RecordingDatasetWithHardExtra(Dataset):
    """
    在「每条样本为整段 recording」的 Dataset 上追加 hard negative 项：
    下标 [0, len(base)) 与 base 一致；[len(base), ...) 为单窗伪 recording，(rec_idx, win_idx) 来自 base。
    """

    def __init__(self, base_dataset: Dataset, hard_pairs: List[Tuple[int, int]]):
        self.base = base_dataset
        self.hard_pairs: List[Tuple[int, int]] = list(hard_pairs)

    def __len__(self) -> int:
        return len(self.base) + len(self.hard_pairs)

    def __getitem__(self, idx: int) -> Tuple[List[Data], Optional[torch.Tensor]]:
        if idx < len(self.base):
            return self.base[idx]
        rec_i, win_i = self.hard_pairs[idx - len(self.base)]
        rec_list, lab = self.base[rec_i]
        one = rec_list[win_i]
        sl = lab[win_i : win_i + 1]
        return [one], sl


def _dataset_n_windows(ds: Dataset, idx: int) -> int:
    """Best-effort 获取一条 recording 的窗口数，优先读 manifest 元数据，避免加载 .pt。"""
    if hasattr(ds, "n_windows_at"):
        try:
            return int(ds.n_windows_at(idx))  # type: ignore[attr-defined]
        except Exception:
            pass
    if hasattr(ds, "indices") and hasattr(ds, "dataset"):
        try:
            base_idx = int(ds.indices[idx])  # type: ignore[attr-defined]
            return _dataset_n_windows(ds.dataset, base_idx)  # type: ignore[attr-defined]
        except Exception:
            pass
    rec_list, _ = ds[idx]
    return int(len(rec_list))


class RecordingWindowChunkDataset(Dataset):
    """
    训练时将过长 recording 按窗口维切成 pseudo-recordings。

    主要用于图缓存 manifest 路径：缓存文件可保持原样，训练 DataLoader 只接收
    不超过 max_windows_per_chunk 的片段，从而降低 GNN/Transformer/backward 显存峰值。
    """

    def __init__(self, base: Dataset, max_windows_per_chunk: int):
        self.base = base
        self.max_windows_per_chunk = int(max_windows_per_chunk)
        if self.max_windows_per_chunk <= 0:
            raise ValueError("max_windows_per_chunk 须 > 0")
        self._spans: List[Tuple[int, int, int]] = []
        for rec_idx in range(len(base)):
            n_win = _dataset_n_windows(base, rec_idx)
            if n_win <= 0:
                continue
            start = 0
            while start < n_win:
                end = min(start + self.max_windows_per_chunk, n_win)
                self._spans.append((rec_idx, start, end))
                start = end

    def __len__(self) -> int:
        return len(self._spans)

    def __getitem__(self, idx: int) -> Tuple[List[Data], Optional[torch.Tensor]]:
        rec_idx, start, end = self._spans[idx]
        rec_list, lab = self.base[rec_idx]
        rec_chunk = rec_list[start:end]
        lab_chunk = lab[start:end] if lab is not None else None
        return rec_chunk, lab_chunk


def collate_fn_for_artifact_detection(
    batch: List[Tuple[List[Data], Optional[torch.Tensor]]],
) -> Tuple[Batch, Optional[torch.Tensor], List[int]]:
    """
    将多条记录打包为一个 PyG Batch（所有窗口子图合并），并返回：
    - batch: Batch，含 edge_index, batch, ptr, x_raw, x_raw_scale（每节点一系数）, (y_bad_channel), (node_valid)；
    - labels: (total_windows,) 所有窗口标签拼接，pad 用 -1 或保持为各记录拼接（无 pad）；
    - recording_lengths: [L1, L2, ...] 每条记录的窗口数。

    DataLoader 中每批多条记录时，Batch 内子图顺序为 rec0_w0, rec0_w1, ..., rec1_w0, ...
    """

    all_data: List[Data] = []
    all_labels: List[torch.Tensor] = []
    recording_lengths: List[int] = []
    for rec_list, lab in batch:
        all_data.extend(rec_list)
        recording_lengths.append(len(rec_list))
        if lab is not None:
            all_labels.append(lab)
    pyg_batch = Batch.from_data_list(all_data)
    if all_labels:
        labels_tensor = torch.cat(all_labels, dim=0)
    else:
        labels_tensor = None
    return pyg_batch, labels_tensor, recording_lengths


def _x_raw_chans_times(x_raw: "torch.Tensor") -> Tuple[int, int]:
    if x_raw.dim() == 2:
        return int(x_raw.shape[0]), int(x_raw.shape[1])
    if x_raw.dim() == 3:
        return int(x_raw.shape[0]), int(x_raw.shape[2])
    raise ValueError("x_raw 维数异常: %s" % (tuple(x_raw.shape),))


def max_chans_times_over_recording_dataset(ds: Dataset) -> Tuple[int, int]:
    """遍历「每条样本 = 一整段 recording」的 Dataset，取所有窗口 x_raw 的最大 (C, T)。"""
    max_c, max_t = 0, 0
    n = len(ds)
    for i in range(n):
        rec_list, _ = ds[i]
        for d in rec_list:
            c, t = _x_raw_chans_times(d.x_raw)
            max_c = max(max_c, c)
            max_t = max(max_t, t)
    return max_c, max_t


def max_chans_times_over_datasets(*datasets: Dataset) -> Tuple[int, int]:
    mc, mt = 0, 0
    for ds in datasets:
        if len(ds) == 0:
            continue
        c, t = max_chans_times_over_recording_dataset(ds)
        mc = max(mc, c)
        mt = max(mt, t)
    return mc, mt


def scaled_window_tensors_from_pyg_batch(
    batch: Batch,
    *,
    pad_n_chans: Optional[int] = None,
    pad_n_times: Optional[int] = None,
) -> "torch.Tensor":
    """
    将 DeepReject 用的 PyG Batch（每窗口一子图，节点=通道）还原为 BIOT 输入：
    (n_windows, n_chans, n_times)，与训练时 x_raw * x_raw_scale（按通道）一致。

    若给定 pad_n_chans / pad_n_times，每个窗口先乘 scale 再 **零填充** 到固定 (C,T)，
    以便同一 batch 内多 recording、通道/时间长度不一致时可 torch.cat。
    """
    import torch

    if not hasattr(batch, "ptr") or batch.ptr is None:
        raise ValueError("Batch 需含 ptr（from_data_list 拼接的多子图）")
    if not hasattr(batch, "x_raw") or batch.x_raw is None:
        raise ValueError("Batch 需含 x_raw")
    if not hasattr(batch, "x_raw_scale") or batch.x_raw_scale is None:
        raise ValueError("Batch 需含 x_raw_scale")
    ptr = batch.ptr
    n_g = int(batch.num_graphs)
    parts = []
    for g in range(n_g):
        s, e = int(ptr[g]), int(ptr[g + 1])
        xr = batch.x_raw[s:e]
        if xr.dim() == 3:
            xr = xr[:, 0, :]
        sc = batch.x_raw_scale[s:e].view(-1, 1).to(dtype=xr.dtype)
        xw = xr * sc
        if pad_n_chans is not None and pad_n_times is not None:
            c, t = int(xw.shape[0]), int(xw.shape[1])
            if c > pad_n_chans or t > pad_n_times:
                raise ValueError(
                    f"窗口形状 ({c},{t}) 超过 pad ({pad_n_chans},{pad_n_times})，"
                    "请增大扫描上限或 --biot-pad-chans / --biot-pad-times"
                )
            padded = xw.new_zeros((pad_n_chans, pad_n_times))
            padded[:c, :t] = xw
            xw = padded
        parts.append(xw.unsqueeze(0))
    return torch.cat(parts, dim=0)


def collate_fn_for_biot(
    batch: List[Tuple[List[Data], Optional[torch.Tensor]]],
) -> Tuple["torch.Tensor", Optional[torch.Tensor], List[int]]:
    """
    与 collate_fn_for_artifact_detection 相同数据源，输出 (x_biot, labels, recording_lengths)。
    x_biot: (total_windows_in_batch, n_chans, n_times)。要求 batch 内各窗口 C、T 一致。
    """
    pyg_batch, labels_tensor, recording_lengths = collate_fn_for_artifact_detection(batch)
    x_biot = scaled_window_tensors_from_pyg_batch(pyg_batch)
    return x_biot, labels_tensor, recording_lengths


def make_collate_fn_biot_padded(pad_n_chans: int, pad_n_times: int):
    """返回 collate，将各窗口 pad 到固定 (pad_n_chans, pad_n_times)，供 BIOT 固定输入维。"""

    def _collate(
        batch: List[Tuple[List[Data], Optional[torch.Tensor]]],
    ) -> Tuple["torch.Tensor", Optional[torch.Tensor], List[int]]:
        pyg_batch, labels_tensor, recording_lengths = collate_fn_for_artifact_detection(batch)
        x_biot = scaled_window_tensors_from_pyg_batch(
            pyg_batch, pad_n_chans=pad_n_chans, pad_n_times=pad_n_times
        )
        return x_biot, labels_tensor, recording_lengths

    return _collate


def make_collate_fn_brainomni_padded(
    pad_n_chans: int,
    pad_n_times: int,
    scale_mag: float,
    scale_grad: float,
):
    """
    与 BIOT 相同 PyG 源，输出 BrainOmni ``encode`` 所需字典：
    ``x`` (B, C, T)、``pos`` (B, C, 6)、``sensor_type`` (B, C) long。
    无 ``meg_ch_pos`` 的旧图缓存时位置用零，``sensor_type`` 仍由 ``x_raw_scale`` 相对 meg/grad 系数推断。
    """

    import torch

    sm = float(scale_mag)
    sg = float(scale_grad)

    def _norm_pos6_xyz(pos6: "torch.Tensor") -> "torch.Tensor":
        p = pos6.clone()
        xyz = p[:, :3]
        mean = xyz.mean(dim=0, keepdim=True)
        xyz = xyz - mean
        scale = torch.sqrt(3 * (xyz * xyz).sum(1).mean()).clamp(min=1e-8)
        p[:, :3] = xyz / scale
        return p

    def _sensor_type_1d(sc: "torch.Tensor") -> "torch.Tensor":
        c = sc.reshape(-1).float()
        dm = (c - sm).abs()
        dg = (c - sg).abs()
        return torch.where(dg < dm, torch.full_like(c, 2, dtype=torch.long), torch.full_like(c, 1, dtype=torch.long))

    def _collate(
        batch: List[Tuple[List[Data], Optional[torch.Tensor]]],
    ) -> Tuple[Dict[str, "torch.Tensor"], Optional["torch.Tensor"], List[int]]:
        pyg_batch, labels_tensor, recording_lengths = collate_fn_for_artifact_detection(batch)
        if not hasattr(pyg_batch, "ptr") or pyg_batch.ptr is None:
            raise ValueError("Batch 需含 ptr")
        if not hasattr(pyg_batch, "x_raw") or pyg_batch.x_raw is None:
            raise ValueError("Batch 需含 x_raw")
        if not hasattr(pyg_batch, "x_raw_scale") or pyg_batch.x_raw_scale is None:
            raise ValueError("Batch 需含 x_raw_scale")
        ptr = pyg_batch.ptr
        n_g = int(pyg_batch.num_graphs)
        meg_pos = getattr(pyg_batch, "meg_ch_pos", None)
        xs: List["torch.Tensor"] = []
        ps: List["torch.Tensor"] = []
        sts: List["torch.Tensor"] = []
        for g in range(n_g):
            s, e = int(ptr[g]), int(ptr[g + 1])
            xr = pyg_batch.x_raw[s:e]
            if xr.dim() == 3:
                xr = xr[:, 0, :]
            sc = pyg_batch.x_raw_scale[s:e].view(-1)
            xw = xr * sc.view(-1, 1).to(dtype=xr.dtype)
            c_i, t_i = int(xw.shape[0]), int(xw.shape[1])
            if c_i > pad_n_chans or t_i > pad_n_times:
                raise ValueError(
                    f"窗口 ({c_i},{t_i}) 超过 pad ({pad_n_chans},{pad_n_times})，"
                    "请增大 --brainomni-pad-chans / --brainomni-pad-times"
                )
            if meg_pos is not None:
                pos3 = meg_pos[s:e].float().to(device=xw.device, dtype=xw.dtype)
            else:
                pos3 = xw.new_zeros((c_i, 3))
            pos6 = xw.new_zeros((c_i, 6))
            pos6[:, :3] = pos3
            pos6 = _norm_pos6_xyz(pos6)
            st = _sensor_type_1d(sc).to(device=xw.device)
            xpad = xw.new_zeros((pad_n_chans, pad_n_times))
            xpad[:c_i, :t_i] = xw
            ppad = xw.new_zeros((pad_n_chans, 6))
            ppad[:c_i] = pos6
            stpad = torch.zeros(pad_n_chans, dtype=torch.long, device=xw.device)
            stpad[:c_i] = st
            stpad[c_i:] = 1
            xs.append(xpad.unsqueeze(0))
            ps.append(ppad.unsqueeze(0))
            sts.append(stpad.unsqueeze(0))
        # BrainOmni SEANet 在 CUDA 上对 float64 的 conv/pad 易触发 invalid configuration；与预训练一致用 float32
        out = {
            "x": torch.cat(xs, dim=0).float(),
            "pos": torch.cat(ps, dim=0).float(),
            "sensor_type": torch.cat(sts, dim=0),
        }
        return out, labels_tensor, recording_lengths

    return _collate
