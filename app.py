"""Single-user loopback HTTP application. Run with python app.py."""
import argparse
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError
import workflow as flow
from engine import Input, Report

ROOT = Path(__file__).resolve().parent


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text("utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    report: Report
    decisions: list[Literal["pending","approved","rejected"]]


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    confirmed: StrictBool


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, mime="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        host = self.headers.get("Host", "")
        port = self.server.server_port
        if host not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            return self.send(403, {"error":"仅支持本机访问"})
        path = urlsplit(self.path).path
        if self.command == "GET":
            if path in ("/", "/static/app.js", "/static/style.css"):
                f = ROOT / "static" / (path.rsplit("/", 1)[-1] or "index.html")
                return self.send(200, f.read_bytes(), mimetypes.guess_type(f)[0]+"; charset=utf-8")
            if path == "/api/config":
                return self.send(200, flow.config())
            if path == "/api/schema":
                return self.send(200, Report.model_json_schema())
            if path == "/api/jobs":
                return self.send(200, flow.history())
            if path.startswith("/api/jobs/"):
                return self.send(200, flow.get(path.split("/")[-1]))
        else:
            origin = self.headers.get("Origin")
            if origin and origin != "http://"+host:
                return self.send(403, {"error":"请求来源不匹配"})
            if self.headers.get_content_type() != "application/json":
                return self.send(415, {"error":"需要 JSON 请求"})
            length = int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 4_000_000:
                return self.send(413, {"error":"请求大小超出限制"})
            data = json.loads(self.rfile.read(length))
            parts = path.strip("/").split("/")
            if self.command == "POST" and path == "/api/jobs":
                return self.send(200, flow.create(Input.model_validate(data)))
            if parts[:2] == ["api", "jobs"] and len(parts) >= 3:
                if self.command == "PUT" and len(parts) == 3:
                    req = Review.model_validate(data)
                    return self.send(200, flow.review(parts[2], req.revision, req.report, req.decisions))
                if self.command == "POST" and parts[3:] == ["confirm"]:
                    req = Confirmation.model_validate(data)
                    if not req.confirmed:
                        raise ValueError("需要人工确认")
                    return self.send(200, flow.confirm(parts[2], req.revision))
        self.send(404, {"error":"路径不存在"})

    def dispatch(self):
        try:
            self.route()
        except ValidationError as exc:
            first = exc.errors(include_input=False)[0]
            self.send(422, {"error": ".".join(map(str, first["loc"]))+" · "+first["msg"]})
        except flow.Conflict as exc:
            self.send(409, {"error": str(exc)})
        except ValueError as exc:
            self.send(400, {"error": str(exc)[:500]})
        except KeyError:
            self.send(404, {"error": "记录不存在"})
        except RuntimeError as exc:
            self.send(502, {"error": str(exc)[:500]})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.send(500, {"error":"处理失败，请检查运行环境后重试"})
    do_GET = do_POST = do_PUT = dispatch


if __name__ == "__main__":
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    flow.init()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"TikTok Copy Analyzer   http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

