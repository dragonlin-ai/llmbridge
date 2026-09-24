#!/usr/bin/env python3
"""独立核验容器库里的镜像标签 —— 不采信 `docker push` 的退出码。

`docker buildx ... --push` 退出码 0 只代表客户端认为推成功了；要确认远端真有这个 tag，
得自己问一次 registry。走标准 Bearer 挑战流程：

    GET /v2/<ns>/<repo>/tags/list
      → 401 + WWW-Authenticate: Bearer realm=..., service=..., scope=...
      → 拿 realm 换（匿名或带凭据的）令牌 → 带 Bearer 再查一次

用法::

    python scripts/verify_registry.py                                   # 默认 ACR + 三个仓库
    python scripts/verify_registry.py --tag 1.0.0                       # 顺带校验标签存在
    python scripts/verify_registry.py --user <账号> --password <密码>    # 私有仓库

退出码：全部仓库可查且（若指定 --tag）标签存在 → 0，否则 1。

注意：**不要把令牌打到日志里**。本脚本只回显标签列表与布尔结论。
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request

DEFAULT_REGISTRY = "registry.cn-hangzhou.aliyuncs.com"
DEFAULT_NS = "winyeahs"
# 默认只查这两个：一条命令安装**必然**匿名拉这两个，所以它们必须是公开的。
# llmbridge-deploy（纯安装器）默认私有 —— 它 401 是预期内的，不该算失败；
# 想连它一起查就显式 `--repos llmbridge-api,llmbridge-web,llmbridge-deploy`。
DEFAULT_REPOS = "llmbridge-api,llmbridge-web"

# 绕开系统代理：registry 在国内直连即可，走代理反而可能被拦。
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _lower_headers(hdrs) -> dict[str, str]:
    # urllib 的 headers 是大小写不敏感的 Message，但 dict() 之后就不是了。
    # 曾因写成 dict(resp.headers) 而拿不到 `www-authenticate`，误判成「仓库不可匿名访问」。
    return {k.lower(): v for k, v in hdrs.items()}


def http_get(url: str, headers: dict[str, str] | None = None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with OPENER.open(req, timeout=20) as resp:
            return resp.status, _lower_headers(resp.headers), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, _lower_headers(exc.headers), exc.read().decode("utf-8", "replace")


def bearer_token(registry: str, namespace: str, repo: str, basic: str | None) -> str:
    """返回 'Bearer <token>' 用的令牌；返回空串表示该仓库匿名可读。"""
    status, headers, _ = http_get(f"https://{registry}/v2/{namespace}/{repo}/tags/list")
    if status == 200:
        return ""
    challenge = headers.get("www-authenticate", "")
    realm_m = re.search(r'realm="([^"]+)"', challenge)
    if not realm_m:
        raise RuntimeError(f"未拿到 WWW-Authenticate 挑战：{challenge!r}（status={status}）")
    svc = re.search(r'service="([^"]+)"', challenge)
    scope = re.search(r'scope="([^"]+)"', challenge)
    url = f"{realm_m.group(1)}?service={svc.group(1) if svc else ''}"
    url += f"&scope={scope.group(1) if scope else f'repository:{namespace}/{repo}:pull'}"
    hdrs = {"Authorization": f"Basic {basic}"} if basic else {}
    status, _, body = http_get(url, hdrs)
    if status != 200:
        raise RuntimeError(f"取令牌失败 status={status}（私有仓库需 --user/--password）")
    return json.loads(body).get("token", "")


def main() -> int:
    ap = argparse.ArgumentParser(description="核验容器库里的镜像标签")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--namespace", default=DEFAULT_NS)
    ap.add_argument("--repos", default=DEFAULT_REPOS,
                    help="逗号分隔；默认只查必须公开的两个，加 llmbridge-deploy 会因私有而报 401")
    ap.add_argument("--tag", help="顺带断言该标签存在")
    ap.add_argument("--user")
    ap.add_argument("--password")
    args = ap.parse_args()

    basic = None
    if args.user and args.password:
        basic = base64.b64encode(f"{args.user}:{args.password}".encode()).decode()

    bad = 0
    for repo in [r.strip() for r in args.repos.split(",") if r.strip()]:
        try:
            token = bearer_token(args.registry, args.namespace, repo, basic)
        except RuntimeError as exc:
            print(f"[失败] {repo}: {exc}")
            bad += 1
            continue
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        status, _, body = http_get(
            f"https://{args.registry}/v2/{args.namespace}/{repo}/tags/list", headers)
        if status != 200:
            print(f"[失败] {repo}: tags/list status={status}（匿名不可读，私有库请带凭据）")
            bad += 1
            continue
        tags = sorted(json.loads(body).get("tags") or [])
        if args.tag:
            ok = args.tag in tags
            print(f"[{'OK' if ok else '失败'}] {repo}: tags={tags}，含 {args.tag}={ok}")
            if not ok:
                bad += 1
        else:
            print(f"[OK]   {repo}: {tags}")

    print("RESULT:", "ALL_OK" if bad == 0 else f"{bad} 项失败")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
