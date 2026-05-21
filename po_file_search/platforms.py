from __future__ import annotations

import platform
from enum import Enum


class SupportedOS(str, Enum):
    LINUX = "linux"
    MACOS = "macos"


def detect_os() -> SupportedOS:
    system = platform.system().lower()
    if system == "linux":
        return SupportedOS.LINUX
    if system == "darwin":
        return SupportedOS.MACOS
    raise RuntimeError(f"Unsupported OS: {platform.system()}. Only Linux and macOS are supported.")
