# src/config/runtime.py
"""Единая типизированная конфигурация процесса Django."""

from core.config import ROOT as PROJECT_ROOT
from core.config import Settings as RuntimeSettings

__all__ = ["PROJECT_ROOT", "RuntimeSettings"]
