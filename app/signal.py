"""Synthetic industrial sound signatures and lightweight signal features."""
from __future__ import annotations

import io
import wave
from typing import Dict, Tuple

import numpy as np

FAULTS = {
    "normal": {"label": "正常", "severity": "正常", "color": "#22c55e"},
    "bearing_wear": {"label": "轴承磨损", "severity": "重度", "color": "#ef4444"},
    "bearing_outer": {"label": "轴承外圈故障", "severity": "重度", "color": "#ef4444"},
    "bearing_inner": {"label": "轴承内圈故障", "severity": "重度", "color": "#ef4444"},
    "imbalance": {"label": "转子不平衡", "severity": "轻度", "color": "#f59e0b"},
    "misalignment": {"label": "转子不对中", "severity": "中度", "color": "#f59e0b"},
    "gear_fault": {"label": "齿轮啮合异常", "severity": "重度", "color": "#ef4444"},
    "gear_broken": {"label": "齿轮断齿", "severity": "重度", "color": "#ef4444"},
    "looseness": {"label": "机械松动", "severity": "中度", "color": "#f59e0b"},
    "generator_fault": {"label": "发电机异常", "severity": "重度", "color": "#ef4444"},
    "yaw_fault": {"label": "偏航系统异常", "severity": "中度", "color": "#f59e0b"},
    "shaft_fault": {"label": "主轴异常", "severity": "重度", "color": "#ef4444"},
}

SAMPLE_RATE = 16_000
CLASS_NAMES = tuple(FAULTS)


def _tone(t: np.ndarray, hz: float, amplitude: float, phase: float = 0.0) -> np.ndarray:
    return amplitude * np.sin(2 * np.pi * hz * t + phase)


def synthesize(fault: str = "normal", duration: float = 2.0, seed: int | None = None) -> Tuple[np.ndarray, int]:
    """Create a deterministic-ish machine recording with class-specific signatures."""
    if fault not in FAULTS:
        raise ValueError(f"unsupported fault: {fault}")
    rng = np.random.default_rng(seed)
    n = max(2048, int(SAMPLE_RATE * duration))
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    speed = 120.0 * (1 + rng.normal(0, 0.012))
    signal = _tone(t, speed, 0.22) + _tone(t, speed * 2, 0.08, 0.4)

    if fault == "bearing_wear":
        # Repeated impacts excite a high-frequency resonance, a common bearing-wear cue.
        impact_hz = speed * 2.43
        impacts = np.zeros(n, dtype=np.float32)
        period = max(1, int(SAMPLE_RATE / impact_hz))
        for index in range(period // 2, n, period):
            width = min(160, n - index)
            impacts[index:index + width] += np.exp(-np.arange(width) / 26) * rng.uniform(0.5, 1.0)
        signal += 0.42 * impacts * np.sin(2 * np.pi * 3200 * t)
        signal += _tone(t, 3200, 0.10) + _tone(t, 6400, 0.05)
    elif fault == "bearing_outer":
        impacts = np.maximum(0, np.sin(2 * np.pi * speed * 3.05 * t)) ** 8
        signal += 0.43 * impacts * np.sin(2 * np.pi * 2800 * t) + _tone(t, 2800, 0.12)
    elif fault == "bearing_inner":
        impacts = np.maximum(0, np.sin(2 * np.pi * speed * 4.12 * t + 0.2)) ** 7
        signal += 0.46 * impacts * np.sin(2 * np.pi * 3900 * t) + _tone(t, 3900, 0.10)
    elif fault == "imbalance":
        signal += _tone(t, speed, 0.52, 0.1) + _tone(t, speed * 0.5, 0.09)
        signal *= 1 + 0.06 * np.sin(2 * np.pi * 2 * t)
    elif fault == "misalignment":
        signal += _tone(t, speed * 2, 0.45) + _tone(t, speed * 3, 0.18) + _tone(t, speed * 0.5, 0.12)
    elif fault == "gear_broken":
        mesh = speed * 10
        once_per_turn = np.maximum(0, np.sin(2 * np.pi * speed * t + 0.7)) ** 18
        signal += _tone(t, mesh, 0.28) + 0.50 * once_per_turn * np.sin(2 * np.pi * mesh * t)
    elif fault == "gear_fault":
        mesh = speed * 10
        signal += _tone(t, mesh, 0.44) + _tone(t, mesh - speed, 0.20) + _tone(t, mesh + speed, 0.20)
        signal += _tone(t, mesh * 2, 0.16, 0.7)
    elif fault == "looseness":
        signal += _tone(t, speed * 0.5, 0.30) + _tone(t, speed * 1.5, 0.24)
        signal += 0.10 * np.sign(np.sin(2 * np.pi * speed * t))
    elif fault == "generator_fault":
        signal += _tone(t, 50, 0.38) + _tone(t, 100, 0.27) + _tone(t, 150, 0.14)
        signal += 0.14 * np.sin(2 * np.pi * 50 * t) * np.sin(2 * np.pi * speed * t)
    elif fault == "yaw_fault":
        signal += _tone(t, 18, 0.45) + _tone(t, 36, 0.18) + _tone(t, speed * 0.25, 0.18)
    elif fault == "shaft_fault":
        signal += _tone(t, speed * 2, 0.38) + _tone(t, speed * 4, 0.27) + _tone(t, 2400, 0.15)

    # Slow environmental modulation plus broadband sensor noise.
    signal *= 0.92 + 0.08 * np.sin(2 * np.pi * 0.7 * t + rng.random())
    signal += rng.normal(0, 0.035, n).astype(np.float32)
    signal = signal / max(1.0, np.max(np.abs(signal))) * 0.92
    return signal.astype(np.float32), SAMPLE_RATE


def wav_bytes(signal: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    values = np.clip(signal, -1, 1)
    pcm = (values * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buffer.getvalue()


def read_wav(raw: bytes) -> Tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(raw), "rb") as wav:
        channels, width, sample_rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
        if width != 2:
            raise ValueError("仅支持 16-bit PCM WAV 文件")
        data = np.frombuffer(wav.readframes(frames), dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            data = data.reshape(-1, channels).mean(axis=1)
    return data, sample_rate


def _dct(values: np.ndarray, count: int) -> np.ndarray:
    index = np.arange(values.shape[-1])
    basis = np.cos(np.pi / values.shape[-1] * (index + 0.5) * np.arange(count)[:, None])
    return values @ basis.T


def extract_features(signal: np.ndarray, sample_rate: int = SAMPLE_RATE) -> Tuple[np.ndarray, Dict[str, float]]:
    """Extract compact log-spectrum/MFCC-like features without librosa."""
    signal = np.asarray(signal, dtype=np.float32)
    if signal.size < 1024:
        signal = np.pad(signal, (0, 1024 - signal.size))
    frame = 2048
    hop = 1024
    frames = []
    for start in range(0, max(1, signal.size - frame + 1), hop):
        chunk = signal[start:start + frame]
        if chunk.size < frame:
            chunk = np.pad(chunk, (0, frame - chunk.size))
        frames.append(chunk * np.hanning(frame))
    spectrum = np.abs(np.fft.rfft(np.asarray(frames), axis=1)) + 1e-7
    power = spectrum ** 2
    frequencies = np.fft.rfftfreq(frame, 1 / sample_rate)
    mean_power = power.mean(axis=0)
    total = float(mean_power.sum())
    centroid = float((frequencies * mean_power).sum() / max(total, 1e-9))
    cumulative = np.cumsum(mean_power)
    rolloff = float(frequencies[min(len(frequencies) - 1, np.searchsorted(cumulative, total * 0.85))])
    rms = float(np.sqrt(np.mean(signal ** 2)))
    peak = float(np.max(np.abs(signal)))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(signal)))))
    bands = [(0, 150), (150, 400), (400, 1000), (1000, 2500), (2500, 5000), (5000, 8000)]
    band_energy = [float(np.log1p(mean_power[(frequencies >= low) & (frequencies < high)].sum())) for low, high in bands]
    # Sixteen log filter-bank bins make the feature vector stable and CNN-friendly.
    edges = np.linspace(0, len(frequencies), 17).astype(int)
    filter_bank = np.stack([mean_power[edges[i]:edges[i + 1]].mean() for i in range(16)])
    mfcc = _dct(np.log1p(filter_bank)[None, :], 8)[0]
    vector = np.concatenate([mfcc, np.asarray(band_energy), [centroid / sample_rate, rolloff / sample_rate, rms, peak, zcr]])
    metrics = {"rms": rms, "peak": peak, "centroid_hz": centroid, "rolloff_hz": rolloff, "zero_crossing": zcr}
    return vector.astype(np.float32), metrics


