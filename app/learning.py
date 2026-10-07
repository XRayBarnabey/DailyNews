import random
from datetime import date

from app.online import fetch_crossword_words, fetch_quotes

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

CROSSWORD_WORDS = {
    "debutant": (
        ("SOLEIL", "Astre qui éclaire la Terre."),
        ("FROMAGE", "Produit laitier affiné, souvent à pâte molle ou dure."),
        ("JARDIN", "Espace où l’on cultive fleurs et légumes."),
        ("CHEVAL", "Animal que l’on monte."),
        ("MAISON", "Lieu où l’on habite."),
        ("FENETRE", "Ouverture qui laisse entrer la lumière."),
        ("CHOCOLAT", "Friandise faite à partir de cacao."),
        ("BATEAU", "Il flotte sur l’eau."),
        ("ORANGE", "Agrume rond et fruit de l’oranger."),
        ("TABLEAU", "Peinture encadrée accrochée au mur."),
        ("MONTAGNE", "Grande élévation naturelle de terrain."),
        ("CUISINE", "Pièce où l’on prépare les repas."),
        ("LIVRE", "Objet fait de pages que l’on lit."),
        ("PLAGE", "Étendue de sable au bord de la mer."),
        ("ETOILE", "Point brillant dans le ciel nocturne."),
        ("RIVIERE", "Cours d’eau qui se jette dans un fleuve."),
    ),
    "normal": (
        ("BIBLIOTHEQUE", "Lieu où l’on emprunte des livres."),
        ("ORCHESTRE", "Ensemble de musiciens dirigé par un chef."),
        ("HORIZON", "Ligne où le ciel semble toucher la terre."),
        ("ARCHIPEL", "Groupe d’îles proches les unes des autres."),
        ("PAYSAGE", "Étendue de territoire que l’on regarde."),
        ("VOYAGEUR", "Personne qui parcourt des pays."),
        ("MARCHE", "Lieu de vente en plein air."),
        ("ELEPHANT", "Plus grand mammifère terrestre, à trompe."),
        ("PARACHUTE", "Toile qui ralentit la chute."),
        ("SYMPHONIE", "Grande composition pour orchestre."),
        ("TELESCOPE", "Instrument pour observer les astres."),
        ("CATHEDRALE", "Grande église d’un évêque."),
        ("ALPHABET", "Ensemble des lettres d’une langue."),
        ("LABYRINTHE", "Réseau de chemins où l’on se perd."),
        ("PAPILLON", "Insecte aux ailes colorées issu d’une chenille."),
        ("EXPEDITION", "Voyage organisé pour explorer."),
    ),
    "avance": (
        ("EPHEMERE", "Qui ne dure qu’un court instant."),
        ("PARADIGME", "Modèle de pensée qui structure une discipline."),
        ("SERENDIPITE", "Découverte heureuse faite par hasard."),
        ("QUINTESSENCE", "Ce qu’il y a de plus pur et de plus essentiel."),
        ("ALTRUISME", "Souci désintéressé des autres."),
        ("EQUINOXE", "Moment où jour et nuit ont même durée."),
        ("PERSPICACE", "Qui comprend finement les choses."),
        ("METAPHORE", "Figure de style fondée sur une comparaison implicite."),
        ("OBSOLETE", "Qui n’est plus en usage."),
        ("AMBIGUITE", "Caractère de ce qui peut être compris de plusieurs façons."),
        ("PHILANTHROPE", "Personne qui œuvre pour le bien de l’humanité."),
        ("ECLECTIQUE", "Qui réunit des éléments d’origines variées."),
        ("RESILIENCE", "Capacité à surmonter les épreuves."),
        ("ANACHRONISME", "Erreur de datation d’un fait ou d’un objet."),
        ("CATHARSIS", "Purification des émotions par l’art."),
    ),
}

MIN_CROSSWORD_WORDS = 5
CANDIDATE_POOL = 60
MAX_CROSSWORD_WORDS = 10

PROVERBS = (
    ("Petit à petit, l’oiseau fait son nid.", "La patience permet d’accomplir de grandes choses."),
    ("Qui ne risque rien n’a rien.", "Il faut oser pour réussir."),
    ("Rome ne s’est pas faite en un jour.", "Les grandes œuvres demandent du temps."),
    ("Après la pluie, le beau temps.", "Les difficultés finissent par passer."),
    ("L’habit ne fait pas le moine.", "Les apparences sont trompeuses."),
    ("Mieux vaut tard que jamais.", "Il est toujours temps de bien faire."),
    ("Pierre qui roule n’amasse pas mousse.", "Qui change sans cesse ne s’enracine pas."),
    ("Tout vient à point à qui sait attendre.", "La patience est récompensée."),
    ("Chat échaudé craint l’eau froide.", "Une mauvaise expérience rend méfiant."),
    ("L’union fait la force.", "Ensemble, on est plus fort."),
)


