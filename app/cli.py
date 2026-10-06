from __future__ import annotations

import argparse
import logging

from app.bootstrap import initialize
from app.config import LOG_LEVEL, ensure_directories
from app.database import SessionLocal
from app.models import Edition, Feed
from app.printing import CupsPrintProvider
from app.rss import fetch_all, fetch_feed
from app.services import generate_edition


def main() -> None:
    logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="dailynews")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialiser la base et les paramètres")
    commands.add_parser("fetch", help="Récupérer les flux actifs")
    commands.add_parser("generate", help="Générer le journal de la veille")
    commands.add_parser("print", help="Imprimer la dernière édition")
    commands.add_parser("test-feed", help="Tester le flux de démonstration")
    args = parser.parse_args()
    ensure_directories()
    with SessionLocal() as db:
        initialize(db)
        if args.command == "init":
            print("Base DailyNews initialisée.")
        elif args.command == "fetch":
            print(fetch_all(db))
        elif args.command == "test-feed":
            feed = db.query(Feed).filter_by(url="mock://demo").one()
            print(f"Articles récupérés : {fetch_feed(feed, db)}")
        elif args.command == "generate":
            edition = generate_edition(db, force=True)
            print(f"Édition {edition.edition_date} : {edition.pdf_path} ({edition.page_count} pages)")
        elif args.command == "print":
            edition = db.query(Edition).filter_by(status="ready").order_by(Edition.edition_date.desc()).first()
            if not edition:
                raise SystemExit("Aucune édition disponible.")
            printers = CupsPrintProvider().printers()
            if not printers:
                raise SystemExit("Aucune imprimante CUPS disponible.")
            print(CupsPrintProvider().print_pdf(edition.pdf_path, printers[0]))


if __name__ == "__main__":
    main()
