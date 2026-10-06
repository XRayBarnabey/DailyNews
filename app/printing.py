from __future__ import annotations

import os
import smtplib
import subprocess
from email.message import EmailMessage
from typing import Protocol

from app.config import (
    CUPS_PORT,
    CUPS_SERVER,
    EPSON_CONNECT_EMAIL,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_STARTTLS,
    SMTP_USER,
)

EMAIL_PRINTER = "epson-connect-email"


def email_printing_enabled() -> bool:
    return bool(EPSON_CONNECT_EMAIL and SMTP_HOST and SMTP_FROM)


def send_pdf_by_email(pdf_path: str) -> str:
    """Send the PDF to the printer's Epson Connect address (the printer prints attachments)."""
    message = EmailMessage()
    message["From"] = SMTP_FROM
    message["To"] = EPSON_CONNECT_EMAIL
    message["Subject"] = os.path.basename(pdf_path)
    message.set_content("DailyNews")
    with open(pdf_path, "rb") as handle:
        message.add_attachment(
            handle.read(), maintype="application", subtype="pdf", filename=os.path.basename(pdf_path)
        )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        if SMTP_STARTTLS:
            smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)
    return "PDF envoyé à l'imprimante via Epson Connect."



def _decode(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return (value or "").strip()


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
        extra = [EMAIL_PRINTER] if email_printing_enabled() else []
        try:
            result = subprocess.run(
                ["lpstat", "-p"], capture_output=True, text=True, timeout=8, env=self._environment(), check=True
            )
        except (OSError, subprocess.SubprocessError):
            if extra:
                return extra
            raise
        return [line.split()[1] for line in result.stdout.splitlines() if line.startswith("printer ")] + extra

    def print_pdf(self, pdf_path: str, printer: str, copies: int = 1, duplex: bool = True) -> str:
        if not os.path.isfile(pdf_path):
            raise FileNotFoundError(pdf_path)
        if printer == EMAIL_PRINTER:
            if not email_printing_enabled():
                raise ValueError("Impression par e-mail non configurée.")
            return send_pdf_by_email(pdf_path)
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
            "-",
        ]
        with open(pdf_path, "rb") as handle:
            pdf_bytes = handle.read()
        try:
            result = subprocess.run(
                command, input=pdf_bytes, capture_output=True, timeout=30, env=self._environment(), check=True
            )
        except subprocess.CalledProcessError as exc:
            detail = _decode(exc.stderr) or _decode(exc.stdout) or f"code de sortie {exc.returncode}"
            raise RuntimeError(f"Échec de l'impression CUPS : {detail}"[:500]) from exc
        return _decode(result.stdout) or "Impression envoyée à CUPS."
