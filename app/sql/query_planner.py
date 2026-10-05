"""
QueryIntent 提取器
LLM 只负责将自然语言转为结构化 JSON，不接触 SQL 语法
"""
import json
import re
from pydantic import BaseModel, Field, ValidationError
from typing import List, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.config import ZAI_API_KEY


# ============ QueryIntent 的 Pydantic 定义 ============
class JoinClause(BaseModel):
    left: str  # 如 "orders.region_id"
    right: str  # 如 "regions.id"


class FilterClause(BaseModel):
    field: str
    op: str = Field(description="操作符: =, >, <, >=, <=, IN, BETWEEN, LIKE")
    value: str


class Aggregation(BaseModel):
    func: str = Field(description="聚合函数: SUM, COUNT, AVG, MAX, MIN")
    field: str


class OrderBy(BaseModel):
    field: str
    direction: str = "DESC"


class QueryIntent(BaseModel):
    tables: List[str]
    joins: List[JoinClause] = []
    filters: List[FilterClause] = []
    aggregations: List[Aggregation] = []
    group_by: List[str] = []
    order_by: List[OrderBy] = []
    limit: Optional[int] = None


# ============ 提取器 ============
class QueryPlanner:
    ALLOWED_TABLES = ["departments", "employees", "regions", "categories",
                      "products", "orders", "order_items"]

    def __init__(self):
        self.llm = ChatOpenAI(
            model="glm-4-flash",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0,
        )

    def extract(self, question: str, schema_text: str) -> Optional[QueryIntent]:
        """从自然语言提取 QueryIntent"""
        prompt = f"""你是数据分析助手。请将用户问题转换为结构化的查询意图 JSON。

【可用表结构】
{schema_text}

【输出格式】
严格返回以下 JSON，不要任何解释：
{{
  "tables": ["涉及的表名"],
  "joins": [{{"left": "左表.字段", "right": "右表.字段"}}],
  "filters": [{{"field": "表.字段", "op": "=", "value": "值"}}],
  "aggregations": [{{"func": "SUM", "field": "表.字段"}}],
  "group_by": ["表.字段"],
  "order_by": [{{"field": "字段", "direction": "DESC"}}],
  "limit": null
}}

【规则】
1. 只使用上面列出的表和字段
2. 聚合函数只允许: SUM, COUNT, AVG, MAX, MIN
3. 操作符只允许: =, >, <, >=, <=, IN, BETWEEN, LIKE
4. 如果问"销售额"，用 SUM(orders.total_amount)，并加 filter: orders.status = '已完成'
5. 如果问"销量"，用 COUNT(*) 或 SUM(order_items.quantity)
6. 如果是计数，用 COUNT

用户问题：{question}

只返回 JSON。"""

        try:
            resp = self.llm.invoke([HumanMessage(content=prompt)]).content.strip()
            resp = re.sub(r"^```(?:json)?\s*", "", resp)
            resp = re.sub(r"\s*```$", "", resp)

            # 括号计数法提取 JSON
            start = resp.find("{")
            if start == -1:
                return None
            depth = 0
            end = -1
            for i in range(start, len(resp)):
                if resp[i] == "{":
                    depth += 1
                elif resp[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end == -1:
                return None

            data = json.loads(resp[start:end])
            intent = QueryIntent(**data)

            # 校验表名合法性
            for t in intent.tables:
                if t not in self.ALLOWED_TABLES:
                    print(f"🚨 [Planner] 非法表名: {t}")
                    return None

            print(f"📋 [Planner] QueryIntent 提取成功: tables={intent.tables}")
            return intent

        except ValidationError as e:
            print(f"⚠️ [Planner] 校验失败: {e}")
            return None
        except Exception as e:
            print(f"⚠️ [Planner] 提取失败: {e}")
            return None