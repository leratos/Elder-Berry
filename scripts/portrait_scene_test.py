"""Szenen-Test-CLI fuer das Grusel-Portrait (Phase 111, Konzept §4.6).

Testet die Szenen aus ``scenes.yaml`` mit DEMSELBEN Generator und Katalog wie
der Betrieb. Ersetzt das Wegwerf-Skript aus #1466.

Schluessel: wird bei JEDEM Lauf per ``getpass`` abgefragt und nirgends
gespeichert -- KEIN SecretStore (Ae6a, #1474: ein SecretStore mit
``use_keyring=False`` auf Leras Rechner koennte einen bestehenden Store im
Keyring-Modus unlesbar machen).

Verwendung (Beispiele)::

    # ZDR-Check (Diagnose): ein Lauf mit data_collection=deny + zdr=true.
    # Fuer flare wird derzeit ein Fehlschlag erwartet (#1478, D8).
    python scripts/portrait_scene_test.py --check-zdr fotos/eine_person.jpg

    # Alle Szenen, je 2 Laeufe, mit zwei Eingabebildern
    python scripts/portrait_scene_test.py fotos/eine_person.jpg fotos/zwei.jpg --runs 2

    # Eine Szene, Qualitaet medium, ohne provider-Optionen
    python scripts/portrait_scene_test.py fotos/zwei.jpg --scene s3_crypt \
        --quality medium --no-zdr

Ausgabe: ``results.csv`` und die Ergebnisbilder in einem neuen
Temp-Verzeichnis, dessen Pfad am Ende ausgegeben wird. Die CSV enthaelt kein
``flagged_input`` und keinen Schluessel.

Kosten: Jeder Lauf ist eine echte Generierung (Testpreis laut #1451 ca.
0,02-0,033 USD pro Bild). Laeufe = Eingabebilder x Szenen x ``--runs``.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import io
import logging
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Repo-Root in PYTHONPATH einbinden, damit `python scripts/...` ohne
# Install-in-Editable-Mode funktioniert (Muster set_dashboard_password.py).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from elder_berry.llm.image_generator import (  # noqa: E402
    ImageGenerator,
    ImageRequest,
    ImageResult,
)
from elder_berry.llm.openrouter_image_generator import (  # noqa: E402
    OpenRouterImageGenerator,
)
from elder_berry.room_display.portrait.scene_catalog import (  # noqa: E402
    ALLOWED_QUALITIES,
    SceneCatalog,
    SceneCatalogError,
    compose_prompt,
)

logger = logging.getLogger("elder_berry.portrait_scene_test")

ALL_SCENES = "alle"
MAX_INPUT_EDGE_PX = 1024
ZDR_PROVIDER_OPTIONS: dict[str, object] = {"data_collection": "deny", "zdr": True}

CSV_FIELDS = (
    "zeit",
    "eingabe_nr",
    "eingabe",
    "lauf",
    "szene",
    "status",
    "http_status",
    "error_code",
    "dauer_s",
    "kosten_usd",
    "bilddatei",
)

#: (api_key, model, quality, provider_options) -> ImageGenerator
GeneratorFactory = Callable[[str, str, str, dict[str, object]], ImageGenerator]


@dataclass(frozen=True)
class InputImage:
    """Ein vorbereitetes Eingabebild.

    ``number`` ist die laufende Nummer (1-basiert) in der Reihenfolge der
    Kommandozeile. Sie macht Ausgabedateien und CSV-Zeilen eindeutig, auch
    wenn zwei Eingaben denselben Dateinamen haben (``foto.jpg`` aus zwei
    Ordnern, ``foto.jpg`` und ``foto.png``).
    """

    number: int
    name: str
    jpeg: bytes = field(repr=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Szenen-Test fuer das Grusel-Portrait (Phase 111).",
    )
    parser.add_argument("images", nargs="+", type=Path, help="Eingabebild(er)")
    parser.add_argument(
        "--scene",
        default=ALL_SCENES,
        help=f"Szenen-ID aus scenes.yaml oder '{ALL_SCENES}' (Default)",
    )
    parser.add_argument(
        "--runs", type=int, default=1, help="Laeufe je Bild und Szene (Default 1)"
    )
    parser.add_argument(
        "--quality",
        choices=sorted(ALLOWED_QUALITIES),
        default=None,
        help="Qualitaet (Default: aus scenes.yaml)",
    )
    zdr = parser.add_mutually_exclusive_group()
    zdr.add_argument(
        "--no-zdr",
        action="store_true",
        help="provider-Optionen aus scenes.yaml NICHT senden",
    )
    zdr.add_argument(
        "--check-zdr",
        action="store_true",
        help=(
            "Diagnose: ein Lauf mit data_collection=deny + zdr=true; meldet "
            "Erfolg oder Fehler. Erwartet derzeit einen Fehlschlag fuer "
            "flare (elder-berry#1478)"
        ),
    )
    parser.add_argument(
        "--scenes-file",
        type=Path,
        default=None,
        help="Andere Szenendatei (Default: Paket)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Ausgabeverzeichnis (Default: neues Temp-Verzeichnis)",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs muss >= 1 sein")
    return args


def prepare_image(path: Path) -> bytes:
    """EXIF-Drehung, Verkleinerung auf 1024 px, JPEG -- alles im RAM."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:  # pragma: no cover -- Umgebungsfehler
        raise SystemExit("Pillow fehlt: pip install Pillow") from exc
    with Image.open(path) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((MAX_INPUT_EDGE_PX, MAX_INPUT_EDGE_PX))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def default_generator_factory(
    api_key: str, model: str, quality: str, provider: dict[str, object]
) -> ImageGenerator:
    return OpenRouterImageGenerator(
        api_key, model=model, quality=quality, provider_options=provider
    )


