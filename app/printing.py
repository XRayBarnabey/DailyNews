from __future__ import annotations

import os
import subprocess
from typing import Protocol

from app.config import CUPS_PORT, CUPS_SERVER


class PrintProvider(Protocol):
    def printers(self) -> list[str]: ...
    def print_pdf(self, pdf_path: str, printer: str, copies: int = 1, duplex: bool = True) -> str: ...


class CupsPrintProvider:
    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        if CUPS_SERVER:
            environment["CUPS_SERVER"] = f"{CUPS_SERVER}:{CUPS_PORT}"
        return environment

    def printers(self) -> list[str]:
        result = subprocess.run(
            ["lpstat", "-p"], capture_output=True, text=True, timeout=8, env=self._environment(), check=True
        )
        return [line.split()[1] for line in result.stdout.splitlines() if line.startswith("printer ")]

    def print_pdf(self, pdf_path: str, printer: str, copies: int = 1, duplex: bool = True) -> str:
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(pdf_path)
        if printer not in self.printers():
            raise ValueError("Imprimante inconnue ou indisponible.")
        command = [
            "lp",
            "-d",
            printer,
            "-n",
            str(max(1, min(copies, 20))),
            "-o",
            "sides=two-sided-long-edge" if duplex else "sides=one-sided",
            "-o",
            "media=A4",
            pdf_path,
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=30, env=self._environment(), check=True
        )
        return result.stdout.strip() or "Impression envoyée à CUPS."
