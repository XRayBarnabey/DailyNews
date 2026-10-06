import io
import json
import unittest
from datetime import date
from unittest.mock import patch

from app.calendar import fete_du_jour, format_french_date


class CalendarTests(unittest.TestCase):
    def test_formats_date_in_french(self):
        self.assertEqual(format_french_date(date(2026, 10, 6)), "mardi 6 octobre 2026")

    def test_reads_primary_saint_and_gender_from_nominis(self):
        payload = {"response": {"prenoms": {"majeurs": {"Bruno": {"sexe": "masculin"}}}}}
        with patch("app.calendar.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
            fete_du_jour.cache_clear()
            self.assertEqual(fete_du_jour(date(2026, 10, 6)), "Saint Bruno")

    def test_nominis_unavailable_does_not_raise(self):
        with patch("app.calendar.urlopen", side_effect=TimeoutError):
            fete_du_jour.cache_clear()
            self.assertEqual(fete_du_jour(date(2026, 10, 7)), "")


if __name__ == "__main__":
    unittest.main()