def _write_new(out_dir: Path, filename: str, data: bytes) -> str:
    """Schreibt ``data`` exklusiv, ohne eine vorhandene Datei zu ersetzen.

    Existiert ``filename`` schon (z.B. weil ``--out-dir`` wiederverwendet
    wird), bekommt die neue Datei einen Zaehler angehaengt. Ein bezahltes
    Ergebnis geht so nie durch Ueberschreiben verloren.

    Returns:
        Der tatsaechlich verwendete Dateiname.
    """
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = filename
    counter = 1
    while True:
        try:
            with (out_dir / candidate).open("xb") as handle:
                handle.write(data)
            return candidate
        except FileExistsError:
            counter += 1
            candidate = f"{stem}_{counter}{suffix}"


def _row(
    image: InputImage, run: int, scene_id: str, result: ImageResult, image_file: str
) -> dict[str, str]:
    return {
        "zeit": datetime.now().isoformat(timespec="seconds"),
        "eingabe_nr": str(image.number),
        "eingabe": image.name,
        "lauf": str(run),
        "szene": scene_id,
        "status": result.status.value,
        "http_status": "" if result.http_status is None else str(result.http_status),
        "error_code": result.error_code or "",
        "dauer_s": f"{result.duration_s:.1f}",
        "kosten_usd": "" if result.cost_usd is None else f"{result.cost_usd:.4f}",
        "bilddatei": image_file,
    }


def run_scene_tests(
    generator: ImageGenerator,
    catalog: SceneCatalog,
    images: Sequence[InputImage],
    scene_ids: Sequence[str],
    runs: int,
    out_dir: Path,
) -> list[dict[str, str]]:
    """Fuehrt alle Laeufe aus, speichert OK-Bilder, liefert die CSV-Zeilen."""
    rows: list[dict[str, str]] = []
    for image in images:
        for scene_id in scene_ids:
            prompt = compose_prompt(catalog.get(scene_id))
            for run in range(1, runs + 1):
                result = generator.generate(
                    ImageRequest(prompt=prompt, input_images=(image.jpeg,))
                )
                image_file = ""
                if result.ok and result.image_bytes is not None:
                    image_file = _write_new(
                        out_dir,
                        f"{image.number:02d}_{Path(image.name).stem}"
                        f"_{scene_id}_{run:02d}.png",
                        result.image_bytes,
                    )
                elif result.detail:
                    print(
                        f"  #{image.number} {image.name} / {scene_id} / {run}: "
                        f"{result.status.value} ({result.detail})",
                        file=sys.stderr,
                    )
                rows.append(_row(image, run, scene_id, result, image_file))
                print(
                    f"#{image.number} {image.name} {scene_id} lauf {run}: "
                    f"{result.status.value} "
                    f"{result.duration_s:.1f}s"
                )
    return rows


