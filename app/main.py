import argparse
import base64
import csv
import io
import json
import logging
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, ImageOps

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pass

API_URL = "https://openrouter.ai/api/v1/chat/completions"
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif",
    ".tif", ".tiff", ".heic", ".heif", ".avif",
}

NON_VEHICLE = "_Divers (non-vehicule)"
VERIFY_DIR = "_A_VERIFIER"
FAIL_DIR = "a_trier"


def norm(text: str) -> str:
    return " ".join(text.strip().casefold().split())


def load_categories(path: Path) -> list:
    cats = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cats.append(line)
    return cats


def build_system_prompt(categories: list) -> str:
    listing = "\n".join(f"- {c}" for c in categories)
    return (
        "Tu es un expert en vehicules militaires allemands de la Seconde Guerre mondiale (1939-1945). "
        "On te presente une photo. Identifie le vehicule principal et classe-le dans EXACTEMENT une "
        "des categories de la liste ci-dessous. "
        f"S'il n'y a pas de vehicule identifiable mais des soldats d'infanterie, choisis \"Infanterie\". "
        f"Si aucun element militaire allemand n'est identifiable, choisis \"{NON_VEHICLE}\".\n\n"
        f"Liste des categories:\n{listing}\n\n"
        "Aide a l'identification: pour distinguer le Panzer III du Panzer IV, compte les galets superieurs "
        "(roues de retour, en haut de la chenille) : 3 galets superieurs = Panzer III, 4 galets superieurs = Panzer IV. "
        "Utilise ce repere des qu'il est visible.\n\n"
        "Regles: ne devine pas ; en cas de doute entre plusieurs modeles, choisis le plus probable et "
        "mets une confiance basse. Reponds UNIQUEMENT par un objet JSON valide, sans texte autour, au format: "
        '{"categorie": "<nom exact copie depuis la liste>", "confiance": 0.0-1.0, "raison": "courte explication en francais"}. '
        "confiance = ta certitude sur la categorie choisie."
    )


