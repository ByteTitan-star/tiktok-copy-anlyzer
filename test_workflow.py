"""HTTP end-to-end tests with isolated SQLite storage and fault injection."""
import json
import os
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from http.server import ThreadingHTTPServer

import app
import workflow as flow


class EndToEnd(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, DATA_DIR=folder.name, ANALYSIS_MODE="mock", STORAGE_MODE="mock")
        env.start()
        self.addCleanup(env.stop)
        flow.init()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.source = {"text": "  Tired of losing your keys?  I keep mine right here. Try it today!\n",
                       "product":"Key tray"}
        self.job = self.api("POST","/api/jobs",self.source)
        self.path = "/api/jobs/"+self.job["id"]

    def api(self, method, path, body=None):
        req = Request(self.base+path, method=method, headers={"Content-Type":"application/json"},
                      data=json.dumps(body).encode() if body is not None else None)
        with urlopen(req) as response:
            return json.load(response)

    def save(self, decisions):
        return self.api("PUT",self.path,dict(revision=1,report=self.job["report"],decisions=decisions))

    def confirm(self, rev):
        return self.api("POST",self.path+"/confirm",{"confirmed":True,"revision":rev})

    def test_review_delivery_recovery(self):
        j = self.job
        self.assertEqual(j["input"]["text"], self.source["text"])
        self.assertEqual(self.api("POST","/api/jobs",self.source)["id"], j["id"])
        self.assertEqual(j["receipts"], [])
        with self.assertRaises(HTTPError) as denied:
            self.confirm(1)
        self.assertEqual(denied.exception.code,409)
        decisions = ["approved"]*len(j["decisions"])
        decisions[-1] = "rejected"
        j["report"]["sentences"][0]["meaning"] = "总是找不到钥匙？"
        saved = self.save(decisions)
        with self.assertRaises(HTTPError):
            self.confirm(1)
        original_ensure = flow.Mock.ensure
        def interrupted(remote, table, fields, token):
            rid = original_ensure(remote,table,fields,token)
            if table == "Copy Components":
                raise RuntimeError("模拟远端成功后响应中断")
            return rid
        with patch.object(flow.Mock,"ensure",interrupted):
            failed = self.confirm(saved["revision"])
        self.assertEqual(failed["state"],"failed")
        self.assertGreater(len(failed["receipts"]),0)
        final = self.confirm(saved["revision"])
        self.assertEqual(final["state"],"done")
        self.assertEqual(len(final["plan"]),len(final["receipts"]))
        self.assertEqual(self.confirm(saved["revision"])["receipts"],final["receipts"])
        with flow.db() as con:
            records = [(r[0],json.loads(r[1])) for r in con.execute("SELECT kind,fields FROM mock_records")]
        self.assertEqual(len(records),len(final["receipts"]))
        component = [f for t,f in records if t=="Copy Components"]
        self.assertEqual(len(component),len(decisions)-1)
        self.assertEqual(component[0]["Meaning"],"总是找不到钥匙？")
        self.assertEqual(component[0]["Script"],[final["receipts"][0]["record_id"]])
        self.assertTrue(all(r.startswith("mock_") for r in component[0]["Patterns"]))
        self.assertEqual(dict(records)["Scripts"]["Original"], self.source["text"])
        with self.assertRaises(HTTPError):
            self.save(decisions)

    def test_reject_changed_original_and_unconfirmed(self):
        j = self.job
        j["report"]["sentences"][0]["original"] += " Altered."
        with self.assertRaises(HTTPError):
            self.save(j["decisions"])
        with self.assertRaises(HTTPError):
            self.api("POST",self.path+"/confirm",{"revision":1,"confirmed":False})
        with flow.db() as con:
            self.assertEqual(con.execute("SELECT count(*) FROM deliveries").fetchone()[0],0)

    def test_restart_during_confirmed_delivery(self):
        saved = self.save(["approved"]*len(self.job["decisions"]))
        with patch.object(flow.Mock, "ensure", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                flow.confirm(self.job["id"], saved["revision"])
        flow.init()
        self.assertEqual(self.api("GET", self.path)["state"], "failed")
        resumed = self.confirm(saved["revision"])
        self.assertEqual(resumed["state"], "done")
        self.assertEqual(len(resumed["plan"]), len(resumed["receipts"]))

    def test_shared_pattern_reused(self):
        def publish(text):
            job = self.api("POST","/api/jobs",{"text":text})
            asset = job["report"]["assets"][0]
            asset.update(level="L1", template="right here", scope="通用", sources=[1])
            job["report"]["assets"] = [asset]
            path = "/api/jobs/"+job["id"]
            save = self.api("PUT",path,dict(revision=1, report=job["report"],
                                           decisions=["approved"]*len(job["decisions"])))
            final = self.api("POST",path+"/confirm",{"revision":save["revision"],"confirmed":True})
            return next(r["record_id"] for r in final["receipts"] if r["table"]=="Expression Patterns")
        self.assertEqual(publish("I keep my keys right here."),publish("My bag is right here."))


if __name__ == "__main__":
    unittest.main()

