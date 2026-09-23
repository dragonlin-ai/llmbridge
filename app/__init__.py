"""LLM 路由中转系统 · 应用包根。

显式声明为常规包（而非 PEP 420 命名空间包）：
setuptools 的 `packages.find` 依赖 `__init__.py` 才会收录子包，
缺了它打出的 wheel 会静默漏包，装完直接 ModuleNotFoundError。
"""
