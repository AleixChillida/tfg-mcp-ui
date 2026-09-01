r"""Diagnostico rapido del entorno del backend.

Ejecutar siempre con el Python del venv:
    .\.venv\Scripts\python.exe doctor.py
"""
from __future__ import annotations

import importlib
import os
import platform
import sys
from pathlib import Path

MODULES = ("mcp", "fastmcp", "fastapi", "uvicorn", "dotenv", "httpx")


def main() -> int:
    print("=== TFG MCP Apps backend doctor ===")
    print("Python:", sys.version.replace("\n", " "))
    print("Executable:", sys.executable)
    print("Platform:", platform.platform())
    print("Working dir:", Path.cwd())
    print(".env:", "OK" if Path(".env").exists() else "MISSING")
    print("MCP_UYUNI_ENABLED:", os.getenv("MCP_UYUNI_ENABLED", "(no cargado por doctor.py)"))

    failed = False
    for name in MODULES:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", None)
            if version is None:
                try:
                    from importlib.metadata import version as package_version
                    package_name = "python-dotenv" if name == "dotenv" else name
                    version = package_version(package_name)
                except Exception:
                    version = "?"
            print(f"{name:10} OK  {version}")
        except Exception as exc:
            failed = True
            print(f"{name:10} ERROR  {type(exc).__name__}: {exc}")

    if failed:
        print("\nFaltan dependencias. Ejecuta setup_windows.ps1.")
        return 1

    print("\nEntorno Python correcto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
