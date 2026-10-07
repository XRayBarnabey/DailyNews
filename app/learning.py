from datetime import date

VOCABULARY = (
    {
        "fr": "curieux",
        "en": "curious",
        "es": "curioso",
        "pt-BR": "curioso",
        "definition": "Qui désire apprendre ou comprendre.",
    },
    {
        "fr": "la lumière",
        "en": "light",
        "es": "la luz",
        "pt-BR": "a luz",
        "definition": "Ce qui rend les choses visibles.",
    },
    {
        "fr": "partager",
        "en": "to share",
        "es": "compartir",
        "pt-BR": "compartilhar",
        "definition": "Donner une part de quelque chose à quelqu’un.",
    },
    {
        "fr": "la fenêtre",
        "en": "window",
        "es": "la ventana",
        "pt-BR": "a janela",
        "definition": "Ouverture dans un mur qui laisse entrer la lumière.",
    },
    {
        "fr": "demain",
        "en": "tomorrow",
        "es": "mañana",
        "pt-BR": "amanhã",
        "definition": "Le jour qui suit aujourd’hui.",
    },
    {
        "fr": "le voyage",
        "en": "journey",
        "es": "el viaje",
        "pt-BR": "a viagem",
        "definition": "Déplacement vers un lieu plus ou moins éloigné.",
    },
    {"fr": "heureux", "en": "happy", "es": "feliz", "pt-BR": "feliz", "definition": "Qui éprouve du bonheur."},
)

IT_TERMS = (
    ("Algorithme", "Suite finie d’instructions permettant de résoudre un problème ou d’effectuer un calcul."),
    ("API", "Interface qui permet à deux logiciels de communiquer selon des règles définies."),
    ("Cache", "Espace de stockage temporaire qui accélère l’accès à des données réutilisées."),
    ("Chiffrement", "Transformation de données en un format illisible sans la clé de déchiffrement."),
    ("DNS", "Système qui associe les noms de domaine aux adresses des serveurs."),
    ("Logiciel libre", "Logiciel dont la licence permet notamment l’étude, la modification et le partage du code."),
    ("Versionnement", "Suivi des changements apportés à des fichiers au fil du temps."),
)

CROSSWORDS = {
    "debutant": {
        "rows": ("RAT", "ARE", "TES"),
        "across": (
            "Petit rongeur à longue queue.",
            "Ancienne unité de mesure de surface.",
            "Adjectif possessif devant « livres » ou « idées ».",
        ),
        "down": (
            "Petit rongeur à longue queue.",
            "Ancienne unité de mesure de surface.",
            "Adjectif possessif devant « livres » ou « idées ».",
        ),
    },
    "normal": {
        "rows": ("MOT", "OUI", "TES"),
        "across": (
            "Unité de langue composée de lettres.",
            "Réponse affirmative.",
            "Adjectif possessif devant « livres » ou « idées ».",
        ),
        "down": (
            "Unité de langue composée de lettres.",
            "Réponse affirmative.",
            "Adjectif possessif devant « livres » ou « idées ».",
        ),
    },
    "avance": {
        "rows": ("SEL", "EGO", "LOT"),
        "across": (
            "Condiment blanc qui relève les plats.",
            "Le « moi » en psychologie.",
            "Ensemble ou groupe de personnes ou de choses.",
        ),
        "down": (
            "Condiment blanc qui relève les plats.",
            "Le « moi » en psychologie.",
            "Ensemble ou groupe de personnes ou de choses.",
        ),
    },
}

LANGUAGE_NAMES = {"fr": "français", "en": "anglais", "es": "espagnol", "pt-BR": "portugais du Brésil"}
DIFFICULTY_NAMES = {"debutant": "débutant", "normal": "normal", "avance": "avancé"}


def daily_features(edition_date: date, settings: dict[str, str]) -> dict:
    day_index = edition_date.toordinal()
    features = {}
    if settings.get("show_daily_vocabulary") == "true":
        language = settings.get("vocabulary_language", "fr")
        if language not in LANGUAGE_NAMES:
            language = "fr"
        word = VOCABULARY[day_index % len(VOCABULARY)]
        features["vocabulary"] = {
            "language": LANGUAGE_NAMES[language],
            "word": word[language],
            "translation": word["fr"] if language != "fr" else "",
            "definition": word["definition"],
        }
    if settings.get("show_crossword") == "true":
        difficulty = settings.get("crossword_difficulty", "debutant")
        if difficulty not in CROSSWORDS:
            difficulty = "debutant"
        puzzle = CROSSWORDS[difficulty]
        features["crossword"] = {
            "difficulty": DIFFICULTY_NAMES[difficulty],
            "rows": puzzle["rows"],
            "numbers": ((1, 2, 3), (4, None, None), (5, None, None)),
            "across": puzzle["across"],
            "down": puzzle["down"],
            "solution": " / ".join(puzzle["rows"]),
        }
    if settings.get("show_it_term") == "true":
        term, definition = IT_TERMS[day_index % len(IT_TERMS)]
        features["it_term"] = {"term": term, "definition": definition}
    return features
