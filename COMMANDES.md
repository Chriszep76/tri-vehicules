# Commandes — tri-vehicules

Exemples prêts à copier (PowerShell / Windows).

Variables utilisées dans les exemples :
- Projet : `G:\git_chriszep76\tri-vehicules`
- Sortie : `G:\photos_piwigo\catégories`
- Source : `G:\photos_piwigo\2018\embarque` (à remplacer par ton dossier)

---

## 0. Construire l'image

```powershell
cd G:\git_chriszep76\tri-vehicules
docker compose build
```

## 1. Tester à blanc (aucun fichier déplacé)

```powershell
docker run --rm --name tri-vehicules --env-file "G:\git_chriszep76\tri-vehicules\.env" -v "G:\photos_piwigo\2018\embarque:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out --dry-run
```

Sur seulement 30 photos :

```powershell
docker run --rm --name tri-vehicules --env-file "G:\git_chriszep76\tri-vehicules\.env" -v "G:\photos_piwigo\2018\embarque:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out --dry-run --limit 30
```

## 2. Trier pour de vrai (déplace les photos)

```powershell
docker run --rm --name tri-vehicules --env-file "G:\git_chriszep76\tri-vehicules\.env" -v "G:\photos_piwigo\2018\embarque:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out
```

## 3. Changer le dossier source

Il suffit de changer le chemin à gauche du `:/data` :

```powershell
docker run --rm --name tri-vehicules --env-file "G:\git_chriszep76\tri-vehicules\.env" -v "G:\photos_piwigo\2018\un_autre_dossier:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out
```

Sans sous-dossiers (racine uniquement) :

```powershell
... tri-vehicules:latest --source /data --out /out --no-recursive
```

## 4. Choisir le modèle

```powershell
# DeepSeek (bon marché, par défaut)
... tri-vehicules:latest --source /data --out /out --model deepseek/deepseek-v4.1-flash

# Gemini
... tri-vehicules:latest --source /data --out /out --model google/gemini-2.5-flash

# Modèle plus précis (cas difficiles)
... tri-vehicules:latest --source /data --out /out --model anthropic/claude-3.7-sonnet
```

## 5. Options utiles

```powershell
--workers 8                 # plus de parallélisme (attention aux limites de débit)
--limit 50                  # ne traiter que 50 photos
--threshold-high 0.85       # exiger plus de certitude pour 'haute'
--threshold-mid 0.6         # 'moyenne' à partir de 0.6
--no-reasoning              # sortie JSON seule (modèles à raisonnement)
--max-tokens 3000           # plus de budget de sortie si réponses vides
--manifest /out/mon_log.csv # changer le nom/chemin du manifeste
```

Exemple combiné :

```powershell
docker run --rm --name tri-vehicules --env-file "G:\git_chriszep76\tri-vehicules\.env" -v "G:\photos_piwigo\2018\embarque:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out --workers 8 --limit 50
```

## 6. Avec docker compose

Le montage se fait via `.env` (`PHOTO_DIR` → `/data`, `OUT_DIR` → `/out`) :

```powershell
cd G:\git_chriszep76\tri-vehicules

# dry-run
docker compose run --rm --name tri-vehicules -T tri-vehicules --source /data --out /out --dry-run --limit 30

# réel
docker compose run --rm --name tri-vehicules -T tri-vehicules --source /data --out /out
```

## 7. Vérifier le résultat

```powershell
# Arborescence de sortie
Get-ChildItem -LiteralPath "G:\photos_piwigo\catégories" -Directory | ForEach-Object { "$($_.Name) : $((Get-ChildItem $_.FullName -File).Count)" }

# Dernières lignes du manifeste
Get-Content "G:\photos_piwigo\catégories\_tri_manifest.csv" -Tail 20
```

## 8. Arrêter / suivre un conteneur

```powershell
docker ps
docker logs -f tri-vehicules
docker stop tri-vehicules
```

## 9. Utiliser une clé explicite (sans fichier .env)

```powershell
docker run --rm --name tri-vehicules -e OPENROUTER_API_KEY=$env:OPENROUTER_API_KEY -e OPENROUTER_MODEL=deepseek/deepseek-v4.1-flash -v "G:\photos_piwigo\2018\embarque:/data" -v "G:\photos_piwigo\catégories:/out" tri-vehicules:latest --source /data --out /out
```

---

## Structure de sortie

```
G:\photos_piwigo\catégories\
├── Tiger I\            <- catégorie (créée à la volée)
├── Panzer IV\
├── ...
├── Infanterie\
├── _Divers (non-vehicule)\
├── _A_VERIFIER\        <- faible confiance, à revérifier
├── a_trier\            <- échecs (erreurs API)
└── _tri_manifest.csv   <- fichier_origine;dossier;confiance
```
