"""建表 + 种子数据（对应 05-数据库设计.sql 的 INSERT 段）。

用法：python -m app.seed
"""
import asyncio
import json

from app.core.security import hash_password
from app.db.session import SessionLocal, engine
from app.db.tables import AdminUser, Base, DecisionSample, EvalCase, Model, Provider, RouteRule


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        if (await session.get(AdminUser, 1)) is not None:
            print("seed: 已存在数据，跳过")
            return

        # 分段提交：SQLite 在未提交事务内也校验外键，必须先落被引用行
        # 注：本函数只写「开发环境最小可跑集」。交付态的 12 家主流厂商 + 代表模型
        #     由 scripts/seed_provider_catalog.py 幂等写入（均 enabled=False 待填 Key）。
        # remark 存「密钥申请入口 + 接入注意事项」，与 app/data/provider_catalog.py 同格式。
        session.add_all([
            Provider(id=1, name="DeepSeek", base_url="https://api.deepseek.com/v1",
                     api_key_encrypted="ENC_PLACEHOLDER_DEEPSEEK",
                     remark="密钥申请：https://platform.deepseek.com/api_keys"),
            Provider(id=2, name="OpenAI", base_url="https://api.openai.com/v1",
                     api_key_encrypted="ENC_PLACEHOLDER_OPENAI",
                     remark="密钥申请：https://platform.openai.com/api-keys"),
        ])
        await session.commit()

        session.add_all([
            Model(id=1, provider_id=1, model_name="deepseek-chat", display_name="DeepSeek Chat",
                  capabilities=json.dumps(["general", "code_generation"]), input_price=2.0,
                  output_price=8.0, context_window=65536, priority=10),
            Model(id=2, provider_id=1, model_name="deepseek-coder", display_name="DeepSeek Coder",
                  capabilities=json.dumps(["code_generation"]), input_price=2.0,
                  output_price=8.0, context_window=65536, priority=10),
            Model(id=3, provider_id=2, model_name="gpt-4o-mini", display_name="GPT-4o mini",
                  capabilities=json.dumps(["general", "translation", "summarize"]), input_price=1.25,
                  output_price=5.0, context_window=128000, priority=20),
            Model(id=4, provider_id=2, model_name="gpt-4o", display_name="GPT-4o",
                  capabilities=json.dumps(["general", "complex_reasoning", "long_context"]), input_price=20.0,
                  output_price=80.0, context_window=128000, priority=30),
        ])
        session.add_all([
            RouteRule(id=1, name="代码任务直达 Coder", priority=10, type="keyword",
                      condition_json=json.dumps({"all": [
                          {"field": "text", "op": "contains", "value": "def "},
                          {"field": "text", "op": "contains", "value": "debug"}]}),
                      target_model_id=2, remark="L1 示例"),
            RouteRule(id=2, name="翻译任务走 mini", priority=20, type="keyword",
                      condition_json=json.dumps({"all": [
                          {"field": "text", "op": "contains", "value": "翻译"}]}),
                      target_model_id=3, remark="L1 示例"),
        ])
        session.add(AdminUser(id=1, username="admin",
                              password_hash=hash_password("admin123"), role="admin"))
        await session.commit()  # 先落 provider/model/rule/user，保证外键可见

        session.add_all([
            EvalCase(input_text="帮我写一个 Python 函数，计算两个日期之间的工作日",
                     expected_task_type="code_generation", expected_model_id=2),
            EvalCase(input_text="把下面这段话翻译成英文：今天天气很好",
                     expected_task_type="translation", expected_model_id=3),
            EvalCase(input_text="总结这篇文章的核心观点，控制在 200 字以内",
                     expected_task_type="summarize", expected_model_id=3),
            EvalCase(input_text="用通俗语言解释一下什么是量子纠缠",
                     expected_task_type="general", expected_model_id=1),
        ])
        await session.commit()
        print("seed: 完成（8 表 + 厂商/模型/规则/admin/评测集）")


if __name__ == "__main__":
    asyncio.run(main())
