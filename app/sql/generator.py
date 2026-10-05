"""
SQL 生成：调用 LLM 根据问题和 Schema 生成 PostgreSQL 查询
"""
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.config import ZAI_API_KEY


SQL_SYSTEM_PROMPT = """你是一个 PostgreSQL 专家，负责把用户的业务问题转换成 SQL 查询。

【绝对规则】
1. 只生成 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE
2. 只使用提供的表结构，不要虚构字段或表
3. 字段名和表名用英文原名（如 orders、total_amount）
4. 字符串用单引号（如 '华东'）
5. 日期用 'YYYY-MM-DD' 格式
6. 涉及销售额时，默认只统计 status = '已完成' 的订单
7. 结果返回聚合值，不加多余的字段

【结果可读性要求 - 重要】
1. 用户看不懂 ID，禁止直接返回 xxx_id 字段
2. 需要关联时，主动 JOIN 出业务名称
3. 例如：
   - 问"最贵的商品" → JOIN products 返回 name, price，不要返回 product_id
   - 问"各区域销售" → JOIN regions 返回 name, SUM(total_amount)
   - 问"谁的业绩最高" → JOIN employees 返回 name, SUM(total_amount)
4. 排序字段和展示字段都要有业务含义

【输出格式】
只输出 SQL 语句本身，不要 markdown 代码块，不要解释，不要加分号。

示例输出：
SELECT p.name, p.price FROM products p ORDER BY p.price DESC LIMIT 5
"""


class SQLGenerator:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="glm-4-flash",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0,
        )

    def generate(self, question: str, schema_text: str, current_date: str = "2026-09-30") -> str:
        """根据问题和 Schema 生成 SQL"""
        prompt = f"""当前日期：{current_date}

{schema_text}

用户问题：{question}

请输出对应的 PostgreSQL SQL 查询语句。"""

        messages = [
            HumanMessage(content=SQL_SYSTEM_PROMPT + "\n\n" + prompt)
        ]

        resp = self.llm.invoke(messages).content.strip()

        # 清理可能残留的 markdown 代码块
        resp = re.sub(r"^```(?:sql)?\s*", "", resp)
        resp = re.sub(r"\s*```$", "", resp)
        resp = resp.strip().rstrip(";")

        return resp