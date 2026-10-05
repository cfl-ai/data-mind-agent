"""
QueryIntent 提取器
GLM-4-Flash 输出扁平 JSON，不需要嵌套结构
"""
import json
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.config import ZAI_API_KEY
from app.sql.query_intent import QueryIntent


SYSTEM_PROMPT = """你是一个查询意图提取器。把用户问题转成 JSON 格式的 QueryIntent。

【绝对规则】
1. 只输出 JSON，不要解释，不要 markdown 代码块
2. 字段格式一律 "表.列"（如 "orders.total_amount"），不要嵌套对象
3. 不存在的表和字段不要编造
4. 涉及销售额时，status 必须过滤 '已完成'

【可用表与字段】
- departments: id, name, manager
- employees: id, name, department_id, role, hire_date
- regions: id, name, parent_region
- categories: id, name, parent_category
- products: id, name, category_id, price, cost, launch_date
- orders: id, order_no, employee_id, region_id, order_date, status, total_amount
- order_items: id, order_id, product_id, quantity, unit_price

【JOIN 白名单】
- orders.region_id = regions.id
- orders.employee_id = employees.id
- products.category_id = categories.id
- order_items.order_id = orders.id
- order_items.product_id = products.id
- employees.department_id = departments.id

【JSON 输出格式】
{
  "query_type": "aggregate",
  "tables": ["orders"],
  "joins": [],
  "filters": [{"column": "orders.status", "op": "=", "value": "已完成"}],
  "aggregations": [{"func": "SUM", "column": "orders.total_amount", "alias": "销售额"}],
  "group_by": [],
  "order_by": [],
  "limit": null
}

【字段含义】
- query_type: select / count / aggregate
- aggregations: func 只能是 COUNT/SUM/AVG/MAX/MIN
- filters: op 只能是 =, !=, >, >=, <, <=, IN, LIKE, BETWEEN
- group_by: 数组，元素是 "表.列" 字符串
- order_by: 数组，元素是 {"column": "别名或表.列", "direction": "ASC/DESC"}
- limit: 数字或 null

【示例 1】华东区的销售额是多少？
{"query_type":"aggregate","tables":["orders","regions"],"joins":[{"left_table":"orders","left_column":"region_id","right_table":"regions","right_column":"id","join_type":"INNER"}],"filters":[{"column":"regions.name","op":"=","value":"华东"},{"column":"orders.status","op":"=","value":"已完成"}],"aggregations":[{"func":"SUM","column":"orders.total_amount","alias":"销售额"}],"group_by":[],"order_by":[],"limit":null}

【示例 2】每个区域的已完成订单金额
{"query_type":"aggregate","tables":["orders","regions"],"joins":[{"left_table":"orders","left_column":"region_id","right_table":"regions","right_column":"id","join_type":"INNER"}],"filters":[{"column":"orders.status","op":"=","value":"已完成"}],"aggregations":[{"func":"SUM","column":"orders.total_amount","alias":"金额"}],"group_by":["regions.name"],"order_by":[],"limit":null}

【示例 3】最贵的商品
{"query_type":"select","tables":["products"],"joins":[],"filters":[],"aggregations":[],"group_by":[],"order_by":[{"column":"products.price","direction":"DESC"}],"limit":1}

【示例 4】销量最高的商品
{"query_type":"aggregate","tables":["order_items","products"],"joins":[{"left_table":"order_items","left_column":"product_id","right_table":"products","right_column":"id","join_type":"INNER"}],"filters":[],"aggregations":[{"func":"SUM","column":"order_items.quantity","alias":"销量"}],"group_by":["products.name"],"order_by":[{"column":"销量","direction":"DESC"}],"limit":1}

【示例 5】总共有多少订单
{"query_type":"count","tables":["orders"],"joins":[],"filters":[],"aggregations":[{"func":"COUNT","column":null,"alias":"订单总数"}],"group_by":[],"order_by":[],"limit":null}
"""


class IntentExtractor:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="glm-4-flash",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0,
        )

    def extract(self, question: str) -> QueryIntent:
        messages = [
            HumanMessage(content=SYSTEM_PROMPT + f"\n\n【用户问题】{question}\n【输出】")
        ]
        resp = self.llm.invoke(messages).content.strip()

        # 清理 markdown 代码块
        resp = re.sub(r"^```(?:json)?\s*", "", resp)
        resp = re.sub(r"\s*```$", "", resp)
        resp = resp.strip()

        # 括号计数法提取第一个 JSON 对象
        start = resp.find("{")
        if start == -1:
            raise ValueError(f"未找到 JSON：{resp[:200]}")

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
            raise ValueError(f"JSON 未闭合：{resp[:200]}")

        json_str = resp[start:end]
        data = json.loads(json_str)

        # Pydantic 校验
        return QueryIntent(**data)