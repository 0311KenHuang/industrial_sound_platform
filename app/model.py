"""Hot-swappable model backends for synthetic or future real data."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .signal import CLASS_NAMES, extract_features, synthesize


class ClassifierBackend:
    name = "base"

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        raise NotImplementedError

    def predict(self, feature: np.ndarray) -> tuple[str, np.ndarray]:
        raise NotImplementedError


class PrototypeClassifier(ClassifierBackend):
    name = "prototype-fallback"

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        self.centroids = np.stack([features[labels == i].mean(axis=0) for i in range(len(CLASS_NAMES))])
        self.scales = np.maximum(features.std(axis=0), 0.05)

    def predict(self, feature: np.ndarray) -> tuple[str, np.ndarray]:
        distances = np.sqrt(((self.centroids - feature) / self.scales) ** 2).mean(axis=1)
        logits = -distances * 1.7
        logits -= logits.max()
        probabilities = np.exp(logits) / np.exp(logits).sum()
        return CLASS_NAMES[int(probabilities.argmax())], probabilities


class TorchCNNClassifier(ClassifierBackend):
    # The fallback path is always available; with torch installed this compact
    # depthwise-friendly 1-D classifier is the swap point for MobileNetV3 weights.
    name = "mobilenetv3-light-cnn"

    def __init__(self) -> None:
        import torch
        from torch import nn
        self.torch = torch
        self.nn = nn
        self.net = None

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        torch, nn = self.torch, self.nn
        x = torch.tensor(features, dtype=torch.float32).unsqueeze(1)
        y = torch.tensor(labels, dtype=torch.long)
        self.net = nn.Sequential(nn.Conv1d(1, 8, 3, padding=1), nn.ReLU(), nn.Conv1d(8, 16, 3, padding=1), nn.ReLU(), nn.AdaptiveAvgPool1d(1), nn.Flatten(), nn.Linear(16, len(CLASS_NAMES)))
        optimizer = torch.optim.Adam(self.net.parameters(), lr=0.01)
        loss_fn = nn.CrossEntropyLoss()
        self.net.train()
        for _ in range(45):
            optimizer.zero_grad()
            loss_fn(self.net(x), y).backward()
            optimizer.step()

    def predict(self, feature: np.ndarray) -> tuple[str, np.ndarray]:
        self.net.eval()
        with self.torch.no_grad():
            output = self.net(self.torch.tensor(feature, dtype=self.torch.float32).view(1, 1, -1))
            probabilities = self.torch.softmax(output, dim=1)[0].numpy()
        return CLASS_NAMES[int(probabilities.argmax())], probabilities


@dataclass
class ModelManager:
    backend: ClassifierBackend | None = None
    trained_samples: int = 0

    def train(self, per_class: int = 24) -> dict[str, Any]:
        features, labels = [], []
        for label, fault in enumerate(CLASS_NAMES):
            for sample in range(per_class):
                signal, rate = synthesize(fault, seed=1000 + label * 100 + sample)
                feature, _ = extract_features(signal, rate)
                features.append(feature)
                labels.append(label)
        x, y = np.stack(features), np.asarray(labels)
        try:
            backend: ClassifierBackend = TorchCNNClassifier()
        except Exception:
            backend = PrototypeClassifier()
        backend.fit(x, y)
        self.backend = backend
        self.trained_samples = len(y)
        return {"backend": backend.name, "samples": len(y), "classes": list(CLASS_NAMES)}

    def ensure_ready(self) -> None:
        if self.backend is None:
            self.train()

    def predict(self, signal: np.ndarray, sample_rate: int) -> dict[str, Any]:
        self.ensure_ready()
        features, metrics = extract_features(signal, sample_rate)
        fault, probabilities = self.backend.predict(features)
        return {"fault": fault, "probabilities": {name: round(float(probabilities[i]), 4) for i, name in enumerate(CLASS_NAMES)}, "metrics": metrics, "backend": self.backend.name, "samples": self.trained_samples}
