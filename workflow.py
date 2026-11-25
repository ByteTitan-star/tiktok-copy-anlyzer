"""Durable review snapshots, deterministic asset keys, and resumable deliveries."""
import hashlib
import json
import os
import re
import sqlite3
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from engine import Input, Report, analyze, validate_source
from feishu import Feishu

ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()
TABLES = ("Scripts", "Expression Patterns", "Copy Components")


class Conflict(ValueError):
    pass


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def config():
    result = {k: os.getenv(v, "mock").lower() for k, v in
              [("analysis", "ANALYSIS_MODE"), ("storage", "STORAGE_MODE")]}
    if any(mode not in {"mock", "live"} for mode in result.values()):
        raise ValueError("ANALYSIS_MODE 和 STORAGE_MODE 只能是 mock 或 live")
    return result


def destination():
    if config()["storage"] == "mock":
        return "local-mock"
    base = os.getenv("FEISHU_APP_TOKEN", "").strip()
    if not base:
        raise ValueError("请配置 FEISHU_APP_TOKEN")
    return digest(["feishu", base])


@contextmanager
def db():
    folder = Path(os.getenv("DATA_DIR", ROOT / "data"))
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / "workspace.sqlite3", timeout=30)
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()


def init():
    with db() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, original TEXT NOT NULL,
          analysis TEXT, storage TEXT, destination TEXT, report TEXT, decisions TEXT,
          revision INTEGER, state TEXT, error TEXT DEFAULT '', created TEXT);
        CREATE TABLE IF NOT EXISTS events (
          seq INTEGER PRIMARY KEY, job TEXT, time TEXT, event TEXT, detail TEXT);
        CREATE TABLE IF NOT EXISTS deliveries (
          destination TEXT, kind TEXT, uid TEXT, token TEXT, record_id TEXT,
          PRIMARY KEY(destination,kind,uid));
        CREATE TABLE IF NOT EXISTS receipts (
          job TEXT, kind TEXT, uid TEXT, record_id TEXT, PRIMARY KEY(job,kind,uid));
        CREATE TABLE IF NOT EXISTS mock_records (
          kind TEXT, uid TEXT, record_id TEXT, fields TEXT, PRIMARY KEY(kind,uid));
        """)
        for entry in con.execute("SELECT id FROM jobs WHERE state='writing'").fetchall():
            message = "上次写入未完成，可在清单中重试。"
            con.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", (message, entry[0]))
            log(con, entry[0], "恢复写入进度", message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(con, job, event, detail=""):
    con.execute("INSERT INTO events(job,time,event,detail) VALUES(?,?,?,?)",
                (job, now(), event, detail))


def row(con, job):
    item = con.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
    if item is None:
        raise KeyError("未找到分析记录")
    return item


def approved_rows(report, decisions):
    return [(i, s) for i, s in enumerate(report["sentences"], 1) if decisions[i-1] == "approved"]


def normalize(value):
    value = unicodedata.normalize("NFKC", value).casefold().replace("’", "'")
    return re.sub(r"\s+", " ", value).strip().rstrip(".!?").strip()


def build_plan(r):
    source = json.loads(r["original"])
    report = json.loads(r["report"])
    approved = approved_rows(report, json.loads(r["decisions"]))
    if not approved:
        return []
    # Script identity is shared by retries of the same reviewed analysis.
    sid = "S-" + r["id"]
    items = []
    def add(table, key, title, fields):
        items.append(dict(table=table, key=key, title=title,
                          fields={"UID": key, "Status": "已通过", **fields}))

    add(TABLES[0], sid, source["product"] or source["text"][:60], {
        "Original": source["text"], "Product": source["product"], "Category": source["category"],
        "Benefits": source["benefits"], "Video": source["video"], "Overview": dump(report["overview"]),
        "Logic": dump([{"order": i, "logic": s["logic"], "stages": s["stages"]} for i,s in approved])})
    links = {i: [] for i, _ in approved}
    seen = set()
    for asset in report["assets"]:
        if not set(asset["sources"]).issubset(links):
            continue
        context = ""
        if asset["scope"] == "产品专属":
            context = normalize(source["product"] or sid)
        key = "P-" + digest([asset["level"], asset["scope"], context, normalize(asset["template"])])
        if key not in seen:
            add(TABLES[1], key, asset["template"], {"Level": asset["level"], "Template": asset["template"],
                "Scope": asset["scope"], "Scene": asset["scene"], "Limits": asset["limits"],
                "Tags": "、".join(asset["tags"])})
            seen.add(key)
        for i in asset["sources"]:
            if key not in links[i]:
                links[i].append(key)
    for i, s in approved:
        add(TABLES[2], f"C-{r['id']}-{i}", s["original"], {"Script": [sid], "Patterns": links[i],
            "Order": i, "Original": s["original"], "Meaning": s["meaning"], "Role": s["role"],
            "Tags": "、".join(s["tags"]), "Syntax": s["syntax"], "Chunks": dump(s["chunks"]),
            "Analysis": dump(s)})
    return items


def get(job):
    with db() as con:
        r = row(con, job)
        return dict(id=job, input=json.loads(r["original"]), report=json.loads(r["report"]),
            decisions=json.loads(r["decisions"]), revision=r["revision"], state=r["state"],
            error=r["error"], analysis=r["analysis"], storage=r["storage"],
            plan=[{k:v for k,v in x.items() if k != "fields"} for x in build_plan(r)],
            receipts=[dict(table=x[0], key=x[1], record_id=x[2]) for x in con.execute(
                "SELECT kind,uid,record_id FROM receipts WHERE job=? ORDER BY rowid", (job,))],
            logs=[dict(x) for x in con.execute(
                "SELECT time,event,detail FROM events WHERE job=? ORDER BY seq",(job,))])


def history():
    with db() as con:
        rows = con.execute("SELECT id,original,state FROM jobs ORDER BY rowid DESC")
        return [dict(id=x["id"], title=json.loads(x["original"])["product"] or
                     json.loads(x["original"])["text"][:64], state=x["state"]) for x in rows]


def create(source: Input):
    modes = config()
    target = destination()
    fingerprint = digest([source.model_dump(mode="json"), modes, target])
    with db() as con:
        existing = con.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()
    if existing:
        return get(existing[0])
    job = uuid.uuid4().hex
    with db() as con:
        log(con, job, "开始分析", modes["analysis"])
    try:
        report = analyze(source, modes["analysis"])
        validate_source(report, source)
    except Exception:
        with db() as con:
            log(con, job, "分析失败", "未生成审核草稿")
        raise
    with db() as con:
        saved = con.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (job, fingerprint, dump(source.model_dump(mode="json")), modes["analysis"], modes["storage"],
             target, dump(report.model_dump()), dump(["pending"]*len(report.sentences)), 1, "review", "", now()))
        if saved.rowcount:
            log(con, job, "分析完成", f"{len(report.sentences)} 个组件，等待审核")
        else:
            job = con.execute("SELECT id FROM jobs WHERE fingerprint=?", (fingerprint,)).fetchone()[0]
    return get(job)


def review(job, revision, report: Report, decisions):
    with LOCK, db() as con:
        con.execute("BEGIN IMMEDIATE")
        r = row(con, job)
        if r["state"] != "review" or revision != r["revision"]:
            raise Conflict("审核版本已变化或已经确认，请重新打开记录")
        validate_source(report, Input.model_validate_json(r["original"]))
        if [s.original for s in report.sentences] != [s["original"] for s in json.loads(r["report"])["sentences"]]:
            raise ValueError("审核不得修改英文原句或顺序")
        if len(decisions) != len(report.sentences):
            raise ValueError("审核数量与句子数量不同")
        con.execute("UPDATE jobs SET report=?,decisions=?,revision=revision+1 WHERE id=?",
                    (dump(report.model_dump()), dump(decisions), job))
        log(con, job, "保存审核", f"版本 {revision+1}；通过 {decisions.count('approved')}，驳回 {decisions.count('rejected')}")
    return get(job)


class Mock:
    def prepare(self):
        pass

    def ensure(self, table, fields, token):
        with db() as con:
            con.execute("INSERT OR IGNORE INTO mock_records VALUES(?,?,?,?)",
                        (table, fields["UID"], "mock_"+token, dump(fields)))
            return con.execute("SELECT record_id FROM mock_records WHERE kind=? AND uid=?",
                               (table, fields["UID"])).fetchone()[0]


def deliver(job, target, item, remote, ids):
    table, key = item["table"], item["key"]
    identity = (target, table, key)
    with db() as con:
        con.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,NULL)", (*identity, str(uuid.uuid4())))
        token, rid = con.execute("SELECT token,record_id FROM deliveries WHERE destination=? AND kind=? AND uid=?",
                                 identity).fetchone()
    if not rid:
        fields = dict(item["fields"])
        for field in ("Script", "Patterns"):
            if field in fields:
                fields[field] = [ids[uid] for uid in fields[field]]
        rid = remote.ensure(table, fields, token)
        if not isinstance(rid, str) or not rid.strip():
            raise RuntimeError("服务未返回有效的 Record ID")
    with db() as con:
        con.execute("UPDATE deliveries SET record_id=? WHERE destination=? AND kind=? AND uid=?", (rid,*identity))
        added = con.execute("INSERT OR IGNORE INTO receipts VALUES(?,?,?,?)", (job,table,key,rid))
        if added.rowcount:
            log(con, job, "记录已关联", f"{table} · {rid}")
    ids[key] = rid


def confirm(job, revision):
    with LOCK:
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            r = row(con, job)
            decisions = json.loads(r["decisions"])
            if revision != r["revision"]:
                raise Conflict("清单版本已更新，请重新查看")
            if r["state"] == "done":
                return get(job)
            if "pending" in decisions or "approved" not in decisions:
                raise Conflict("请处理全部组件，并至少通过一个组件")
            if r["destination"] != destination() or r["storage"] != config()["storage"]:
                raise Conflict("当前写入目标与草稿不同，请恢复原配置或新建分析")
            con.execute("UPDATE jobs SET state='writing',error='' WHERE id=?", (job,))
            log(con, job, "人工确认写入", f"版本 {revision} · {r['storage']}")
        try:
            remote = Feishu() if r["storage"] == "live" else Mock()
            remote.prepare()
            ids = {}
            for item in build_plan(r):
                deliver(job, r["destination"], item, remote, ids)
        except Exception as exc:
            with db() as con:
                con.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", (str(exc)[:500],job))
                log(con, job, "写入中断", str(exc)[:500])
        else:
            with db() as con:
                con.execute("UPDATE jobs SET state='done' WHERE id=?", (job,))
                log(con, job, "写入完成", f"{len(ids)} 条记录已关联")
    return get(job)

