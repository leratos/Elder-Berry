"""Tests fuer scripts/portrait_scene_test.py (Phase 111, E1, §4.6 + Ae6a)."""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
from pathlib import Path

import pytest

from elder_berry.llm.image_generator import (
    ImageGenerator,
    ImageRequest,
    ImageResult,
    ImageStatus,
)
from elder_berry.room_display.portrait.scene_catalog import CORE_PROMPT

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "portrait_scene_test.py"
SECRET = "sk-or-v1-CLI-SECRET-should-never-hit-disk"
PNG = b"\x89PNG\r\n\x1a\nFAKE"


def _load():
    spec = importlib.util.spec_from_file_location("portrait_scene_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses brauchen das Modul in sys.modules
    spec.loader.exec_module(module)
    return module


cli = _load()


class FakeGenerator(ImageGenerator):
    def __init__(self, results=None):
        self.requests: list[ImageRequest] = []
        self._results = list(results or [])
        self.closed = False

    def generate(self, request: ImageRequest) -> ImageResult:
        self.requests.append(request)
        if self._results:
            return self._results.pop(0)
        return ImageResult(
            status=ImageStatus.OK,
            duration_s=12.3,
            image_bytes=PNG,
            cost_usd=0.025,
            http_status=200,
        )

    def close(self) -> None:
        self.closed = True


class Harness:
    def __init__(self, tmp_path: Path, results=None):
        self.tmp_path = tmp_path
        self.out = tmp_path / "out"
        self.generator = FakeGenerator(results)
        self.factory_calls: list[tuple] = []
        self.prompts: list[str] = []
        self.images = []
        for name in ("eine.jpg", "zwei.jpg"):
            path = tmp_path / name
            path.write_bytes(b"raw")
            self.images.append(path)

    def factory(self, api_key, model, quality, provider):
        self.factory_calls.append((api_key, model, quality, provider))
        return self.generator

    def read_key(self, prompt):
        self.prompts.append(prompt)
        return SECRET

    def run(self, *args):
        argv = [*map(str, args), "--out-dir", str(self.out)]
        return cli.main(
            argv,
            read_key=self.read_key,
            generator_factory=self.factory,
            image_loader=lambda path: b"\xff\xd8JPEG-" + path.name.encode(),
        )

    def rows(self, name="results.csv"):
        with (self.out / name).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))


def _ok(payload: bytes) -> ImageResult:
    return ImageResult(
        status=ImageStatus.OK, duration_s=1.0, image_bytes=payload, http_status=200
    )


# ---------------------------------------------------------------------------
# Argumente
# ---------------------------------------------------------------------------


class TestParser:
    def test_defaults(self):
        args = cli.parse_args(["a.jpg"])
        assert args.scene == "alle"
        assert args.runs == 1
        assert args.quality is None
        assert not args.no_zdr and not args.check_zdr

    def test_runs_must_be_positive(self):
        with pytest.raises(SystemExit):
            cli.parse_args(["a.jpg", "--runs", "0"])

    def test_quality_choices(self):
        with pytest.raises(SystemExit):
            cli.parse_args(["a.jpg", "--quality", "ultra"])
        assert cli.parse_args(["a.jpg", "--quality", "medium"]).quality == "medium"

    def test_no_zdr_and_check_zdr_exclusive(self):
        with pytest.raises(SystemExit):
            cli.parse_args(["a.jpg", "--no-zdr", "--check-zdr"])

    def test_image_required(self):
        with pytest.raises(SystemExit):
            cli.parse_args([])


# ---------------------------------------------------------------------------
# Laeufe + CSV
# ---------------------------------------------------------------------------


