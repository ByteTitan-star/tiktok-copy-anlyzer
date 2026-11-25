"""Offline adapter contract tests, including an acknowledgement lost after creation."""

import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from feishu import Feishu, FeishuError, _exchange


class BaseStub:
    def __init__(self):
        self.tables = {}
        self.records = {}
        self.creates = 0
        self.fail_after_table = None
        self.fail_after_record = False
        self.tokens = []

    def request(self, method, path, body=None, params=None):
        if path.endswith("/tables"):
            if method == "GET":
                return {"items": [{"name": v["name"], "table_id": k} for k, v in self.tables.items()]}
            spec = body["table"]
            table_id = "tbl" + str(len(self.tables) + 1)
            self.tables[table_id] = spec
            if self.fail_after_table == spec["name"]:
                self.fail_after_table = None
                raise FeishuError("simulated lost acknowledgement")
            return {"table_id": table_id}
        if path.endswith("/fields"):
            table = self.tables[path.split("/")[-2]]
            if method == "POST":
                table["fields"].append(body)
                return {}
            return {"items": table["fields"]}
        if path.endswith("/records/search"):
            uid = body["filter"]["conditions"][0]["value"][0]
            key = (path.rsplit("/", 1)[0], uid)
            return {"items": [self.records[key]] if key in self.records else []}
        if path.endswith("/records"):
            self.assert_token(params)
            self.creates += 1
            record = {"record_id": "rec" + str(self.creates)}
            self.records[(path, body["fields"]["UID"])] = record
            if self.fail_after_record:
                self.fail_after_record = False
                raise FeishuError("simulated lost acknowledgement")
            return {"record": record}
        raise AssertionError(path)

    def assert_token(self, params):
        self.tokens.append(params["client_token"])


class AdapterTest(unittest.TestCase):
    def setUp(self):
        self.stub = BaseStub()
        with patch.dict(os.environ, {"FEISHU_APP_ID": "demo", "FEISHU_APP_SECRET": "secret",
                                     "FEISHU_APP_TOKEN": "base-test"}):
            self.client = Feishu()
        self.client._api = self.stub.request

    def test_prepare_resumes_and_checks_reference_fields(self):
        self.stub.fail_after_table = "Expression Patterns"
        with self.assertRaises(FeishuError):
            self.client.prepare()
        self.client.prepare()
        self.client.prepare()
        self.assertEqual(len(self.stub.tables), 3)
        fields = self.stub.tables[self.client.tables["Copy Components"]]["fields"]
        by_name = {item["field_name"]: item for item in fields}
        self.assertEqual(by_name["Patterns"]["property"]["table_id"], self.client.tables["Expression Patterns"])
        self.assertTrue(by_name["Patterns"]["property"]["multiple"])
        self.assertEqual(by_name["Script"]["property"]["table_id"], self.client.tables["Scripts"])
        self.assertEqual(by_name["Order"]["type"], 2)
        fields.remove(by_name["Chunks"])
        self.client.prepare()
        self.assertIn({"field_name": "Chunks", "type": 1}, fields)
        by_name["Patterns"]["property"]["table_id"] = "wrong"
        with self.assertRaisesRegex(FeishuError, "须关联"):
            self.client.prepare()

    def test_resume_and_reuse_existing_record(self):
        self.client.prepare()
        self.stub.fail_after_record = True
        fields = {"UID": "pattern-key", "Template": "I use A for B"}
        token = str(uuid4())
        with self.assertRaises(FeishuError):
            self.client.ensure("Expression Patterns", fields, token)
        for key in (token, str(uuid4())):
            self.assertEqual(self.client.ensure("Expression Patterns", fields, key), "rec1")
        self.assertEqual(self.stub.tokens, [token])
        self.assertEqual(self.stub.creates, 1)

    def test_paginated_listing(self):
        self.client._api = lambda method, path, params: (
            {"items": [2]} if "page_token" in params else
            {"items": [1], "has_more": True, "page_token": "second"}
        )
        self.assertEqual(list(self.client._list("/tables")), [1, 2])

    def test_errors_do_not_expose_response_or_tokens(self):
        error = HTTPError("https://site/secret", 403, "secret", None,
                          io.BytesIO(json.dumps({"code": 123, "msg": "secret"}).encode()))
        with patch("feishu.urlopen", side_effect=error):
            with self.assertRaisesRegex(FeishuError, "403.*123") as caught:
                _exchange("/secret", "GET", token="secret")
        self.assertNotIn("secret", str(caught.exception))

    def test_missing_config(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(FeishuError, "FEISHU_APP_ID"):
            Feishu()


if __name__ == "__main__":
    unittest.main()
