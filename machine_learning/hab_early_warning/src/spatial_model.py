"""A small U-Net over the Arabian Sea HAB grid — see `spatial_dataset.py` and
TODO.md's "ConvLSTM / U-Net for spatial forecasting" for why this exists.

Three downsampling levels, not deeper: the padded grid is 72x48 pixels
(`spatial_dataset.PAD_LAT`/`PAD_LON`), and three stride-2 pools reach a 9x6
bottleneck — a fourth would try to pool a single-digit dimension. GroupNorm
rather than BatchNorm: training batches here are small (tens of frames, not
hundreds), and BatchNorm's running statistics are unreliable at that size.
"""

from __future__ import annotations

import torch
from torch import nn


def resolve_device() -> torch.device:
    """MPS on this Apple Silicon machine when available, else CPU. The grid
    is small enough (72x48 px) that neither needs a discrete GPU."""
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _block(in_channels: int, out_channels: int, groups: int = 8) -> nn.Sequential:
    groups = min(groups, out_channels)
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1),
        nn.GroupNorm(groups, out_channels),
        nn.ReLU(inplace=True),
        nn.Conv2d(out_channels, out_channels, kernel_size=3, padding=1),
        nn.GroupNorm(groups, out_channels),
        nn.ReLU(inplace=True),
    )


class SpatialBloomUNet(nn.Module):
    """Per-pixel bloom-probability logits from a multi-channel ocean-state
    "image" — one frame in, one mask out, no temporal recurrence (that is
    the deferred ConvLSTM half; see the plan's "Deferred" section)."""

    def __init__(self, in_channels: int, base_channels: int = 16):
        super().__init__()
        c1, c2, c3, c4 = base_channels, base_channels * 2, base_channels * 4, base_channels * 8

        self.enc1 = _block(in_channels, c1)
        self.enc2 = _block(c1, c2)
        self.enc3 = _block(c2, c3)
        self.bottleneck = _block(c3, c4)

        self.pool = nn.MaxPool2d(2)
        self.up3 = nn.ConvTranspose2d(c4, c3, kernel_size=2, stride=2)
        self.dec3 = _block(c3 + c3, c3)
        self.up2 = nn.ConvTranspose2d(c3, c2, kernel_size=2, stride=2)
        self.dec2 = _block(c2 + c2, c2)
        self.up1 = nn.ConvTranspose2d(c2, c1, kernel_size=2, stride=2)
        self.dec1 = _block(c1 + c1, c1)

        self.head = nn.Conv2d(c1, 1, kernel_size=1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        s1 = self.enc1(x)
        s2 = self.enc2(self.pool(s1))
        s3 = self.enc3(self.pool(s2))
        bottleneck = self.bottleneck(self.pool(s3))

        d3 = self.dec3(torch.cat([self.up3(bottleneck), s3], dim=1))
        d2 = self.dec2(torch.cat([self.up2(d3), s2], dim=1))
        d1 = self.dec1(torch.cat([self.up1(d2), s1], dim=1))

        return self.head(d1).squeeze(1)  # (B, H, W) logits


def masked_focal_loss(
    logits: torch.Tensor,
    target: torch.Tensor,
    valid: torch.Tensor,
    alpha: float = 0.25,
    gamma: float = 2.0,
) -> torch.Tensor:
    """Focal loss (Lin et al. 2017), masked to real labelled ocean cells.

    Plain BCE would let ~90% negatives dominate the gradient for a ~9.7%
    positive rate (`hab_early_warning/readme.md`'s measured bloom rate) —
    the same imbalance the tabular model handles with `class_weight=
    "balanced"`. `valid` excludes padding and cells with no `bloom_t3` label
    (structural NaN from the t+3 shift, or land) — those must contribute
    exactly zero gradient, not a downweighted one.
    """
    prob = torch.sigmoid(logits)
    bce = nn.functional.binary_cross_entropy_with_logits(logits, target, reduction="none")
    p_t = prob * target + (1 - prob) * (1 - target)
    alpha_t = alpha * target + (1 - alpha) * (1 - target)
    loss = alpha_t * (1 - p_t).pow(gamma) * bce

    valid = valid.to(loss.dtype)
    denominator = valid.sum().clamp_min(1.0)
    return (loss * valid).sum() / denominator
