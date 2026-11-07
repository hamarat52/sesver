"""CI iş akışı (.github/workflows/windows-installer.yml) statik denetimleri.

Bulgu 5: her ``uses:`` 40 karakterlik commit SHA'sına sabit ve yanında sürüm yorumu var;
yazma yetkisi (contents: write) yalnız release job'unda ve o job kod checkout etmez.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "windows-installer.yml"

PINNED = re.compile(r"^\s*(?:-\s+)?uses:\s+([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@([0-9a-f]{40})\s+#\s+v\d+(?:\.\d+){1,2}\s*$")


def _workflow():
    import yaml  # PyYAML (huggingface-hub/transformers bağımlılığı olarak ortamda)
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


class PinnedActionsTests(unittest.TestCase):
    def test_every_uses_line_is_pinned_to_commit_sha_with_version_comment(self):
        lines = [ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
                 if re.match(r"^\s*(?:-\s+)?uses:", ln)]
        self.assertGreaterEqual(len(lines), 5)
        for ln in lines:
            self.assertRegex(ln, PINNED, ln.strip())

    def test_yaml_is_valid_and_parsed_steps_match(self):
        data = _workflow()
        self.assertIsInstance(data, dict)
        uses = [step["uses"] for job in data["jobs"].values() for step in job.get("steps", []) if "uses" in step]
        text_count = len(re.findall(r"(?m)^\s*(?:-\s+)?uses:", WORKFLOW.read_text(encoding="utf-8")))
        self.assertEqual(len(uses), text_count)
        for ref in uses:
            self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")  # YAML yorumu değere girmez

    def test_write_token_only_in_release_job_without_checkout(self):
        data = _workflow()
        self.assertEqual(data["permissions"], {"contents": "read"})
        writers = [name for name, job in data["jobs"].items()
                   if (job.get("permissions") or {}).get("contents") == "write"]
        self.assertEqual(writers, ["release"])
        release_uses = [s.get("uses", "") for s in data["jobs"]["release"]["steps"]]
        self.assertFalse([u for u in release_uses if u.startswith("actions/checkout@")])


if __name__ == "__main__":
    unittest.main()
