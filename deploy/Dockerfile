# 说明：刻意不写 `# syntax=docker/dockerfile:1` —— 那行会让 buildx 去拉
# docker/dockerfile 前端镜像，在国内网络下可能连 auth.docker.io 都到不了，
# 构建死在第一步。本文件只用普通语法，守护进程内置 BuildKit 完全够用。
#
# LLM 路由中转系统 · 后端镜像
#
# 构建（**上下文必须是仓库根目录**，因为要拷 app/ 与 scripts/）：
#   docker build -f deploy/Dockerfile -t llmbridge-api:1.0.0 .
#
# 为什么仍推荐 `pip install -e .`（而不是 `pip install .`）：
#   非可编辑安装会把 app/ 复制进 site-packages。厂商目录预置**已不再依赖** scripts/
#   （实现在包内 app/data/catalog_seed.py），所以功能上两者都行；但可编辑安装让 app/
#   原地留在 /app，`scripts/` 下的运维脚本（数据迁移等）也能直接跑，调试时改代码免重装。

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai \
    LLMBRIDGE_REPO_ROOT=/app

WORKDIR /app

# 依赖清单与源码分开拷贝：改业务代码不会让「装依赖」这一层缓存失效。
COPY pyproject.toml README.md MANIFEST.in ./
COPY app ./app
COPY scripts ./scripts

# psycopg[binary] / cryptography / bcrypt 均有免编译 wheel，无需 gcc，镜像保持精简。
RUN pip install --no-cache-dir -e .

COPY deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY deploy/healthcheck.py /usr/local/bin/healthcheck.py
RUN chmod +x /usr/local/bin/entrypoint.sh

# 部署脚本也放进镜像（约几十 KB）：容器库是目标机唯一一定能访问的地址，于是
# 「安装脚本」可以随镜像一起交付，不必依赖 GitHub（国内不可达）。
# **这是目标机安装脚本的首选载体** —— 安装流程随后要拉的就是这套镜像，
# 所以取脚本这一步不会多下载一个字节：
#   docker run --rm --entrypoint cat <本镜像> /opt/llmbridge/deploy/docker-deploy.sh \
#     | bash -s -- --image
# 必须带 --entrypoint cat：默认 entrypoint 会先跑数据库初始化再起服务。
# （另有 8 MB 的纯安装器镜像 llmbridge-deploy，见 deploy/Dockerfile.deploy —— 更轻，
#   但要求该仓库在容器库里被设为公开；本镜像已确认可匿名拉取。）
COPY deploy/docker-deploy.sh deploy/docker-compose.image.yml /opt/llmbridge/deploy/

# 以非 root 运行：应用不需要写容器文件系统（日志走 stdout、数据库在外部）。
RUN useradd --create-home --shell /usr/sbin/nologin llmbridge \
    && chown -R llmbridge:llmbridge /app
USER llmbridge

EXPOSE 8000

# 用 Python 标准库探活，省掉镜像里装 curl。
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD ["python", "/usr/local/bin/healthcheck.py"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["llmbridge-serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
