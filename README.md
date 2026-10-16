# tri-vehicules

Trie automatiquement des photos par **type de véhicule militaire allemand (1939-1945)** via un modèle de vision (LLM) d'OpenRouter.

Tu indiques un **dossier source** au lancement ; les photos en sont extraites et déplacées vers un **dossier de sortie** (`OUT_DIR`), dans un sous-dossier créé à la volée au nom de la catégorie. Un dossier `a_trier` recueille les échecs (erreurs API).

Le tout tourne dans Docker.

## Comment ça marche

1. `categories.txt` contient la **liste fermée** des catégories (le modèle ne peut choisir que dedans).
2. Chaque image est redimensionnée puis envoyée au modèle avec cette liste.
3. Le modèle répond en JSON : `{"categorie": "...", "confiance": 0.0-1.0, "raison": "..."}`.
4. Rangement dans `OUT_DIR` (dossiers créés au fur et à mesure) :
   - `confiance >= 0.8` → dossier de la catégorie, marquée `haute`
   - `0.5 <= confiance < 0.8` → dossier de la catégorie, marquée `moyenne`
   - `confiance < 0.5` → `_A_VERIFIER`, marquée `basse`
   - catégorie hors liste ou non reconnue → `_A_VERIFIER`
   - aucun véhicule allemand → `_Divers (non-vehicule)`
   - erreur API (après 3 essais) → `a_trier`, marquée `echec`
5. Un manifeste `_tri_manifest.csv` est écrit (`fichier_origine;dossier;confiance`), au même format que l'exemple de `G:\photos_piwigo\2018\embarque`.
6. Les photos sont **retirées du dossier source** au fur et à mesure (déplacement, pas copie).

## Prérequis

- Docker + Docker Compose
- Une clé OpenRouter : https://openrouter.ai/keys

## Installation

```powershell
cd G:\git_chriszep76\tri-vehicules
Copy-Item .env.example .env
# mets ta clé dans OPENROUTER_API_KEY, le dossier source dans PHOTO_DIR
# et le dossier de sortie dans OUT_DIR (ex: G:\photos_piwigo\catégories)
docker compose build
```

## Utilisation

Test à blanc (aucun fichier déplacé) :
```powershell
docker compose run --rm --name tri-vehicules -T tri-vehicules --source /data --dry-run --limit 30
```

Tri réel :
```powershell
docker compose run --rm --name tri-vehicules -T tri-vehicules --source /data
```

Le montage se fait via `.env` : `PHOTO_DIR` → `/data` (source) et `OUT_DIR` → `/out` (sortie). Le script utilise `/out` par défaut (variable `OUT_DIR` du conteneur).

Ou avec des montages explicites et un dossier source choisi à la volée :
```powershell
docker run --rm --name tri-vehicules -e OPENROUTER_API_KEY=$env:OPENROUTER_API_KEY -v "G:\photos_piwigo\2018\embarque\Tiger I:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out --dry-run --limit 30
```

## Options

| Option | Défaut | Description |
| --- | --- | --- |
| `--source` | `/data` | Dossier des photos à trier (dans le conteneur). |
| `--out` | `/out` (ou `$OUT_DIR`) | Dossier racine de sortie ; les sous-dossiers de catégorie y sont créés à la volée. |
| `--categories` | `/app/categories.txt` | Fichier de catégories (liste fermée). |
| `--model` | `$OPENROUTER_MODEL` | Modèle de vision OpenRouter. |
| `--workers` | `4` | Requêtes en parallèle. |
| `--max-side` | `1024` | Taille max (px) de l'image envoyée. |
| `--max-tokens` | `2048` | Budget de tokens de sortie. |
| `--no-reasoning` | désactivé | Désactive la réflexion du modèle (si supporté). |
| `--threshold-high` | `0.8` | Seuil de confiance « haute ». |
| `--threshold-mid` | `0.5` | Seuil de confiance « moyenne ». |
| `--verify-name` | `_A_VERIFIER` | Dossier des cas à revérifier (faible confiance). |
| `--fail-name` | `a_trier` | Dossier des échecs (erreurs API). |
| `--manifest` | `<out>/_tri_manifest.csv` | Chemin du manifeste. |
| `--recursive` | **activé** | Parcourt aussi les sous-dossiers (`--no-recursive` pour désactiver). |
| `--limit` | `0` | Ne traite que les N premières images. |
| `--dry-run` | désactivé | Simule, sans déplacer. |
| `--timeout` | `120` | Délai max par requête (s). |
| `--retries` | `3` | Essais par image. |
| `--backoff` | `2.0` | Délai croissant entre essais (s). |

## Personnaliser les catégories

Édite `categories.txt` (une catégorie par ligne, `#` pour commenter), puis reconstruis :
```powershell
docker compose build
```
Le nom de chaque ligne devient le nom du dossier de destination.

## Modèles conseillés

- `deepseek/deepseek-v4.1-flash` : bon marché, accepte les images.
- `google/gemini-2.5-flash` : vision solide.
- `openai/gpt-4o` / `anthropic/claude-3.7-sonnet` : pour les cas difficiles (identification fine de modèles proches).

Attention : l'identification d'un **modèle précis** (ex. Panzer IV vs Panther) reste difficile ; c'est pourquoi les cas peu sûrs vont dans `_A_VERIFIER`.

## Dépannage

- `Dossier source introuvable: /data` : montage incomplet (`-v "C:\dossier:/data"`).
- `HTTP 401` : clé absente/invalide dans `.env` ou `-e OPENROUTER_API_KEY=...`.
- `reponse vide du modele` : augmenter `--max-tokens` ou tester `--no-reasoning`.
