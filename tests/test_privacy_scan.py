from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.privacy_scan import scan_repository


class PrivacyScanTests(unittest.TestCase):
    def make_repo(self, files: dict[str, str]) -> Path:
        temp = tempfile.TemporaryDirectory(prefix="privacy-scan-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        return root

    def rules(self, files: dict[str, str]) -> set[str]:
        return {finding.rule for finding in scan_repository(self.make_repo(files), include_history=False)}

    def test_documentation_safe_examples_pass(self) -> None:
        self.assertEqual(
            self.rules(
                {
                    ".env.example": "GMAIL_OWNER=owner@example.com\n",
                    "README.md": "Install in /opt/daily-brief-agent and use 192.0.2.10.\n",
                    "state/subscribers.example.json": '{"subscribers":["reader@example.com"]}\n',
                }
            ),
            set(),
        )

    def test_private_key_and_token_file_fail(self) -> None:
        key_header = "-----" + "BEGIN " + "PRIVATE KEY" + "-----\n"
        rules = self.rules({"secrets/token.json": key_header})
        self.assertIn("runtime-directory", rules)
        self.assertIn("runtime-or-secret-file", rules)
        self.assertIn("private-key-content", rules)

    def test_non_example_email_and_public_ip_fail(self) -> None:
        email = "person" + "@" + "company.com"
        public_ip = ".".join(("8", "8", "8", "8"))
        rules = self.rules({"notes.txt": f"{email} {public_ip}\n"})
        self.assertIn("non-example-email", rules)
        self.assertIn("public-ipv4", rules)

    def test_generated_report_path_fails(self) -> None:
        rules = self.rules({"logs/sent-message-20260101.md": "private report\n"})
        self.assertIn("runtime-directory", rules)
        self.assertIn("generated-report-or-bundle", rules)


if __name__ == "__main__":
    unittest.main()
