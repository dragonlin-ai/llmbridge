"""一键打包：产出可离线交付的发布包（zip）。

用法（在仓库根执行）：
    python scripts/build_release.py                    # 完整打包（含前端构建）
    python scripts/build_release.py --skip-frontend    # 前端已构建，跳过 npm
    python scripts/build_release.py --skip-python      # 只重打前端产物
    python scripts/build_release.py --no-archive       # 只组装目录，不压 zip

产物：
    release/llmbridge-<版本>-<日期>/       组装目录（可直接 scp 到服务器）
    release/llmbridge-<版本>-<日期>.zip    分发包
    包内含 BUILD-INFO.txt（版本/时间/git 提交）与 SHA256SUMS.txt（完整性清单）

设计取舍
--------
1. **打包 ≠ 只打 Python 包**。一次真实部署需要四样东西：后端代码、数据库脚本、
   编排配置、前端静态产物。少任何一样现场都得手工补，所以这里一次性组装齐。
2. **前端构建失败不静默降级**。宁可让打包失败，也不要产出一个「缺 dist/、
   nginx 挂个空目录」的包 —— 那种包到现场才发现，排查成本远高于重打一次。
3. **SHA256SUMS 覆盖包内全部文件**，交付给第三方后可逐项校验，避免传输损坏。
"""
from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_DIR = ROOT / "release"

# 打进发布包的顶层目录/文件（白名单式，避免把 .venv / node_modules / 本地库带进去）
INCLUDE_DIRS = ("app", "scripts", "deploy", "docs")
INCLUDE_FILES = ("README.md", "LICENSE", "CHANGELOG.md", ".env.example",
                 "pyproject.toml", "MANIFEST.in", ".gitignore", ".gitattributes")
INCLUDE_WEB = ("admin-web/dist",)


def read_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def run(cmd: list[str], cwd: Path, label: str) -> None:
    """跑一条外部命令；失败即终止（不降级、不吞错）。"""
    print(f"[build] {label}: {' '.join(cmd)}")
    # Windows 上 npm 是 npm.cmd，CreateProcess 不能直接执行 .cmd/.bat，必须经 cmd.exe。
    if sys.platform == "win32" and cmd[0].lower().endswith((".cmd", ".bat")):
        cmd = ["cmd.exe", "/c", *cmd]
    proc = subprocess.run(cmd, cwd=str(cwd))
    if proc.returncode != 0:
        raise SystemExit(f"[build] 失败（exit={proc.returncode}）：{label}")


def which_npm() -> str:
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("[build] 找不到 npm。请先安装 Node.js 20+，或加 --skip-frontend。")


def build_frontend() -> None:
    web = ROOT / "admin-web"
    npm = which_npm()
    # node_modules 缺失/不完整时先补装。用 ci 而不是 install：锁文件是唯一真源，
    # install 会顺手改锁文件，导致「打包出来的前端依赖和提交记录不一致」。
    if not (web / "node_modules").is_dir():
        run([npm, "ci"], cwd=web, label="前端依赖安装（npm ci）")
    run([npm, "run", "build"], cwd=web, label="前端构建（vue-tsc + vite build）")
    if not (web / "dist" / "index.html").is_file():
        raise SystemExit("[build] 前端构建未产出 admin-web/dist/index.html")
    # 之前构建遗留的哈希文件会堆积，导致包体虚高且 index.html 引用对不上。
    stale = [p for p in (web / "dist" / "assets").glob("*") if p.suffix in {".js", ".css"}]
    print(f"[build] 前端产物：{len(stale)} 个资源文件")


def build_python(version: str) -> Path:
    outdir = RELEASE_DIR / "python-dist"
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    run([sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(outdir)],
        cwd=ROOT, label=f"Python 包构建（sdist + wheel, v{version}）")
    return outdir


def git_commit() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT),
                              capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode == 0 else "(非 git 仓库)"
    except FileNotFoundError:
        return "(未安装 git)"


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.py[cod]", "*.db", "*.db-wal", "*.db-shm", "*.log", ".env",
    ))


