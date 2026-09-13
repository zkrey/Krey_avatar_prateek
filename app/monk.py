"""
Monk Skin Tone (MST) classification — the deterministic core of Service A, slice 1.

No ML training. Given clean skin-pixel samples, we:
  1. convert each sample sRGB -> CIELAB (perceptually uniform; a delta of ~10 LAB
     units is roughly one 'just noticeable difference' on a mobile screen),
  2. take the robust (median) LAB reading across samples,
  3. map to the nearest of the 10 Monk swatches by ΔE2000 (CIEDE2000, perceptually uniform),
  4. derive a confidence from how tightly the samples agree AND how close the reading sits
     to a real swatch — an off-locus reading (large ΔE2000) is low-confidence / needs confirm.

This mirrors the Capture Pipeline Spec, section 4.1: LAB space, lighting-weighted
aggregation, and "flag for user confirmation if std deviation > 15 LAB units".
"""
from __future__ import annotations
from typing import Sequence, Tuple
import math

RGB = Tuple[int, int, int]

# Monk Skin Tone Scale — the 10 published reference swatches (MST 1 = lightest).
MONK_SWATCHES: dict[int, RGB] = {
    1: (246, 237, 228),
    2: (243, 231, 219),
    3: (247, 234, 208),
    4: (234, 218, 186),
    5: (215, 189, 150),
    6: (160, 126, 86),
    7: (130, 92, 67),
    8: (96, 65, 52),
    9: (58, 49, 42),
    10: (41, 36, 32),
}

# Dispersion (in LAB units) above which we ask the user to confirm — spec 4.1.
CONFIRM_THRESHOLD = 15.0

# Per-photo confidence floor (spec §6). Below this we also ask the user to confirm,
# even when dispersion is under CONFIRM_THRESHOLD — a shaky single-photo reading is
# exactly what the 5-photo aggregation is meant to rescue.
CONFIDENCE_FLOOR = 0.65

# ΔE2000 distance to the NEAREST swatch beyond which the reading sits "off-locus" — it
# doesn't correspond to any real Monk tone (odd lighting, a non-skin patch, white-balance
# cast). A real skin tone that merely falls *between* two swatches stays well under this;
# only genuinely-off reads exceed it, so it lowers confidence and can trip a confirm.
# (Quantisation distance to a bucket centre; true error-vs-reality needs ground truth —
# docs/recognition_thresholds.md.) Provisional; recalibrate on real flag data.
OFF_SWATCH_DE = 10.0

# D65 reference white.
_XN, _YN, _ZN = 95.047, 100.0, 108.883


def _srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def rgb_to_lab(rgb: RGB) -> Tuple[float, float, float]:
    """sRGB (0-255) -> CIELAB (D65)."""
    r, g, b = (_srgb_to_linear(v) for v in rgb)
    # linear sRGB -> XYZ (D65), scaled to 0-100
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) * 100.0
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b) * 100.0
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) * 100.0

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x / _XN), f(y / _YN), f(z / _ZN)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bb = 200 * (fy - fz)
    return (L, a, bb)


def delta_e76(lab1, lab2) -> float:
    """CIE76 colour difference (plain Euclidean in LAB). Kept as a fast fallback; skin
    matching uses delta_e2000, which is perceptually uniform where CIE76 is not."""
    return math.dist(lab1, lab2)


