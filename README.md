# DailyNews

DailyNews est une application web d’administration et de génération d’une revue de presse quotidienne. Elle récupère des flux RSS, sélectionne les articles de la veille selon les poids et quotas des sources, compose un PDF A4 en noir et blanc, l’archive et peut le transmettre à une imprimante CUPS.

## Démarrage

```bash
git clone <URL_DU_DEPOT> dailynews
cd dailynews
cp .env.example .env
```

Modifiez `ADMIN_PASSWORD` dans `.env` avant d’exposer l’application. Open-Meteo fonctionne sans clé pour un usage gratuit ; une clé client facultative se règle dans l’interface. Les secrets ne sont jamais publiés dans Git. Puis démarrez l’application :

```bash
docker compose up -d
```

Ouvrez [http://localhost:8000](http://localhost:8000). L’administration est protégée par HTTP Basic ; les identifiants initiaux sont ceux de `ADMIN_USER` et `ADMIN_PASSWORD` dans `.env`. En développement local, installez les dépendances depuis `requirements-dev.txt` puis démarrez `uvicorn app.main:app --reload`.

La première ouverture crée les tables, les réglages, le planning et un flux RSS de démonstration hors ligne. Le fichier PDF et la base sont persistés dans le volume Docker `dailynews-data`.

## Utilisation

Depuis le tableau de bord, utilisez **Récupérer les flux** puis **Générer une édition**. L’édition est datée du jour, mais sélectionne par défaut les articles publiés la veille entre minuit et minuit dans le fuseau configuré. L’aperçu PDF intégré permet de vérifier la composition avant impression.

La page **Flux RSS** permet d’ajouter, tester, activer, modifier et supprimer les sources. Le flux `mock://demo`, livré à l’installation, sert quatre articles fictifs datés de la veille sans accès réseau. Il peut être récupéré et généré comme n’importe quel flux.

La page **Journal** permet d’ajouter jusqu’à dix villes en saisissant leur nom et en choisissant une suggestion Open-Meteo ; leurs coordonnées sont remplies automatiquement. Open-Meteo fournit la température, les conditions et le risque de précipitations du matin et de l’après-midi, y compris les créneaux matinaux passés grâce à `past_days`. L’API gratuite ne demande pas de clé ; une clé client facultative peut être changée dans l’interface sans jamais être renvoyée par l’API de lecture. La date française et la fête principale sont imprimées en haut à gauche, avec repli si Nominis est indisponible.

Le PDF place le bandeau météo immédiatement sous le titre puis les articles résumés en une, deux ou trois colonnes, sans rubriques ni URL imprimées. Les QR codes vers les articles sont optionnels. Deux polices indépendantes règlent le titre du journal et les articles ; un logo PNG transparent peut être importé pour l’angle supérieur droit. Le plafond de pages se règle dans **Journal** : `2` pour une feuille recto-verso, `4` pour deux feuilles. Si nécessaire, les articles les moins bien classés sont retirés pour respecter le plafond sans couper le document.

La page **Planification** définit séparément les heures de collecte, de génération et d’impression, les jours actifs, l’activation automatique et les options CUPS. Le réglage initial propose 05:30, 06:00 et 06:10 tous les jours ; l’impression automatique est désactivée tant qu’aucune imprimante n’est sélectionnée.

## Répartition éditoriale

La sélection est isolée dans `app/newsroom/selection.py`, testée sans base ni réseau et utilisable indépendamment du web.

1. Les articles dont la date connue est hors de la fenêtre locale sont écartés ; une date absente reste admissible.
2. Les URL sont normalisées (fragment et paramètres de suivi supprimés), puis les titres sont normalisés pour fusionner les doublons syndiqués. La copie provenant du flux dont le score éditorial est supérieur est conservée.
3. Les minima de flux sont alloués en premier, par priorité puis par identifiant, dans la limite du volume disponible.
4. Le reste du tirage est réparti proportionnellement aux poids, en respectant les disponibilités et maxima. Les places d’un flux épuisé ou plafonné sont redistribuées ; les poids tous nuls deviennent égaux.
5. Le classement interne favorise priorité, poids, fraîcheur et qualité du résumé. Les articles retenus sont présentés dans l’ordre éditorial, sans intertitres de rubrique.

Le rapport de génération expose les volumes analysés, dans la période, sélectionnés, les rubriques et la distribution par source. Les résumés RSS sont du texte nettoyé ; le contenu intégral des articles sources n’est pas aspiré.

## Impression CUPS

Le conteneur embarque le client CUPS (`lp`, `lpstat`), pas un serveur CUPS ni un accès direct à une imprimante physique. Reliez-le à CUPS sur le réseau et définissez son nom DNS ou son adresse joignable depuis le conteneur dans `.env` :

```env
CUPS_SERVER=192.168.1.20
CUPS_PORT=631
```

Autorisez le client sur le serveur CUPS, puis sélectionnez l’imprimante dans **Planification**. Le bouton **Imprimer** envoie l’édition manuellement. Les copies, le format A4 et le recto-verso sur le bord long sont envoyés à CUPS ; chaque tentative est inscrite dans `print_jobs`. Note technique : le PDF est envoyé à `lp` via stdin (`lp ... -`) pour éviter les problèmes de chemin ou de montage entre conteneur et serveur CUPS ; en cas d’échec, le `stderr` de CUPS est conservé dans le message du `print_jobs`. L’absence de CUPS n’empêche ni l’archivage ni le téléchargement du PDF.

## CLI

Les mêmes services sont accessibles sans interface web :

```bash
python -m app.cli init
python -m app.cli test-feed
python -m app.cli fetch
python -m app.cli generate
python -m app.cli print
```

`generate` force la génération de l’édition du jour. Le service de génération, son classement et ses modèles HTML/CSS sont séparés des routes HTTP.

## Configuration

| Variable | Défaut | Usage |
| --- | --- | --- |
| `APP_ENV` | `production` | Environnement de déploiement |
| `ADMIN_USER` | `admin` | Compte de l’interface et de l’API |
| `ADMIN_PASSWORD` | `change-this-password` dans Compose | Mot de passe Basic Auth ; à remplacer avant tout accès réseau |
| `DATABASE_URL` | SQLite sous `/data/database` | URL SQLAlchemy (PostgreSQL possible avec son pilote) |
| `TIMEZONE` | `Europe/Paris` | Fuseau initial du planning et du journal |
| `DATA_DIR` | `/data` en conteneur, `data` en local | Base, journaux et autres données |
| `PDF_DIR` | `/data/pdf` | Éditions et images mises en cache |
| `LOG_LEVEL` | `INFO` | Niveau des journaux JSON |
| `WEB_PORT` | `8000` | Port publié par Compose |
| `CUPS_SERVER`, `CUPS_PORT` | local, `631` | Serveur CUPS optionnel |
| `OPENMETEO_API_KEY` | vide | Clé client Open-Meteo facultative (réglable aussi dans l’interface) |

Les réglages éditoriaux et le planning sont ensuite administrés dans l’interface. Les journaux structurés sont envoyés sur la sortie du conteneur et écrits avec rotation dans `/data/logs/dailynews.log`.

## API

L’API JSON, protégée par les mêmes identifiants que l’interface, expose notamment :

```text
GET/POST          /api/feeds
PUT/DELETE        /api/feeds/{id}
POST              /api/feeds/{id}/test
POST              /api/rss/fetch
GET/POST          /api/editions
GET               /api/editions/{id}
GET               /api/editions/{id}/pdf
POST              /api/editions/{id}/print
GET/PUT           /api/settings
GET/PUT           /api/schedule
GET               /api/printers
GET               /health
```

Les schémas d’entrée valident les URL, horaires, quotas et coordonnées. La récupération RSS refuse les URL non HTTP(S), les adresses IP non publiques et les redirections ; la taille et le délai des flux sont limités. Les flux accessibles sont donc des URL publiques configurées par l’administrateur.

## Version

La version en cours (fichier `app/VERSION`, plus le commit Git si connu) s'affiche en bas à droite de l'interface et dans `/health`. Pour inclure le commit dans l'image Docker : `GIT_SHA=$(git rev-parse --short HEAD) docker compose up -d --build`.

## Sauvegarde et maintenance

Sauvegardez régulièrement le volume Docker `dailynews-data`, qui contient la base SQLite, les PDF, les images locales et les journaux. Par exemple, arrêtez le service puis archivez le volume avec les outils Docker de votre hôte. Les PDF restent des fichiers standards indépendants de DailyNews.

Mettez à jour l’application en récupérant les changements puis en reconstruisant l’image :

```bash
git pull
docker compose up -d --build
```

Les tables sont créées au démarrage via SQLAlchemy `create_all`. Les migrations Alembic ne sont pas encore intégrées ; sauvegardez les données avant une mise à jour qui change le schéma.

## Tests et dépannage

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
docker compose config --quiet
docker compose logs -f dailynews
```

- **Aucun article sélectionné** : vérifiez l’état des flux, leurs dates de publication et le fuseau horaire ; le flux de démonstration vérifie le parcours complet.
- **PDF absent ou erreur au démarrage** : consultez `docker compose logs dailynews` ; WeasyPrint s’appuie sur les bibliothèques système fournies par l’image.
- **Météo indisponible** : vérifiez l’accès Internet sortant et les coordonnées ; la génération reste opérationnelle.
- **Imprimante absente** : contrôlez `CUPS_SERVER`, le port 631, l’accès réseau et les droits CUPS depuis le conteneur.
- **Mot de passe oublié** : modifiez `ADMIN_PASSWORD` dans `.env` et recréez le conteneur (`docker compose up -d --force-recreate`).

## Architecture

```text
app/main.py                 FastAPI, authentification, HTML et API
app/models.py               Flux, articles, éditions, réglages, planning, impressions
app/rss.py                  Parsing RSS, assainissement et protections réseau
app/newsroom/selection.py   Fenêtre de dates, déduplication, quotas pondérés
app/weather.py              Interface WeatherProvider et prévisions Open-Meteo
app/services.py             Classification, composition et génération PDF
app/templates/              Interface Jinja et gabarit presse
app/scheduler.py            Jobs indépendants de collecte, génération, impression
app/printing.py             Interface PrintProvider et client CUPS
app/cli.py                  Commandes opérationnelles
```

Les PDF sont au format A4, noir et blanc, avec en-tête, bandeau météo horizontal et folios. Les articles s’écoulent en colonnes ; un plafond de pages réduit la sélection éditoriale plutôt que de tronquer le PDF.
## Impression par e-mail (Epson Connect)

Si l'imprimante (ex. EPSON WF-4830) ne peut pas être ajoutée à CUPS, activez Epson Connect sur l'imprimante
puis renseignez son adresse e-mail et un serveur SMTP : `EPSON_CONNECT_EMAIL`, `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (l'adresse expéditrice doit être autorisée dans Epson Connect).
Une imprimante virtuelle `epson-connect-email` apparaît alors dans la liste ; le PDF lui est envoyé en pièce jointe.
Les options copies/recto-verso ne s'appliquent pas à ce mode.
