"""SDK가 없는 호스트의 안내와 잘못된 HEF 선택을 검증."""

from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

from piwankanobi.cli import run
from piwankanobi.models import download_instructions


ROOT = Path(__file__).resolve().parent.parent


class ModelSelectionTests(unittest.TestCase):
    def test_qwen3_is_rejected_before_inference_on_installed_old_sdk(self):
        output = StringIO()
        with patch("piwankanobi.cli.runtime_version", return_value="5.1.1"):
            with redirect_stderr(output):
                self.assertEqual(run(["--model", "qwen3-vl-2b"]), 2)
        self.assertIn("Qwen3-VL-2B-Instruct", output.getvalue())
        self.assertIn("5.1.1", output.getvalue())
        self.assertIn("5.4.0", output.getvalue())

    def test_missing_model_instructions_use_selected_model_and_runtime(self):
        command = download_instructions("qwen3-vl-2b", "5.4.0")
        self.assertIn("/v5.4.0/blob/Qwen3-VL-2B-Instruct.hef", command)
        self.assertIn("/models/5.4.0/", command)


class WithoutSDKTests(unittest.TestCase):
    def invoke_without_site_packages(self, *args):
        return subprocess.run(
            [sys.executable, "-S", str(ROOT / "main.py"), *args],
            text=True, capture_output=True, timeout=10,
        )

    def test_help_and_model_list_work_without_site_packages(self):
        for flag in ("--help", "--list-models"):
            with self.subTest(flag=flag):
                result = self.invoke_without_site_packages(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("qwen3-vl-2b", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_missing_sdk_has_actionable_error_without_traceback(self):
        result = self.invoke_without_site_packages("--prompt", "Hello")
        self.assertEqual(result.returncode, 2)
        self.assertIn(".venv", result.stderr)
        self.assertIn("./run.sh", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_doctor_reports_unavailable_dependencies_without_loading_a_model(self):
        result = self.invoke_without_site_packages("--doctor")
        self.assertEqual(result.returncode, 2)
        self.assertIn("[error] numpy", result.stdout)
        self.assertIn("[error] cv2", result.stdout)
        self.assertIn(".venv", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


class DoctorDeviceTests(unittest.TestCase):
    def test_doctor_accepts_driver_node(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            hef = Path(temporary_dir) / "model.hef"
            hef.touch()
            output = StringIO()
            with (
                patch("piwankanobi.cli.runtime_version", return_value="5.4.0"),
                patch("piwankanobi.cli.Path.glob", side_effect=lambda pattern: (
                    iter([Path("/dev/h1x-0")]) if pattern == "h1x-[0-9]*" else iter([])
                )),
                patch("piwankanobi.cli.importlib.import_module", return_value=SimpleNamespace(
                    __version__="mock",
                )),
                redirect_stdout(output),
            ):
                self.assertEqual(run(["--doctor", "--hef", str(hef)]), 0)
            self.assertIn("[ok] Hailo device: /dev/h1x-0", output.getvalue())
            self.assertIn("[ok] HailoRT Python SDK: 5.4.0", output.getvalue())
            self.assertIn(f"[ok] HEF: {hef}", output.getvalue())


class LauncherTests(unittest.TestCase):
    def test_launcher_requires_project_python_and_preserves_arguments(self):
        with tempfile.TemporaryDirectory(prefix="piWanKanobi launcher ") as temporary_dir:
            project = Path(temporary_dir)
            shutil.copy2(ROOT / "run.sh", project / "run.sh")
            (project / "main.py").write_text(
                "import json, sys\n"
                "print(sys.executable)\n"
                "print(json.dumps(sys.argv[1:]))\n",
            )
            arguments = ["--prompt", "an image with spaces", "--image", "a picture.png"]

            def launch():
                return subprocess.run(
                    [str(project / "run.sh"), *arguments],
                    cwd="/", text=True, capture_output=True, timeout=10,
                )

            missing = launch()
            self.assertEqual(missing.returncode, 2)
            self.assertIn(".venv", missing.stderr)

            project_python = project / ".venv" / "bin" / "python"
            project_python.parent.mkdir(parents=True)
            project_python.symlink_to("/usr/bin/python3")
            result = launch()
            self.assertEqual(result.returncode, 0, result.stderr)
            interpreter, forwarded_arguments = result.stdout.splitlines()
            self.assertEqual(interpreter, str(project_python))
            self.assertEqual(json.loads(forwarded_arguments), arguments)


if __name__ == "__main__":
    unittest.main()
