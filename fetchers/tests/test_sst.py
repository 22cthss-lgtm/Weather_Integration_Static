import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

FETCHERS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FETCHERS))
from src.services.ocean_service import OceanService


class OceanServiceTests(unittest.TestCase):
    def test_product_date_is_separate_from_utc_fetch_time(self):
        service = OceanService()
        with patch.object(service, "resolve_latest_sst_image", return_value=(
            "https://www.data.jma.go.jp/example.gif", "2026-10-20"
        )):
            payload = next(service.fetch())
        self.assertEqual(payload.image_time, "2026-10-20")
        self.assertTrue(payload.fetched_at.endswith("+00:00"))
        self.assertIn("2026-10-20", payload.title)

    def test_unresolved_source_raises_instead_of_returning_empty(self):
        with patch.object(OceanService, "resolve_latest_sst_image", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "SST"):
                list(OceanService().fetch())


class PublicationTests(unittest.TestCase):
    def load_runner(self):
        path = FETCHERS / "update_sst.py"
        self.assertTrue(path.is_file(), "Standalone SST entry point is missing")
        spec = importlib.util.spec_from_file_location("update_sst", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_failed_fetch_keeps_existing_json(self):
        runner = self.load_runner()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "latest.json"
            original = b'{"previous_success": true}\n'
            output.write_bytes(original)
            with patch.object(runner.OceanService, "fetch", side_effect=RuntimeError("source unavailable")):
                with self.assertRaises(RuntimeError):
                    runner.update_sst(output)
            self.assertEqual(output.read_bytes(), original)

    def test_empty_fetch_keeps_existing_json(self):
        runner = self.load_runner()
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "latest.json"
            output.write_text("previous success", encoding="utf-8")
            with patch.object(runner.OceanService, "fetch", return_value=iter(())):
                with self.assertRaises(RuntimeError):
                    runner.update_sst(output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous success")

    def test_replace_failure_keeps_previous_file_and_cleans_temporary_file(self):
        runner = self.load_runner()
        service = OceanService()
        payload = service.build_payload("sst", "SST", "https://example.com/sst.gif", service.sst_source_url, "2026-10-20")
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "latest.json"
            output.write_text("previous success", encoding="utf-8")
            with patch.object(runner.OceanService, "fetch", return_value=iter([payload])):
                with patch("src.publication.os.replace", side_effect=OSError("replace denied")):
                    with self.assertRaises(OSError):
                        runner.update_sst(output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous success")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_success_writes_single_payload_without_database_fields(self):
        runner = self.load_runner()
        service = OceanService()
        payload = service.build_payload("sst", "SST", "https://example.com/sst.gif", service.sst_source_url, "2026-10-20")
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            output = Path(directory) / "data" / "latest.json"
            with patch.object(runner.OceanService, "fetch", return_value=iter([payload])):
                runner.update_sst(output)
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["image_type"], "sst")
            self.assertEqual(data["image_time"], "2026-10-20")
            self.assertEqual(set(data), {"image_type", "source", "title", "image_url", "source_url", "fetched_at", "image_time"})


if __name__ == "__main__":
    unittest.main()
