"""Executor abstraction. Switching executor = switching mode."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.strategy.signals.base import Signal


class Executor(ABC):
    @abstractmethod
    def submit(self, signal: Signal) -> None: ...