def _try_layout(words: list[tuple[str, str]]) -> dict[tuple[int, int], str] | None:
    """Place words greedily so that each new word crosses the existing ones."""
    first = words[0][0]
    cells: dict[tuple[int, int], str] = {(0, i): ch for i, ch in enumerate(first)}
    placed = [(first, 0, 0, "across")]

    def fits(word: str, row: int, col: int, direction: str) -> bool:
        dr, dc = (0, 1) if direction == "across" else (1, 0)
        if (row - dr, col - dc) in cells or (row + dr * len(word), col + dc * len(word)) in cells:
            return False
        crossings = 0
        for i, ch in enumerate(word):
            r, c = row + dr * i, col + dc * i
            if (r, c) in cells:
                if cells[(r, c)] != ch:
                    return False
                crossings += 1
            else:
                # side neighbours must be empty, otherwise letters would form unintended words
                if (r + dc, c + dr) in cells or (r - dc, c - dr) in cells:
                    return False
        return crossings == 1

    for word, _ in words[1:]:
        if len(placed) >= MAX_CROSSWORD_WORDS:
            break
        options = []
        for pword, prow, pcol, pdir in placed:
            direction = "down" if pdir == "across" else "across"
            for i, ch in enumerate(pword):
                for j, wch in enumerate(word):
                    if ch != wch:
                        continue
                    if pdir == "across":
                        row, col = prow - j, pcol + i
                    else:
                        row, col = prow + i, pcol - j
                    if fits(word, row, col, direction):
                        options.append((row, col, direction))
        if options:
            row, col, direction = options[0]
            dr, dc = (0, 1) if direction == "across" else (1, 0)
            for i, ch in enumerate(word):
                cells[(row + dr * i, col + dc * i)] = ch
            placed.append((word, row, col, direction))
    if len(placed) < MIN_CROSSWORD_WORDS:
        return None
    return {"cells": cells, "placed": placed}


def build_crossword(difficulty: str, seed: int, online_words: list[tuple[str, str]] | None = None) -> dict:
    words = list(CROSSWORD_WORDS[difficulty]) + list(online_words or [])
    rng = random.Random(seed)
    bank = list(dict(words).items())
    if len(bank) > CANDIDATE_POOL:
        bank = rng.sample(bank, CANDIDATE_POOL)
    best = None
    for _ in range(300):
        rng.shuffle(bank)
        layout = _try_layout(bank)
        if layout and (best is None or len(layout["placed"]) > len(best["placed"])):
            best = layout
            if len(best["placed"]) >= MAX_CROSSWORD_WORDS:
                break
    if best is None:
        raise ValueError("Impossible de construire la grille de mots croisés.")
    clues = dict(words)
    cells, placed = best["cells"], best["placed"]
    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    height = max(r for r, _ in cells) - min_r + 1
    width = max(c for _, c in cells) - min_c + 1
    starts = sorted({(r - min_r, c - min_c) for _, r, c, _ in placed})
    numbers = {pos: n for n, pos in enumerate(starts, 1)}
    rows = []
    for r in range(height):
        rows.append(
            [
                {"filled": (r + min_r, c + min_c) in cells, "number": numbers.get((r, c))}
                for c in range(width)
            ]
        )
    across, down, solution = [], [], []
    for word, r, c, direction in placed:
        number = numbers[(r - min_r, c - min_c)]
        entry = {"number": number, "clue": clues[word], "length": len(word)}
        (across if direction == "across" else down).append(entry)
        solution.append((number, direction, word))
    across.sort(key=lambda e: e["number"])
    down.sort(key=lambda e: e["number"])
    solution.sort(key=lambda s: (s[0], s[1]))
    return {
        "grid": rows,
        "across": across,
        "down": down,
        "word_count": len(placed),
        "solution": " · ".join(
            f"{n} {'H' if d == 'across' else 'V'} : {w}" for n, d, w in solution
        ),
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
        if settings.get("show_vocabulary_translations") == "true":
            features["vocabulary"]["translations"] = [
                {"language": LANGUAGE_NAMES[code], "word": word[code]} for code in LANGUAGE_NAMES if code != language
            ]
    if settings.get("show_crossword") == "true":
        difficulty = settings.get("crossword_difficulty", "debutant")
        if difficulty not in CROSSWORD_WORDS:
            difficulty = "debutant"
        online = fetch_crossword_words().get(difficulty) if settings.get("online_content", "true") == "true" else None
        puzzle = build_crossword(difficulty, day_index, online)
        features["crossword"] = {"difficulty": DIFFICULTY_NAMES[difficulty], **puzzle}
    if settings.get("show_proverb") == "true":
        quotes = fetch_quotes() if settings.get("online_content", "true") == "true" else []
        if quotes:
            item = quotes[day_index % len(quotes)]
            features["proverb"] = {"title": "La citation du jour", "text": item["text"], "meaning": item["author"]}
        else:
            text, meaning = PROVERBS[day_index % len(PROVERBS)]
            features["proverb"] = {"title": "Le proverbe du jour", "text": text, "meaning": meaning}
    if settings.get("show_it_term") == "true":
        term, definition = IT_TERMS[day_index % len(IT_TERMS)]
        features["it_term"] = {"term": term, "definition": definition}
    return features