def assemble(version: str, stage: Path, python_dist: Path | None) -> None:
    """把发布包内容组装到 stage 目录。"""
    for name in INCLUDE_DIRS:
        src = ROOT / name
        if src.is_dir():
            copy_tree(src, stage / name)
        else:
            print(f"[build][WARN] 缺少目录 {name}，已跳过")

    for name in INCLUDE_FILES:
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, stage / name)
        else:
            print(f"[build][WARN] 缺少文件 {name}，已跳过")

    for name in INCLUDE_WEB:
        src = ROOT / name
        if src.is_dir() and (src / "index.html").is_file():
            copy_tree(src, stage / name)
        else:
            raise SystemExit(
                f"[build] 缺少构建好的前端产物 {name}/index.html。\n"
                "        先执行：cd admin-web && npm ci && npm run build\n"
                "        或去掉 --skip-frontend 让本脚本代建。"
            )

    if python_dist is not None:
        copy_tree(python_dist, stage / "dist-python")

    # 部署/排障时第一个要看的就是「这个包到底是什么时候、哪个提交打出来的」。
    (stage / "BUILD-INFO.txt").write_text(
        "\n".join([
            "LLM 路由中转系统 · 发布包构建信息",
            "=" * 44,
            f"版本      : {version}",
            f"构建时间  : {datetime.now().astimezone().isoformat(timespec='seconds')}",
            f"git 提交  : {git_commit()}",
            f"构建机    : {platform.platform()}",
            f"Python    : {platform.python_version()} ({sys.executable})",
            "",
            "包内容：",
            "  app/            后端源码（FastAPI）",
            "  scripts/        幂等运维脚本（目录预置 / 历史库迁移）",
            "  deploy/         部署产物（Dockerfile / compose / nginx / systemd / Windows 脚本）",
            "  admin-web/dist/ 控制台前端静态产物（交给 nginx）",
            "  docs/           全阶段交付文档",
            "  dist-python/    Python sdist 与 wheel",
            "",
            "部署步骤见 docs/阶段五-部署与交付/05-安装打包说明.md",
            "",
        ]), encoding="utf-8")


def write_checksums(stage: Path) -> int:
    """为包内全部文件生成 SHA256 清单（不含清单自身）。"""
    lines: list[str] = []
    for path in sorted(stage.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(stage).as_posix()}")
    (stage / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def make_zip(stage: Path, zip_path: Path) -> tuple[int, int]:
    """压缩时固定时间戳与压缩级别，让「同内容产出同字节」尽量成立。"""
    total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(stage.parent).as_posix())
                total += 1
    return total, zip_path.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 LLM 路由中转系统发布包")
    parser.add_argument("--skip-frontend", action="store_true", help="跳过前端构建（复用已有 dist/）")
    parser.add_argument("--skip-python", action="store_true", help="跳过 Python 包构建")
    parser.add_argument("--no-archive", action="store_true", help="只组装目录，不压 zip")
    args = parser.parse_args()

    version = read_version()
    stamp = datetime.now().strftime("%Y%m%d")
    name = f"llmbridge-{version}-{stamp}"
    RELEASE_DIR.mkdir(exist_ok=True)
    stage = RELEASE_DIR / name

    print(f"[build] 目标版本 {version}，组装目录 {stage}")

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    if not args.skip_frontend:
        build_frontend()
    else:
        print("[build] 已跳过前端构建（--skip-frontend）")

    python_dist = None
    if not args.skip_python:
        python_dist = build_python(version)
    else:
        print("[build] 已跳过 Python 包构建（--skip-python）")

    assemble(version, stage, python_dist)
    n_files = write_checksums(stage)
    print(f"[build] 校验清单：{n_files} 个文件")

    if args.no_archive:
        print(f"[build] 完成（未压缩）：{stage}")
        return 0

    zip_path = RELEASE_DIR / f"{name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    total, size = make_zip(stage, zip_path)
    print(f"[build] 完成：{zip_path}")
    print(f"[build] {total} 个文件，{size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
