"""Masaüstü uygulamasını doğrudan modül olarak çalıştırma giriş noktası."""

from __future__ import annotations

import sys

from sinav_takvimi.arayuz.masaustu import uygulamayi_baslat

if __name__ == "__main__":
    sys.exit(uygulamayi_baslat())
