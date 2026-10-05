"""
自校正 Agent
执行失败时，分析错误并修正 SQL，最多重试 3 次
"""
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.config import ZAI_API_KEY


CORRECTION_PROMPT = """你是 SQL 修正专家。用户的 SQL 执行失败了，请根据错误信息修正。

【表结构】
- departments(id, name, manager)
- employees(id, name, department_id, role, hire_date)
- regions(id, name, parent_region)
- categories(id, name, parent_category)
- products(id, name, category_id, price, cost, launch_date)
- orders(id, order_no, employee_id, region_id, order_date, status, total_amount)
- order_items(id, order_id, product_id, quantity, unit_price)

【原始 SQL】
{sql}

【参数】
{params}

【错误信息】
{error}

【要求】
1. 只输出修正后的 SQL，不要解释
2. 保持参数化（:p1, :p2 等）
3. 不要引入白名单外的表/字段

【修正后的 SQL】"""


class CorrectionAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="glm-4-flash",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0,
        )
        self.max_retries = 3

    def correct(self, sql: str, params: dict, error: str) -> str:
        """修正 SQL，返回新 SQL（失败返回原 SQL）"""
        prompt = CORRECTION_PROMPT.format(
            sql=sql,
            params=str(params),
            error=error,
        )
        try:
            resp = self.llm.invoke([HumanMessage(content=prompt)]).content.strip()
            resp = re.sub(r"^```(?:sql)?\s*", "", resp)
            resp = re.sub(r"\s*```$", "", resp)
            resp = resp.strip().rstrip(";")
            return resp
        except Exception as e:
            print(f"⚠️ [修正] 失败：{e}")
            return sql  # 返回原 SQL