class TestRuns:
    def test_all_scenes_all_images_runs(self, tmp_path):
        h = Harness(tmp_path)
        assert h.run(*h.images, "--runs", "2") == 0
        rows = h.rows()
        assert len(rows) == 2 * 6 * 2
        assert len(h.generator.requests) == 24
        assert list(rows[0]) == list(cli.CSV_FIELDS)
        assert rows[0]["status"] == "ok"
        assert rows[0]["kosten_usd"] == "0.0250"
        assert rows[0]["dauer_s"] == "12.3"
        assert (h.out / rows[0]["bilddatei"]).read_bytes() == PNG
        assert h.generator.closed

    def test_every_request_carries_core_and_image(self, tmp_path):
        h = Harness(tmp_path)
        h.run(h.images[0], "--scene", "s3_crypt")
        request = h.generator.requests[0]
        assert request.prompt.endswith(CORE_PROMPT)
        assert "crypt" in request.prompt
        assert request.input_images == (b"\xff\xd8JPEG-eine.jpg",)

    def test_config_provider_and_quality_used_by_default(self, tmp_path):
        h = Harness(tmp_path)
        h.run(h.images[0], "--scene", "s1_moonlit_parlour")
        _, model, quality, provider = h.factory_calls[0]
        assert model == "openai/gpt-image-2.6-flare"
        assert quality == "low"
        assert provider == {"data_collection": "deny"}  # D8, #1482

    def test_no_zdr_sends_no_provider(self, tmp_path):
        h = Harness(tmp_path)
        h.run(
            h.images[0],
            "--scene",
            "s1_moonlit_parlour",
            "--no-zdr",
            "--quality",
            "medium",
        )
        _, _, quality, provider = h.factory_calls[0]
        assert provider == {}
        assert quality == "medium"

    def test_failed_run_has_status_codes_and_no_image(self, tmp_path):
        h = Harness(
            tmp_path,
            [
                ImageResult(
                    status=ImageStatus.REFUSED,
                    duration_s=1.0,
                    http_status=403,
                    error_code="403",
                    detail="flagged",
                )
            ],
        )
        h.run(h.images[0], "--scene", "s2_forgotten_library")
        row = h.rows()[0]
        assert row["status"] == "refused"
        assert row["http_status"] == "403"
        assert row["error_code"] == "403"
        assert row["bilddatei"] == ""
        assert "flagged_input" not in (h.out / "results.csv").read_text(
            encoding="utf-8"
        )

    def test_unknown_scene(self, tmp_path):
        h = Harness(tmp_path)
        assert h.run(h.images[0], "--scene", "nope") == 2
        assert h.factory_calls == []
        assert h.prompts == []  # kein Schluessel abgefragt

    def test_missing_image(self, tmp_path):
        h = Harness(tmp_path)
        assert h.run(tmp_path / "fehlt.jpg") == 2

    def test_empty_key_aborts(self, tmp_path):
        h = Harness(tmp_path)
        argv = [str(h.images[0]), "--out-dir", str(h.out)]
        assert (
            cli.main(
                argv,
                read_key=lambda _: "  ",
                generator_factory=h.factory,
                image_loader=lambda p: b"x",
            )
            == 2
        )
        assert h.factory_calls == []

    def test_key_asked_every_run_and_never_written(self, tmp_path):
        h = Harness(tmp_path)
        h.run(*h.images)
        h.run(h.images[0], "--check-zdr")
        assert len(h.prompts) == 2
        assert h.factory_calls[0][0] == SECRET
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert SECRET.encode() not in path.read_bytes(), path

    def test_no_secret_store_used(self):
        source = SCRIPT.read_text(encoding="utf-8")
        assert "SecretStore" not in source.split('"""', 2)[2]


# ---------------------------------------------------------------------------
# Keine Ueberschreibung (Codex-Befund PR #412)
# ---------------------------------------------------------------------------


