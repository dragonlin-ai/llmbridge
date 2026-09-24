#!/usr/bin/env python3
"""装完到底能不能用？—— 对一条命令装出来的栈做**功能性**核验（不是只看 `docker ps`）。

为什么需要它：容器全 `healthy` 只说明进程活着，不代表控制台能打开、能登录、能读库。
只跑 `docker ps` 会把「装上了但用不了」当成成功。

用法::

    python scripts/verify_deploy.py                      # 默认 http://127.0.0.1:80
    python scripts/verify_deploy.py --port 8099          # 换端口
    python scripts/verify_deploy.py --base http://10.0.0.5

退出码：全通过 0，有失败项 1。

自带 `ProxyHandler({})` 绕开系统代理 —— 本机 HTTP 代理会拦 127.0.0.1，
不绕会把代理错误（502）误判成服务故障。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
BASE = "http://127.0.0.1:80"
FAILS: list[str] = []


def call(path: str, method: str = "GET", body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with OPENER.open(req, timeout=15) as resp:
            raw = resp.read()
            if "json" in resp.headers.get("Content-Type", ""):
                return resp.status, json.loads(raw)
            return resp.status, raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:  # noqa: BLE001 — 连不上就是最需要看清的失败
        return 0, f"{type(exc).__name__}: {exc}"


def check(label: str, cond: bool, detail: str) -> None:
    print(("  [OK]   " if cond else "  [失败] ") + f"{label}: {detail}")
    if not cond:
        FAILS.append(label)


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description="核验已部署的 llmbridge 是否真的可用")
    ap.add_argument("--base", help="形如 http://127.0.0.1:8099")
    ap.add_argument("--port", type=int, help="只给端口，等价于 --base http://127.0.0.1:<port>")
    ap.add_argument("--user", default="admin", help="默认管理员账号")
    ap.add_argument("--password", default="admin123", help="默认管理员密码")
    args = ap.parse_args()
    if args.base:
        BASE = args.base.rstrip("/")
    elif args.port:
        BASE = f"http://127.0.0.1:{args.port}"
    print(f"目标：{BASE}\n")

    print("1) 控制台入口（根路径，经 nginx 反代）")
    st, html = call("/")
    check("GET /", st == 200 and isinstance(html, str) and '<div id="app">' in html,
          f"HTTP {st}，含 SPA 挂载点="
          f"{'<div id=\"app\">' in html if isinstance(html, str) else False}")

    print("2) 健康检查（nginx → api 全链路）")
    st, body = call("/health")
    check("GET /health", st == 200 and body == {"status": "ok"}, f"HTTP {st} {body}")

    print("3) 确认 /admin 是接口前缀而不是控制台页面")
    st, body = call("/admin/")
    check("GET /admin/ 应为 API 404（证明控制台不在该路径）", st == 404, f"HTTP {st} {body}")

    print("4) 真实登录（证明库可读写）")
    st, body = call("/admin/auth/login", "POST",
                    {"username": args.user, "password": args.password})
    # 刻意**不打印响应体** —— 里面是真实 JWT，落到日志/文件里等于把凭据写进交付物。
    data = body.get("data", {}) if isinstance(body, dict) else {}
    token = data.get("token") or data.get("access_token") or ""
    check("POST /admin/auth/login", st == 200 and bool(token),
          f"HTTP {st}，code={body.get('code') if isinstance(body, dict) else '?'}，"
          f"token 长度={len(token)}")

    if token:
        print("5) 首次运行引导真的铺了接入商目录")
        st, body = call("/admin/providers?page_size=200", token=token)
        items = (body or {}).get("data", {}).get("items", []) if isinstance(body, dict) else []
        vendors = {i.get("vendor") for i in items}
        check("GET /admin/providers（>0 即引导生效）", st == 200 and len(items) > 0,
              f"HTTP {st}，通道 {len(items)} 条 / 厂商 {len(vendors)} 家")

        print("6) 模型池按设计留空")
        st, body = call("/admin/models?page_size=200", token=token)
        total = (body or {}).get("data", {}).get("total") if isinstance(body, dict) else None
        check("GET /admin/models", st == 200 and total == 0, f"HTTP {st}，total={total}")

        print("7) 概览页不 500（0 模型 0 请求）")
        st, body = call("/admin/stats/overview", token=token)
        check("GET /admin/stats/overview", st == 200 and (body or {}).get("code") == 0,
              f"HTTP {st}，code={(body or {}).get('code')}")

    print()
    print("RESULT:", "ALL_OK" if not FAILS else f"失败项 {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