def delta_e2000(lab1, lab2, kL: float = 1.0, kC: float = 1.0, kH: float = 1.0) -> float:
    """CIEDE2000 colour difference — the modern, perceptually-uniform ΔE. Matters for skin,
    where CIE76 over/under-states differences. Deterministic, stdlib-only. JND ≈ 1; ΔE ≲ 2–3
    reads as an accurate skin match (docs/recognition_thresholds.md)."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1 = math.hypot(a1, b1)
    C2 = math.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0
    Cbar7 = Cbar ** 7
    G = 0.5 * (1 - math.sqrt(Cbar7 / (Cbar7 + 25.0 ** 7))) if Cbar > 0 else 0.0
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    else:
        dh = h2p - h1p
        if dh > 180:
            dh -= 360
        elif dh < -180:
            dh += 360
        dhp = dh
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2.0)

    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0
    if C1p * C2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2.0
    elif (h1p + h2p) < 360:
        hbarp = (h1p + h2p + 360) / 2.0
    else:
        hbarp = (h1p + h2p - 360) / 2.0

    T = (1 - 0.17 * math.cos(math.radians(hbarp - 30))
         + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6))
         - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    dTheta = 30 * math.exp(-(((hbarp - 275) / 25.0) ** 2))
    Cbarp7 = Cbarp ** 7
    Rc = 2 * math.sqrt(Cbarp7 / (Cbarp7 + 25.0 ** 7)) if Cbarp > 0 else 0.0
    Sl = 1 + (0.015 * (Lbarp - 50) ** 2) / math.sqrt(20 + (Lbarp - 50) ** 2)
    Sc = 1 + 0.045 * Cbarp
    Sh = 1 + 0.015 * Cbarp * T
    Rt = -math.sin(math.radians(2 * dTheta)) * Rc
    return math.sqrt(
        (dLp / (kL * Sl)) ** 2
        + (dCp / (kC * Sc)) ** 2
        + (dHp / (kH * Sh)) ** 2
        + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh))
    )


# Precompute swatch LABs once.
_SWATCH_LAB = {k: rgb_to_lab(v) for k, v in MONK_SWATCHES.items()}


def _median_lab(labs: Sequence[Tuple[float, float, float]]):
    n = len(labs)
    out = []
    for ch in range(3):
        vals = sorted(x[ch] for x in labs)
        mid = n // 2
        out.append(vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2)
    return tuple(out)


def _dispersion(labs: Sequence[Tuple[float, float, float]]) -> float:
    """Combined LAB spread across samples (0 = perfect agreement)."""
    if len(labs) < 2:
        return 0.0
    means = [sum(x[ch] for x in labs) / len(labs) for ch in range(3)]
    var = [sum((x[ch] - means[ch]) ** 2 for x in labs) / len(labs) for ch in range(3)]
    return math.sqrt(sum(var))  # magnitude of the per-channel std vector


def _continuous_monk(reading_L: float) -> float:
    """
    Fractional Monk position (e.g. 5.9 vs 6.6) by interpolating the reading's L* against
    the swatch lightness curve. The integer `value` rounds to the nearest bucket, which is
    coarse — two genuinely different shades can share a bucket. This keeps the sub-bucket
    difference so it survives into render and aggregation (bucket is a display label only).
    """
    idxs = sorted(_SWATCH_LAB)                       # 1..10
    Ls = [_SWATCH_LAB[i][0] for i in idxs]           # swatch L*, decreasing with index
    if reading_L >= Ls[0]:
        return float(idxs[0])
    if reading_L <= Ls[-1]:
        return float(idxs[-1])
    for k in range(len(idxs) - 1):
        L_hi, L_lo = Ls[k], Ls[k + 1]
        if L_lo <= reading_L <= L_hi:
            frac = (L_hi - reading_L) / (L_hi - L_lo + 1e-9)
            return round(idxs[k] + frac * (idxs[k + 1] - idxs[k]), 2)
    return float(min(_SWATCH_LAB, key=lambda i: abs(_SWATCH_LAB[i][0] - reading_L)))


def _median_rgb(samples: Sequence[RGB]) -> RGB:
    return tuple(int(sorted(s[ch] for s in samples)[len(samples) // 2]) for ch in range(3))


def classify(samples: Sequence[RGB]) -> dict:
    """
    samples: list of clean skin-pixel RGBs (one representative pixel per patch).
    Returns a body_models-shaped skin-tone record (spec section 4, Service A contract).
    Carries BOTH the coarse Monk bucket (`value`) and the continuous tone the render
    engine should actually use (`lab`, `rgb`, `monk_continuous`).
    """
    if not samples:
        raise ValueError("no skin samples provided")

    labs = [rgb_to_lab(s) for s in samples]
    reading = _median_lab(labs)

    # Nearest Monk swatch by CIEDE2000 (perceptually uniform), and the ΔE2000 to it.
    value = min(_SWATCH_LAB, key=lambda k: delta_e2000(reading, _SWATCH_LAB[k]))
    delta = round(delta_e2000(reading, _SWATCH_LAB[value]), 2)

    dispersion = _dispersion(labs)
    # Confidence has TWO factors, both must hold:
    #   dispersion — do the sample patches agree? (tight -> high)
    #   fit        — does the reading sit near a real swatch? (off-locus ΔE -> low)
    # A tone that merely falls between swatches stays near 1.0; only a genuinely-off read
    # (delta past OFF_SWATCH_DE) pulls fit down and can trip the confirm.
    disp_conf = max(0.0, 1.0 - dispersion / 30.0)
    fit_conf = max(0.0, 1.0 - max(0.0, delta - OFF_SWATCH_DE) / 15.0)
    confidence = max(0.30, min(0.99, disp_conf * fit_conf))
    # Confirm on high spread, an off-locus reading, OR a sub-floor confidence (spec §6).
    needs_confirm = (dispersion > CONFIRM_THRESHOLD
                     or delta > OFF_SWATCH_DE
                     or confidence < CONFIDENCE_FLOOR)

    return {
        "value": value,                          # Monk bucket 1..10 (coarse display label)
        "monk_continuous": _continuous_monk(reading[0]),  # fractional shade (render/aggregation)
        "lab": [round(c, 1) for c in reading],   # measured skin colour — what render draws with
        "rgb": list(_median_rgb(samples)),
        "confidence": round(confidence, 3),
        "confirmed_by_user": False,
        "delta_e": delta,                        # ΔE2000 to the nearest swatch centre
        "delta_e_method": "ciede2000",
        "dispersion_lab": round(dispersion, 2),  # sample spread
        "needs_confirm": needs_confirm,          # -> frontend confirm swatch
        "n_samples": len(samples),
        "model": "deterministic-lab-mst-v1",     # v1: CIEDE2000 match + off-swatch fit factor
    }
