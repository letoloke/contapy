#!/usr/bin/env python3
"""Start ContaPy."""

try:
    from contapy.app import main
except ModuleNotFoundError as exc:  # pragma: no cover - friendly install hint
    if exc.name == "PySide6":
        raise SystemExit(
            "PySide6 is required to run ContaPy.\n"
            "Install it with:  python3 -m pip install -r requirements.txt\n"
            "Arch users can also run:  sudo pacman -S pyside6"
        ) from exc
    raise

if __name__ == "__main__":
    raise SystemExit(main())
