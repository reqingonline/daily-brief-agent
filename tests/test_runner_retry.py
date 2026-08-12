from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER = REPO_ROOT / "scripts" / "run-daily-brief.sh"


def bash_executable() -> str:
    configured = os.environ.get("DAILY_BRIEF_TEST_BASH")
    if configured:
        return configured
    if os.name == "nt":
        for candidate in (Path("D:/Git/bin/bash.exe"), Path("C:/Program Files/Git/bin/bash.exe")):
            if candidate.is_file():
                return str(candidate)
    found = shutil.which("bash")
    if not found:
        raise unittest.SkipTest("Bash is required for orchestration tests")
    return found


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


class RunnerRetryTests(unittest.TestCase):
    def test_invalid_first_draft_is_repaired_before_fake_smtp(self) -> None:
        with tempfile.TemporaryDirectory(prefix="daily-brief-runner-") as raw_root:
            root = Path(raw_root)
            for directory in ("scripts", "config", "state", "logs", "workspace", "bin"):
                (root / directory).mkdir()
            shutil.copy2(RUNNER, root / "scripts" / RUNNER.name)
            (root / "scripts" / RUNNER.name).chmod(0o755)
            (root / "config" / "brief-prompt.txt").write_text("test prompt\n", encoding="utf-8")
            (root / "config" / "source-policy.txt").write_text("test policy\n", encoding="utf-8")
            (root / "config" / "codex-runtime.env").write_text(
                "CODEX_MODEL=test-model\nCODEX_REASONING_EFFORT=low\n", encoding="utf-8"
            )
            (root / "state" / "daily-brief-subscribers.json").write_text(
                '{"version":1,"owner":"owner@example.com","fixed_recipients":[],"subscribers":["reader@example.com"],"updated_at":"2026-01-01T00:00:00+08:00"}\n',
                encoding="utf-8",
            )
            (root / "state" / "subscription-preflight.ok").write_text(
                f"{int(__import__('time').time())}\n", encoding="utf-8"
            )

            write_executable(
                root / "bin" / "fake-python",
                """#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "-m" ]]
module="$2"
shift 2
case "$module" in
  fake.editorial)
    while (($#)); do
      if [[ "$1" == "--output" ]]; then output="$2"; shift 2; else shift; fi
    done
    printf 'editorial fixture\\n' > "$output"
    echo 'editorial_context=ok'
    ;;
  fake.collector)
    while (($#)); do
      case "$1" in
        --output) output="$2"; shift 2 ;;
        --json-output) json_output="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    printf 'source fixture\\n' > "$output"
    printf '{"fixture":true}\\n' > "$json_output"
    echo 'source_collection=news:1 lanes:1/1 fact_checks:1 think_tanks:1 war:1 markets:1/1'
    ;;
  fake.validator)
    message="$1"
    if grep -q 'CONCENTRATED_SOURCE' "$message"; then
      echo 'brief_validation_error=source_concentration_exceeded:全球重大事件' >&2
      exit 1
    fi
    echo 'brief_validation=ok'
    ;;
  fake.smtp)
    printf 'called\\n' > "${FAKE_SMTP_MARKER:?}"
    echo 'recipient_count=1'
    echo 'send_success=1 send_failed=0'
    ;;
  *)
    echo "unexpected fake module: $module" >&2
    exit 2
    ;;
esac
""",
            )
            write_executable(
                root / "bin" / "fake-codex",
                """#!/usr/bin/env bash
set -euo pipefail
output=''
while (($#)); do
  if [[ "$1" == '--output-last-message' ]]; then output="$2"; shift 2; else shift; fi
done
count=0
[[ ! -r "${FAKE_CALLS_FILE:?}" ]] || count="$(<"$FAKE_CALLS_FILE")"
count=$((count + 1))
printf '%s\\n' "$count" > "$FAKE_CALLS_FILE"
cat > "${FAKE_PROMPT_PREFIX:?}-$count.txt"
{
  printf 'Subject: 每日大事与市场简报 - 2026-01-01 11:00 中国时间\\n'
  printf '<html><body><h2>全球重大事件</h2><p>完整测试内容</p>'
  printf '<h2>事实核查</h2><p>测试</p><h2>国际关系观察</h2><p>测试</p>'
  printf '<h2>权威智库报告</h2><p>测试</p><h2>国际战争观察</h2><p>测试</p>'
  printf '<h2>历史上的今天</h2><p>测试</p>'
  if (( count == 1 )); then printf 'CONCENTRATED_SOURCE'; fi
  for _ in {1..800}; do printf '补充'; done
  printf '</body></html>\\n'
} > "$output"
""",
            )

            env = os.environ.copy()
            env.update(
                {
                    "DAILY_BRIEF_PYTHON": "bin/fake-python",
                    "CODEX_BIN": "bin/fake-codex",
                    "BRIEF_EDITORIAL_MODULE": "fake.editorial",
                    "BRIEF_COLLECTOR_MODULE": "fake.collector",
                    "BRIEF_VALIDATOR_MODULE": "fake.validator",
                    "BRIEF_SMTP_MODULE": "fake.smtp",
                    "FAKE_CALLS_FILE": "codex.calls",
                    "FAKE_SMTP_MARKER": "smtp.called",
                    "FAKE_PROMPT_PREFIX": "prompt",
                }
            )
            completed = subprocess.run(
                [bash_executable(), "scripts/run-daily-brief.sh"],
                cwd=root,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=30,
                check=False,
            )

            combined = completed.stdout + "\n" + completed.stderr
            self.assertEqual(completed.returncode, 0, combined)
            self.assertEqual((root / "codex.calls").read_text(encoding="utf-8").strip(), "2")
            self.assertTrue((root / "smtp.called").is_file())
            self.assertIn("brief_validation_error=source_concentration_exceeded:全球重大事件", combined)
            self.assertIn("brief_repair_attempt=1", combined)
            self.assertIn("brief_repair=ok attempts=1", combined)
            self.assertIn("recipient_count=1", combined)
            self.assertIn("send_success=1 send_failed=0", combined)
            self.assertIn("model_generation_seconds=", combined)
            self.assertIn("smtp_seconds=", combined)
            self.assertIn("total_seconds=", combined)
            repaired_prompt = (root / "prompt-2.txt").read_text(encoding="utf-8")
            self.assertIn("source_concentration_exceeded:全球重大事件", repaired_prompt)
            self.assertIn("不得降低、删除或绕过原有质量标准", repaired_prompt)


if __name__ == "__main__":
    unittest.main()
