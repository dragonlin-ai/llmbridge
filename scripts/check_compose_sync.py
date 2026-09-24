#!/usr/bin/env python3
"""比对 `deploy/docker-deploy.sh` **内嵌的编排副本** 与 `deploy/docker-compose.image.yml` 是否一致。

为什么需要它：`docker-deploy.sh` 把编排文件内嵌了一份（heredoc），好让「手上只有那一个脚本文件」
的目标机也能离线安装。于是同一份内容存在**两份**，改其一忘改其二就会让两条安装路径产生不同行为 ——
而这种偏差不会有任何报错，只会在某天以「按文档做和按脚本做结果不一样」的形式冒出来。

运行时机：发布前自查，或挂进 CI。`docker-deploy.sh` 在仓库内以 `--image` 运行时也会做同样的比对
并告警，但那需要真的跑一次部署；本脚本可以独立跑、不碰 Docker。

退出码：一致 0，不一致 1（并打印差异）。
"""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "docker-deploy.sh"
COMPOSE = ROOT / "deploy" / "docker-compose.image.yml"
MARK = "<<'LLMBRIDGE_COMPOSE_EOF'\n"
END = "\nLLMBRIDGE_COMPOSE_EOF"


def main() -> int:
    script_text = SCRIPT.read_text(encoding="utf-8")
    compose_text = COMPOSE.read_text(encoding="utf-8")

    if MARK not in script_text:
        print(f"[失败] {SCRIPT.name} 里找不到内嵌起点 {MARK.strip()!r}")
        return 1

    start = script_text.index(MARK) + len(MARK)
    try:
        end = script_text.index(END, start)
    except ValueError:
        print(f"[失败] {SCRIPT.name} 里找不到内嵌终点 {END.strip()!r}")
        return 1

    embedded = script_text[start:end] + "\n"
    print(f"内嵌副本行数: {embedded.count(chr(10))}")
    print(f"真源行数    : {compose_text.count(chr(10))}")

    if embedded == compose_text:
        print("RESULT: IDENTICAL")
        return 0

    print("RESULT: DIFFERENT —— 请同步两份内容")
    for line in list(difflib.unified_diff(
            compose_text.splitlines(), embedded.splitlines(),
            str(COMPOSE.relative_to(ROOT)), "内嵌副本", lineterm=""))[:80]:
        print(line)
    return 1


if __name__ == "__main__":
    sys.exit(main())