class TestNoOverwrite:
    def test_inputs_with_same_stem_get_distinct_files(self, tmp_path):
        """foto.jpg aus zwei Ordnern + foto.png: drei Bilder, drei Dateien."""
        h = Harness(tmp_path, [_ok(b"PNG-A"), _ok(b"PNG-B"), _ok(b"PNG-C")])
        inputs = []
        for sub, name in (("a", "foto.jpg"), ("b", "foto.jpg"), ("c", "foto.png")):
            (tmp_path / sub).mkdir()
            path = tmp_path / sub / name
            path.write_bytes(b"raw")
            inputs.append(path)

        assert h.run(*inputs, "--scene", "s3_crypt") == 0

        rows = h.rows()
        assert [row["eingabe_nr"] for row in rows] == ["1", "2", "3"]
        assert [row["eingabe"] for row in rows] == ["foto.jpg", "foto.jpg", "foto.png"]
        files = [row["bilddatei"] for row in rows]
        assert len(set(files)) == 3
        assert [(h.out / f).read_bytes() for f in files] == [
            b"PNG-A",
            b"PNG-B",
            b"PNG-C",
        ]
        assert files[0] == "01_foto_s3_crypt_01.png"

    def test_reused_out_dir_keeps_previous_results(self, tmp_path):
        h = Harness(tmp_path, [_ok(b"ERSTER-LAUF"), _ok(b"ZWEITER-LAUF")])
        h.run(h.images[0], "--scene", "s3_crypt")
        h.run(h.images[0], "--scene", "s3_crypt")

        first, second = h.rows("results.csv"), h.rows("results_2.csv")
        assert first[0]["bilddatei"] == "01_eine_s3_crypt_01.png"
        assert second[0]["bilddatei"] == "01_eine_s3_crypt_01_2.png"
        assert (h.out / first[0]["bilddatei"]).read_bytes() == b"ERSTER-LAUF"
        assert (h.out / second[0]["bilddatei"]).read_bytes() == b"ZWEITER-LAUF"

    def test_write_new_counts_up(self, tmp_path):
        names = [cli._write_new(tmp_path, "x.png", bytes([i])) for i in range(3)]
        assert names == ["x.png", "x_2.png", "x_3.png"]
        assert (tmp_path / "x_3.png").read_bytes() == b"\x02"


# ---------------------------------------------------------------------------
# --check-zdr
# ---------------------------------------------------------------------------


class TestCheckZdr:
    def test_success(self, tmp_path, capsys):
        h = Harness(tmp_path)
        assert h.run(*h.images, "--check-zdr", "--runs", "5") == 0
        assert len(h.generator.requests) == 1  # genau ein Lauf, nur erstes Bild
        assert h.factory_calls[0][3] == {"data_collection": "deny", "zdr": True}
        assert "ZDR verfuegbar" in capsys.readouterr().out

    def test_forces_zdr_even_if_config_differs(self, tmp_path):
        scenes = tmp_path / "scenes.yaml"
        scenes.write_text(
            "generation:\n  model: m\n  quality: low\nscenes:\n  - id: a\n    prompt: A.\n",
            encoding="utf-8",
        )
        h = Harness(tmp_path)
        h.run(h.images[0], "--check-zdr", "--scenes-file", scenes)
        assert h.factory_calls[0][3] == {"data_collection": "deny", "zdr": True}

    def test_failure_reports_error(self, tmp_path, capsys):
        h = Harness(
            tmp_path,
            [
                ImageResult(
                    status=ImageStatus.ERROR,
                    duration_s=0.4,
                    http_status=404,
                    error_code="404",
                    detail="No endpoints found",
                )
            ],
        )
        assert h.run(h.images[0], "--check-zdr") == 1
        captured = capsys.readouterr()
        assert (
            "ZDR-Check fehlgeschlagen: status=error http=404 code=404" in captured.out
        )
        assert "No endpoints found" in captured.err


# ---------------------------------------------------------------------------
# Bildvorbereitung (Pillow)
# ---------------------------------------------------------------------------


class TestPrepareImage:
    def test_exif_rotation_and_downscale(self, tmp_path):
        image_mod = pytest.importorskip("PIL.Image")
        source = image_mod.new("RGB", (3000, 2000), (200, 10, 10))
        exif = image_mod.Exif()
        exif[0x0112] = 6  # Orientation: um 90 Grad drehen
        path = tmp_path / "foto.jpg"
        source.save(path, format="JPEG", exif=exif)

        data = cli.prepare_image(path)

        with image_mod.open(io.BytesIO(data)) as result:
            assert result.format == "JPEG"
            assert result.size == (683, 1024)  # hochkant nach EXIF, lange Kante 1024
