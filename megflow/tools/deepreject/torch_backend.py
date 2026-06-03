# -*- coding: utf-8 -*-
"""Torch backend for standalone DeepReject inference."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

from .model.dataset import collate_fn_for_artifact_detection
from .model.deepreject import DeepReject

from .config import deepreject_kwargs_from_config, load_model_config


def load_torch_model(
    ckpt_path: Path,
    model_config_path: Path,
    *,
    device: torch.device,
    encoder_chunk_size: Optional[int] = None,
) -> DeepReject:
    config = load_model_config(Path(model_config_path))
    kwargs = deepreject_kwargs_from_config(config)
    if encoder_chunk_size is not None:
        kwargs["encoder_chunk_size"] = encoder_chunk_size if encoder_chunk_size > 0 else None
    model = DeepReject(**kwargs).to(device)
    try:
        state = torch.load(Path(ckpt_path), map_location=device, weights_only=True)
    except TypeError:
        state = torch.load(Path(ckpt_path), map_location=device)
    model.load_state_dict(state)
    model.eval()
    return model


@torch.no_grad()
def predict_data_list_torch(
    model: torch.nn.Module,
    data_list: List[Any],
    *,
    device: torch.device,
    batch_size: int = 32,
) -> Tuple[np.ndarray, Optional[np.ndarray], np.ndarray, Optional[np.ndarray]]:
    """Return artifact logits/probs and bad-channel logits/probs for one recording."""
    model.eval()
    all_art_logits: List[torch.Tensor] = []
    all_bad_logits: List[torch.Tensor] = []
    mod = model.module if hasattr(model, "module") else model
    use_bad = bool(getattr(mod, "use_bad_channel_head", False) and mod.bad_channel_head is not None)

    chunk_size = len(data_list) if int(batch_size) <= 0 else int(batch_size)
    for start in range(0, len(data_list), chunk_size):
        end = min(start + chunk_size, len(data_list))
        batch_data = data_list[start:end]
        pyg_batch, _, recording_lengths = collate_fn_for_artifact_detection([(batch_data, None)])
        pyg_batch = pyg_batch.to(device)
        logits_list, bad_list, _ = model(
            pyg_batch,
            recording_lengths=recording_lengths,
            return_bad_channel_logits=use_bad,
            return_pre_logit_embedding=False,
        )
        all_art_logits.append(torch.cat(logits_list, dim=0).detach().cpu())
        if bad_list is not None:
            all_bad_logits.extend([x.detach().float().cpu() for x in bad_list])

    if all_art_logits:
        art_logits_t = torch.cat(all_art_logits, dim=0)
    else:
        art_logits_t = torch.empty((0, 2), dtype=torch.float32)
    art_probs = F.softmax(art_logits_t, dim=-1)[:, 1].numpy().astype(np.float32)

    bad_logits_np: Optional[np.ndarray] = None
    bad_probs: Optional[np.ndarray] = None
    if all_bad_logits:
        bad_logits_t = torch.stack(all_bad_logits, dim=0).mean(dim=0)
        bad_logits_np = bad_logits_t.numpy().astype(np.float32)
        bad_probs = F.softmax(bad_logits_t, dim=-1)[:, 1].numpy().astype(np.float32)

    return art_logits_t.numpy().astype(np.float32), bad_logits_np, art_probs, bad_probs