def write_csv(rows: Sequence[dict[str, str]], out_dir: Path) -> Path:
    """Schreibt ``results.csv`` (bzw. ``results_2.csv`` ..., falls vorhanden).

    Returns:
        Pfad der geschriebenen CSV.
    """
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    name = _write_new(out_dir, "results.csv", buffer.getvalue().encode("utf-8"))
    return out_dir / name


def main(
    argv: Sequence[str] | None = None,
    *,
    read_key: Callable[[str], str] = getpass.getpass,
    generator_factory: GeneratorFactory = default_generator_factory,
    image_loader: Callable[[Path], bytes] = prepare_image,
) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    # httpx loggt sonst jede Request-Zeile; Bodies loggt es nie, aber leiser ist besser.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        catalog = SceneCatalog.load(args.scenes_file)
    except SceneCatalogError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2

    if args.check_zdr:
        scene_ids = [catalog.scenes[0].id if args.scene == ALL_SCENES else args.scene]
    elif args.scene == ALL_SCENES:
        scene_ids = [scene.id for scene in catalog.scenes]
    else:
        scene_ids = [args.scene]
    unknown = [sid for sid in scene_ids if sid not in {s.id for s in catalog.scenes}]
    if unknown:
        print(f"Fehler: unbekannte Szene {unknown[0]!r}", file=sys.stderr)
        return 2

    missing = [path for path in args.images if not path.is_file()]
    if missing:
        print(f"Fehler: Datei nicht gefunden: {missing[0]}", file=sys.stderr)
        return 2
    image_paths = args.images[:1] if args.check_zdr else args.images
    images = [
        InputImage(number, path.name, image_loader(path))
        for number, path in enumerate(image_paths, start=1)
    ]

    if args.check_zdr:
        provider: dict[str, object] = dict(ZDR_PROVIDER_OPTIONS)
    elif args.no_zdr:
        provider = {}
    else:
        provider = dict(catalog.generation.provider_options)
    quality = args.quality or catalog.generation.quality
    runs = 1 if args.check_zdr else args.runs

    api_key = read_key("OpenRouter-Schluessel (Eingabe verdeckt): ").strip()
    if not api_key:
        print("Fehler: kein Schluessel eingegeben.", file=sys.stderr)
        return 2
    generator = generator_factory(api_key, catalog.generation.model, quality, provider)
    del api_key

    out_dir = args.out_dir or Path(tempfile.mkdtemp(prefix="portrait_scene_test_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"Modell {catalog.generation.model}, Qualitaet {quality}, "
        f"provider={provider or '-'}, Laeufe={len(images) * len(scene_ids) * runs}"
    )
    try:
        rows = run_scene_tests(generator, catalog, images, scene_ids, runs, out_dir)
    finally:
        close = getattr(generator, "close", None)
        if callable(close):
            close()
    csv_path = write_csv(rows, out_dir)
    print(f"Ergebnisse: {out_dir} (CSV: {csv_path.name})")

    if args.check_zdr:
        row = rows[0]
        if row["status"] == "ok":
            print("ZDR verfuegbar")
            return 0
        print(
            f"ZDR-Check fehlgeschlagen: status={row['status']} "
            f"http={row['http_status'] or '-'} code={row['error_code'] or '-'}"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
