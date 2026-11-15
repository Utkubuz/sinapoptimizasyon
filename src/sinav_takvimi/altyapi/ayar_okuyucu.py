"""config/agirliklar.toml → Ayarlar."""

from __future__ import annotations

import tomllib
from pathlib import Path

from sinav_takvimi.altyapi.db import KAYNAK_KOKU
from sinav_takvimi.domain.ayarlar import Ayarlar

VARSAYILAN_AYAR_DOSYASI = KAYNAK_KOKU / "config" / "agirliklar.toml"


def ayarlari_yukle(yol: str | Path = VARSAYILAN_AYAR_DOSYASI) -> Ayarlar:
    with Path(yol).open("rb") as f:  # tomllib ikili modda okur
        return Ayarlar.sozlukten(tomllib.load(f))
