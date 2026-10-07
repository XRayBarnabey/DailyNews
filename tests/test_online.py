import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app import config, online
from app.learning import daily_features


class OnlineContentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        patcher = patch.object(config, "DATA_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_quotes_are_fetched_cached_and_used(self):
        payload = {
            "success": True,
            "data": {"text": "La citation française du jour.", "author": {"forename": "Hubert", "name": "Reeves"}},
        }
        with patch("app.online._get_json", return_value=payload) as call:
            features = daily_features(date(2026, 10, 7), {"show_proverb": "true"})
            self.assertEqual(
                online.fetch_quotes(), [{"text": "La citation française du jour.", "author": "Hubert Reeves"}]
            )
            self.assertEqual(call.call_count, 1)
        self.assertEqual(features["proverb"]["title"], "La citation du jour")
        self.assertEqual(features["proverb"]["text"], "La citation française du jour.")
        self.assertEqual(features["proverb"]["meaning"], "Hubert Reeves")

    def test_brazilian_translation_label_is_brésilien(self):
        settings = {"show_daily_vocabulary": "true", "show_vocabulary_translations": "true"}
        brazilian = daily_features(date(2026, 10, 7), {**settings, "vocabulary_language": "pt-BR"})
        english = daily_features(date(2026, 10, 7), {**settings, "vocabulary_language": "en"})
        self.assertEqual(brazilian["vocabulary"]["language"], "brésilien")
        self.assertTrue(any(item["language"] == "brésilien" for item in english["vocabulary"]["translations"]))

    def test_quotes_fall_back_to_proverb_offline(self):
        with patch("app.online._get_json", side_effect=OSError("offline")):
            features = daily_features(date(2026, 10, 7), {"show_proverb": "true"})
        self.assertEqual(features["proverb"]["title"], "Le proverbe du jour")

    def test_crossword_words_use_online_bank(self):
        def fake(url, timeout=10):
            if "trouve-mot" in url:
                return [{"name": w, "cat": "nom"} for w in _WORDS]
            return {"fr": [{"definitions": [{"definition": "<i>Une définition assez longue.</i>"}]}]}

        with patch("app.online._get_json", side_effect=fake):
            banks = online.fetch_crossword_words()
        self.assertEqual(set(banks), {"debutant", "normal", "avance"})
        self.assertTrue(all(len(v) >= 12 for v in banks.values()))


_WORDS = (
    ["chaise", "bureau", "fleuve", "nuage", "orange", "pomme", "lampe", "cravate", "poisson", "marteau", "tableau",
     "voiture", "garage", "cuisine", "rideau", "balcon", "jardin", "bouteille", "ordinateur", "cheminee", "carotte", "fourchette", "montagne", "fromage", "horloge"]
    + ["bibliotheque", "restaurant", "boulangerie", "pharmacien", "ambassade", "carburateur", "photographe",
       "baignoire", "calculatrice", "mathematiques", "locomotive", "chocolatier", "refrigerateur", "dictionnaire"]
    + ["gastronomie", "ambulance", "tracteur", "politique", "chanteuse", "orchestre", "cinephile", "magasins", "plombier", "voyageur", "lunettes", "papillon", "architecture", "imprimerie", "astronomie", "horticulteur", "bouleverser", "electricite",
       "sociologie", "philosophie", "cartographe", "hydrographie", "meteorologie"]
)

if __name__ == "__main__":
    unittest.main()