def build_visuals(signal: np.ndarray, sample_rate: int = SAMPLE_RATE, waveform_points: int = 180, spectrum_bins: int = 32) -> Dict[str, object]:
    """Return compact, normalized data for the diagnosis waveform and spectrum."""
    values = np.asarray(signal, dtype=np.float32).reshape(-1)
    if values.size == 0:
        values = np.zeros(1024, dtype=np.float32)
    point_count = max(2, min(waveform_points, values.size))
    positions = np.linspace(0, values.size - 1, point_count).astype(int)
    scale = max(float(np.max(np.abs(values))), 1e-6)
    waveform = np.clip(values[positions] / scale, -1, 1)

    segment = values[:min(values.size, 4096)]
    if segment.size < 1024:
        segment = np.pad(segment, (0, 1024 - segment.size))
    spectrum = np.abs(np.fft.rfft(segment * np.hanning(segment.size)))
    frequencies = np.fft.rfftfreq(segment.size, 1 / max(sample_rate, 1))
    max_hz = min(8000.0, max(sample_rate, 1) / 2)
    mask = frequencies <= max_hz
    spectrum, frequencies = spectrum[mask], frequencies[mask]
    edges = np.linspace(0, len(spectrum), max(2, spectrum_bins) + 1).astype(int)
    levels = []
    for index in range(len(edges) - 1):
        chunk = spectrum[edges[index]:edges[index + 1]]
        levels.append(float(chunk.mean()) if chunk.size else 0.0)
    level_scale = max(max(levels, default=0.0), 1e-6)
    spectrum_data = []
    for index, level in enumerate(levels):
        chunk = frequencies[edges[index]:edges[index + 1]]
        center = float(chunk.mean()) if chunk.size else 0.0
        spectrum_data.append({"frequency_hz": round(center, 1), "amplitude": round(min(1.0, level / level_scale), 4)})
    return {
        "duration": round(values.size / max(sample_rate, 1), 2),
        "sample_rate": int(sample_rate),
        "waveform": [round(float(value), 4) for value in waveform],
        "spectrum": spectrum_data,
    }
