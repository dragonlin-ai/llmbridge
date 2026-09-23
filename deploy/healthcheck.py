"""容器健康检查：探 `/health`，只依赖标准库（镜像里不装 curl）。

不用 `urllib.request.urlopen` 直连的原因：宿主/容器若设了 HTTP_PROXY，
本地探活会被代理拦掉并返回 502，把「服务正常」误判成不健康。
显式用空 ProxyHandler 绕开。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

PORT = os.environ.get("PORT", "8000")
URL = f"http://127.0.0.1:{PORT}/health"


def main() -> int:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if resp.status == 200 and body.get("status") == "ok":
            return 0
        print(f"unhealthy: status={resp.status} body={body}", file=sys.stderr)
        return 1
    except Exception as exc:  # 探活失败只报原因，不抛栈
        print(f"unhealthy: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
