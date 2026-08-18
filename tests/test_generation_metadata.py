from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from daily_brief_agent.generation_metadata import aggregate_usage, annotate_message


class GenerationMetadataTests(unittest.TestCase):
    def write_events(self, directory: Path, name: str, lines: list[object]) -> Path:
        path = directory / name
        with path.open("w", encoding="utf-8") as handle:
            for line in lines:
                if isinstance(line, str):
                    handle.write(line)
                else:
                    handle.write(json.dumps(line))
                handle.write("\n")
        return path

    def test_aggregates_total_tokens_across_calls_and_ignores_other_events(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            first = self.write_events(
                directory,
                "first.jsonl",
                [
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "ignored"}},
                    "not-json",
                ],
            )
            second = self.write_events(
                directory,
                "second.jsonl",
                [
                    {
                        "type": "response.completed",
                        "usage": {"input_tokens": 4, "output_tokens": 6},
                    }
                ],
            )

            summary = aggregate_usage([first, second])

        self.assertEqual(summary.total_tokens, 25)
        self.assertEqual(summary.usage_events, 2)
        self.assertEqual(summary.malformed_lines, 1)

    def test_invalid_token_fields_do_not_create_a_fake_total(self) -> None:
        with tempfile.TemporaryDirectory() as raw_directory:
            path = self.write_events(
                Path(raw_directory),
                "invalid.jsonl",
                [
                    {"type": "turn.completed", "usage": {"total_tokens": -1}},
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": True, "output_tokens": "not-a-number"},
                    },
                ],
            )
            summary = aggregate_usage([path])

        self.assertIsNone(summary.total_tokens)
        self.assertEqual(summary.usage_events, 0)

    def test_annotation_is_subtle_after_header_and_preserves_subject(self) -> None:
        content = (
            "Subject: 每日大事与市场简报 - 2026-08-18 11:00 中国时间\n"
            "<html><body><header><h1>每日大事与市场简报</h1>"
            "<p class='meta'>2026年8月18日 11:00</p></header>"
            "<h2>一、本期要点</h2></body></html>"
        )

        annotated = annotate_message(content, "model<&", 123456)

        self.assertTrue(annotated.startswith("Subject: 每日大事与市场简报"))
        self.assertEqual(annotated.count("brief-model-note"), 1)
        self.assertLess(annotated.index("</header>"), annotated.index("brief-model-note"))
        self.assertIn("生成模型 model&lt;&amp;", annotated)
        self.assertIn("本次总用量：123,456 tokens", annotated)
        self.assertIn("font-size:11px", annotated)

    def test_repeated_annotation_replaces_existing_note(self) -> None:
        content = "<html><body><h1>标题</h1><h2>正文</h2></body></html>"

        first = annotate_message(content, "old-model", 10)
        second = annotate_message(first, "new-model", None)

        self.assertEqual(second.count("brief-model-note"), 1)
        self.assertNotIn("old-model", second)
        self.assertIn("生成模型 new-model", second)
        self.assertIn("本次总用量：暂不可得", second)

    def test_annotation_requires_an_html_insertion_point(self) -> None:
        with self.assertRaises(ValueError):
            annotate_message("Subject: title\nplain text", "model", 1)


if __name__ == "__main__":
    unittest.main()