def encode_image(path: Path, max_side: int) -> str:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def parse_json(content: str) -> dict:
    text = content.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def classify(path: Path, args, api_key: str, system_prompt: str) -> dict:
    b64 = encode_image(path, args.max_side)
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Analyse cette image et reponds au format JSON demande."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": args.max_tokens,
    }
    if args.no_reasoning:
        payload["reasoning"] = {"enabled": False}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if args.referer:
        headers["HTTP-Referer"] = args.referer
    if args.title:
        headers["X-Title"] = args.title

    last_err = None
    for attempt in range(args.retries):
        try:
            resp = requests.post(API_URL, headers=headers, json=payload, timeout=args.timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"].get("content")
            if not content:
                raise RuntimeError(f"reponse vide du modele (finish_reason={choice.get('finish_reason')})")
            result = parse_json(content)
            try:
                confiance = float(result.get("confiance", 0.0))
            except (TypeError, ValueError):
                confiance = 0.0
            return {
                "categorie": str(result.get("categorie", "")),
                "confiance": confiance,
                "raison": str(result.get("raison", "")),
                "error": "",
            }
        except Exception as exc:
            last_err = exc
            if attempt < args.retries - 1:
                time.sleep(args.backoff * (attempt + 1))
    return {"categorie": "", "confiance": 0.0, "raison": "", "error": str(last_err)}


def iter_images(source: Path, recursive: bool):
    pattern = "**/*" if recursive else "*"
    for p in sorted(source.glob(pattern)):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def unique_dest(dest_dir: Path, filename: str) -> Path:
    target = dest_dir / filename
    if not target.exists():
        return target
    stem, suffix = Path(filename).stem, Path(filename).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def move_to(src: Path, dest_dir: Path, dry_run: bool):
    if dry_run:
        return dest_dir / src.name
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = unique_dest(dest_dir, src.name)
    shutil.move(str(src), str(target))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Trie des photos par vehicule (Allemagne 1939-1945) via OpenRouter.")
    parser.add_argument("--source", default="/data", help="Dossier des photos a trier.")
    parser.add_argument("--out", default=os.environ.get("OUT_DIR", "/out"),
                        help="Dossier racine de sortie (categories creees ici).")
    parser.add_argument("--categories", default=os.environ.get("CATEGORIES_FILE", "/app/categories.txt"))
    parser.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL", "google/gemini-2.0-flash-001"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-side", type=int, default=1024)
    parser.add_argument("--max-tokens", type=int, default=2048,
                        help="Budget de tokens de sortie (a augmenter pour les modeles a raisonnement).")
    parser.add_argument("--no-reasoning", action="store_true",
                        help="Desactive la reflexion du modele (si supporte) pour sortir seulement le JSON.")
    parser.add_argument("--threshold-high", type=float, default=0.8, help="Seuil de confiance 'haute'.")
    parser.add_argument("--threshold-mid", type=float, default=0.5, help="Seuil de confiance 'moyenne'.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--backoff", type=float, default=2.0)
    parser.add_argument("--recursive", action=argparse.BooleanOptionalAction, default=True,
                        help="Parcourt aussi les sous-dossiers (actif par defaut ; --no-recursive pour desactiver).")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-name", default=VERIFY_DIR)
    parser.add_argument("--fail-name", default=FAIL_DIR, help="Dossier des echecs (erreurs API).")
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--referer", default=os.environ.get("OPENROUTER_REFERER", ""))
    parser.add_argument("--title", default=os.environ.get("OPENROUTER_TITLE", "tri-vehicules"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        logging.error("OPENROUTER_API_KEY manquant.")
        return 2

    source = Path(args.source).resolve()
    if not source.is_dir():
        logging.error("Dossier source introuvable: %s", source)
        return 2

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cats_path = Path(args.categories)
    if not cats_path.is_file():
        logging.error("Fichier de categories introuvable: %s", cats_path)
        return 2

    categories = load_categories(cats_path)
    if norm(NON_VEHICLE) not in {norm(c) for c in categories}:
        categories.append(NON_VEHICLE)
    if not categories:
        logging.error("Aucune categorie definie dans %s", cats_path)
        return 2

    allowed = {norm(c): c for c in categories}
    nonveh_exact = allowed[norm(NON_VEHICLE)]
    system_prompt = build_system_prompt(categories)

    images = list(iter_images(source, args.recursive))
    if out != source and source in out.parents:
        images = [p for p in images if out not in p.parents]
    if args.limit > 0:
        images = images[: args.limit]

    logging.info("Modele: %s | %d categories | %d images | sortie: %s | dry-run: %s",
                 args.model, len(categories), len(images), out, args.dry_run)

    manifest_path = Path(args.manifest) if args.manifest else (out / "_tri_manifest.csv")
    manifest_exists = manifest_path.exists()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_file = open(manifest_path, "a", newline="", encoding="utf-8")
    writer = csv.writer(manifest_file, delimiter=";")
    if not manifest_exists:
        writer.writerow(["fichier_origine", "dossier", "confiance"])

    ranged = verify = failed = 0

    def decide(result) -> tuple:
        if result["error"]:
            return args.fail_name, "echec", "ECHEC"
        cat = allowed.get(norm(result["categorie"]))
        conf = result["confiance"]
        if cat is None:
            return args.verify_name, "basse", "DEPLACE"
        if cat == nonveh_exact:
            label = "haute" if conf >= args.threshold_high else ("moyenne" if conf >= args.threshold_mid else "basse")
            return cat, label, "DEPLACE"
        if conf >= args.threshold_high:
            return cat, "haute", "DEPLACE"
        if conf >= args.threshold_mid:
            return cat, "moyenne", "DEPLACE"
        return args.verify_name, "basse", "DEPLACE"

    def process(path: Path):
        result = classify(path, args, api_key, system_prompt)
        folder, label, action = decide(result)
        return path, result, folder, label, action

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process, p): p for p in images}
            for fut in as_completed(futures):
                path = futures[fut]
                try:
                    path, result, folder, label, action = fut.result()
                except Exception as exc:
                    writer.writerow([path.name, args.fail_name, "echec"])
                    manifest_file.flush()
                    try:
                        move_to(path, out / args.fail_name, args.dry_run)
                    except Exception:
                        pass
                    failed += 1
                    logging.warning("ECHEC %s -> %s", path.name, exc)
                    continue

                if action == "ECHEC":
                    failed += 1
                    logging.warning("ECHEC (API) %s -> %s | %s", path.name, args.fail_name, result["error"])
                elif action == "DEPLACE":
                    if folder == args.verify_name:
                        verify += 1
                    else:
                        ranged += 1
                    if args.dry_run:
                        logging.info("%s (dry-run) %.2f | %s | %s", folder, result["confiance"], path.name, result["raison"])
                    else:
                        logging.info("%s %.2f | %s | %s", folder, result["confiance"], path.name, result["raison"])

                if not args.dry_run:
                    try:
                        move_to(path, out / folder, False)
                    except Exception as exc:
                        failed += 1
                        logging.warning("ECHEC deplacement %s -> %s", path.name, exc)

                writer.writerow([path.name, folder, label])
                manifest_file.flush()
    finally:
        manifest_file.close()

    logging.info("Termine. Ranges=%d | A verifier=%d | Echecs(a_trier)=%d", ranged, verify, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
