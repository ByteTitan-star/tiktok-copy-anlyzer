import io
import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError
from engine import DEMO_TEXT, Input, Report, analyze, validate_source


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.data = Input(text=DEMO_TEXT)
        self.report = analyze(self.data, "mock")

    def test_demo(self):
        self.assertEqual(len(self.report.sentences), 5)
        self.assertEqual({a.level for a in self.report.assets}, {"L1", "L2", "L3"})
        self.assertEqual(self.report.sentences[-1].role, "CTA")
        self.assertEqual(self.report, Report.model_validate_json(self.report.model_dump_json()))

    def test_boundaries(self):
        data = Input(text=" \r\nWait...   really?\r\nDon’t   move.  ")
        result = analyze(data, "mock")
        self.assertEqual(result.sentences[-1].original, "Don’t   move.")
        validate_source(result, data)

    def test_change_or_omission(self):
        for edit in ("rewrite", "drop", "swap"):
            with self.subTest(edit):
                report = self.report.model_copy(deep=True)
                if edit == "rewrite":
                    report.sentences[0].original = report.sentences[0].original.lower()
                elif edit == "drop":
                    report.sentences.pop(1)
                else:
                    report.sentences.reverse()
                with self.assertRaises(ValueError):
                    validate_source(report, self.data)

    def test_invalid_reference(self):
        for sources in ([], [0], [2, 2], [7]):
            self.report.assets[0].sources = sources
            with self.assertRaises(ValueError):
                validate_source(self.report, self.data)

    def test_schema(self):
        schema = Report.model_json_schema()
        for model in [schema, *schema["$defs"].values()]:
            self.assertFalse(model["additionalProperties"])
            self.assertEqual(set(model["required"]), set(model["properties"]))
        for data in ({"text":"   "}, {"text":"abc", "video":"javascript:abc"}, {"text":"a" * 12001},
                     {"text":"example", "wrong":"field"}):
            with self.assertRaises(ValidationError):
                Input(**data)

    @patch.dict("os.environ", {"LLM_API_KEY":"offline-unit-test", "LLM_MODEL":"test-model",
                               "LLM_BASE_URL":"https://example.invalid/v1"})
    @patch("engine.urllib.request.urlopen")
    def test_live_contract(self, open_request):
        response = {"choices":[{"message":{"content":self.report.model_dump_json()}, "finish_reason":"stop"}]}
        open_request.return_value = io.BytesIO(json.dumps(response).encode())
        self.assertEqual(analyze(self.data, "live"), self.report)
        req = open_request.call_args.args[0]
        self.assertEqual(req.full_url, "https://example.invalid/v1/chat/completions")
        payload = json.loads(req.data)
        self.assertEqual(json.loads(payload["messages"][1]["content"])["text"], DEMO_TEXT)
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], Report.model_json_schema())

    @patch("engine._model_json")
    def test_invalid_model_output_retry(self, model_json):
        model_json.side_effect = ["{}", self.report.model_dump_json()]
        self.assertEqual(analyze(self.data, "live"), self.report)
        self.assertEqual(model_json.call_count, 2)

    @patch("engine._model_json", return_value='{}')
    def test_persistent_invalid_output(self, model_json):
        with self.assertRaisesRegex(ValueError, "两次"):
            analyze(self.data, "live")


if __name__ == "__main__":
    unittest.main()
