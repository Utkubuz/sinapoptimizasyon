"""Root launcher for the Streamlit web interface."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    from sinav_takvimi.arayuz.streamlit_app import calistir

    calistir()


if __name__ == "__main__":
    main()
