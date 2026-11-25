"""Feishu Base adapter. Call prepare/ensure only after a confirmed review."""

import json
import os
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from uuid import UUID


TABLE_FIELDS = {
    "Scripts": "UID Original Product Category Benefits Video Overview Logic Status".split(),
    "Expression Patterns": "UID Level Template Scope Scene Limits Tags Status".split(),
    "Copy Components": "UID Script Patterns Order Original Meaning Role Tags Syntax Chunks Analysis Status".split(),
}
LINK_TARGETS = {"Script": "Scripts", "Patterns": "Expression Patterns"}
BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuError(RuntimeError):
    pass


def _required(data, key):
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        raise FeishuError(f"飞书响应缺少 {key}，请重试并检查开放平台日志。")
    return value


def _exchange(path, method, body=None, token=None, params=None):
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Raw error messages and URLs may contain submitted data or tokens.
        status = exc.code
        with exc:
            try:
                code = json.load(exc).get("code")
            except (ValueError, AttributeError, OSError, HTTPException):
                code = None
        suffix = f"，业务码 {code}" if type(code) is int else ""
        raise FeishuError(f"飞书请求失败（HTTP {status}{suffix}），请检查权限或稍后重试。") from None
    except (URLError, OSError, HTTPException, ValueError):
        raise FeishuError("飞书连接中断或响应无效。请检查网络，重试时将核对已写入记录。") from None
    if not isinstance(result, dict) or type(result.get("code")) is not int:
        raise FeishuError("飞书响应格式异常，请核对开放平台日志后重试。")
    if result["code"] != 0:
        raise FeishuError(f"飞书业务错误 {result['code']}，请在开放平台服务端日志中核对权限和字段。")
    return result


class Feishu:
    def __init__(self):
        options = {}
        for name in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_APP_TOKEN"):
            options[name] = os.environ.get(name, "").strip()
            if not options[name]:
                raise FeishuError("请在 .env 中填写 " + name)
        self._auth = {"app_id": options["FEISHU_APP_ID"], "app_secret": options["FEISHU_APP_SECRET"]}
        self._tables_path = "/bitable/v1/apps/" + quote(options["FEISHU_APP_TOKEN"], safe="") + "/tables"
        self._token = ""
        self._expires = 0
        self.tables = {}

    def _api(self, method, path, body=None, params=None):
        if time.monotonic() >= self._expires:
            auth = _exchange("/auth/v3/tenant_access_token/internal", "POST", self._auth)
            self._token = _required(auth, "tenant_access_token")
            self._expires = time.monotonic() + max(1, int(auth.get("expire", 7200)) - 60)
        return _exchange(path, method, body, self._token, params).get("data", {})

    def _list(self, path):
        params = {"page_size": 100}
        seen = set()
        while True:
            page = self._api("GET", path, params=params)
            items = page.get("items")
            if not isinstance(items, list):
                raise FeishuError("无法读取飞书表或字段清单，请检查应用文档权限。")
            yield from items
            if not page.get("has_more"):
                return
            token = _required(page, "page_token")
            if token in seen:
                raise FeishuError("飞书分页标记重复，请稍后重试。")
            seen.add(token)
            params["page_token"] = token

    def _fields(self, name):
        result = []
        for field in TABLE_FIELDS[name]:
            spec = {"field_name": field, "type": 2 if field == "Order" else 1}
            if field in LINK_TARGETS:
                spec.update(type=21, property={
                    "table_id": self.tables[LINK_TARGETS[field]], "multiple": True,
                    "back_field_name": "Source Components" if field == "Patterns" else "Components",
                })
            result.append(spec)
        return result

    def prepare(self):
        """Reconcile named tables and fields in dependency order; never alter existing data."""
        self.tables = {row["name"]: _required(row, "table_id") for row in self._list(self._tables_path)}
        for name in TABLE_FIELDS:
            specs = self._fields(name)
            if name not in self.tables:
                data = self._api("POST", self._tables_path, {"table": {
                    "name": name, "default_view_name": "全部记录", "fields": specs,
                }})
                self.tables[name] = _required(data, "table_id")
                continue
            path = f"{self._tables_path}/{self.tables[name]}/fields"
            existing = {row["field_name"]: row for row in self._list(path)}
            for spec in specs:
                field = spec["field_name"]
                if field not in existing:
                    self._api("POST", path, spec)
                    continue
                row = existing[field]
                if row.get("type") != spec["type"]:
                    raise FeishuError(f"{name} 的 {field} 字段类型不兼容，请核对现有表结构。")
                if field in LINK_TARGETS:
                    prop = row.get("property") or {}
                    if prop.get("table_id") != spec["property"]["table_id"]:
                        raise FeishuError(f"{name} 的 {field} 须关联到 {LINK_TARGETS[field]}。")
                    if field == "Patterns" and not prop.get("multiple"):
                        raise FeishuError("Patterns 字段须开启多条关联记录。")

    def ensure(self, table, fields, client_token):
        """Return Feishu's actual record ID for either a matching UID or a new record."""
        if table not in TABLE_FIELDS or table not in self.tables:
            raise FeishuError("请先完成飞书表结构初始化。")
        uid = _required(fields, "UID")
        try:
            if UUID(str(client_token)).version != 4:
                raise ValueError
        except (TypeError, ValueError):
            raise FeishuError("写入操作缺少有效的 UUIDv4 幂等标识。") from None
        path = f"{self._tables_path}/{self.tables[table]}/records"
        data = self._api("POST", path + "/search", {
            "field_names": ["UID"],
            "filter": {"conjunction": "and", "conditions": [
                {"field_name": "UID", "operator": "is", "value": [uid]},
            ]},
        }, {"page_size": 2})
        items = data.get("items")
        if not isinstance(items, list):
            # Search can omit items for an explicitly empty page.
            if data.get("total") == 0:
                items = []
            else:
                raise FeishuError("飞书查询结果缺少记录清单，请重试。")
        if len(items) > 1 or data.get("has_more"):
            raise FeishuError(f"{table} 存在重复 UID，请核对后重试。")
        if items:
            return _required(items[0], "record_id")
        created = self._api("POST", path, {"fields": fields}, {"client_token": str(client_token)})
        return _required(created.get("record"), "record_id")
