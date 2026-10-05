"""
意图路由（优化版）
"""
import re
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.config import ZAI_API_KEY


GREETING_KEYWORDS = ["你好", "您好", "hi", "hello", "在吗", "嗨"]

UNSUPPORTED_KEYWORDS = [
    "天气", "讲个笑话", "写代码", "写诗", "股票", "基金",
    "你是谁", "你叫什么", "你几岁", "怎么追女生", "推荐电影",
]

METRIC_KEYWORDS = ["怎么算", "怎么计算", "口径", "定义是什么", "是什么意思"]

# ⚡ 新增：数据查询快速规则（先于 LLM 兜底）
DATA_QUERY_KEYWORDS = [
    # 聚合词
    "多少", "几", "总数", "总金额", "总额", "总共有",
    "最高", "最低", "最大", "最小", "最贵", "最便宜", "最畅销", "销量最高",
    "排行", "排名", "top", "前几", "前10",
    "占比", "比例", "百分比", "分布",
    "趋势", "走势", "每月", "每天", "按月",
    "平均", "均值",
    # 维度词
    "区域", "地区", "华东", "华南", "华北", "西南",
    "商品", "产品", "品类", "类别", "订单", "销售额", "gmv",
    "员工", "部门", "城市", "月份", "日期",
    # 查询动词
    "查", "查询", "统计", "看看", "看看有", "分析",
    "列出", "显示", "有哪些", "有多少",
]


class IntentRouter:
    def __init__(self):
        self.llm = ChatOpenAI(
            model="glm-4-flash",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0,
        )

    def route(self, query: str) -> str:
        """路由意图"""
        q = query.strip().lower()

        # 1. 打招呼
        if any(kw in q for kw in GREETING_KEYWORDS) and len(q) <= 15:
            print(f"🧭 [路由] greeting")
            return "greeting"

        # 2. 明确超范围（关键词命中）
        if any(kw in q for kw in UNSUPPORTED_KEYWORDS):
            print(f"🧭 [路由] unsupported（关键词）")
            return "unsupported"

        # 3. 问口径
        if any(kw in q for kw in METRIC_KEYWORDS) and any(
            k in q for k in ["gmv", "销售额", "利润", "客单价", "转化率", "复购率"]
        ):
            print(f"🧭 [路由] explain_metric")
            return "explain_metric"

        # ⚡ 4. 数据查询快速规则（新增，避开 LLM 误判）
        if any(kw in q for kw in DATA_QUERY_KEYWORDS):
            print(f"🧭 [路由] query_data（关键词命中）")
            return "query_data"

        # 5. LLM 兜底（更严格的判定）
        prompt = f"""判断用户问题是否与"公司内部业务数据查询"相关。

【相关的例子】
- 最贵的东西
- 有多少客户
- 给我看看销量
- 排个名
- 分析下趋势
- 哪些商品卖得好

【不相关的例子】
- 天气怎么样
- 讲个笑话
- 股票行情
- 你是谁
- 推荐一部电影

用户问题：{query}

【重要】如果问题是"名词短语"或"业务相关"，即使不完整也判断为相关。
只返回一个词：query_data 或 unsupported。
"""
        try:
            resp = self.llm.invoke([HumanMessage(content=prompt)]).content.strip().lower()
            intent = resp.split()[0] if resp else "query_data"
            # 去掉标点
            intent = re.sub(r"[^a-z_]", "", intent)
            if intent not in ("query_data", "unsupported"):
                intent = "query_data"
        except Exception:
            intent = "query_data"

        print(f"🧭 [路由] {intent}（LLM 兜底）")
        return intent


def greeting_reply() -> str:
    return "您好~ 我是 DataMind 业务数据分析助手，可以帮您查询销售、订单、商品、区域等业务数据。请问您想了解什么？"


def unsupported_reply() -> str:
    return (
        "抱歉，我目前只支持查询公司业务数据，比如销售额、订单量、商品排行、区域分布等。\n"
        "您可以试试问：\n"
        "  - 上个月华东区销售额是多少？\n"
        "  - 销量最高的商品是什么？\n"
        "  - 每个区域的已完成订单金额？"
    )


def metric_reply(query: str) -> str:
    q = query.lower()
    if "gmv" in q or "销售额" in q:
        return "销售额（GMV）口径：统计 status='已完成' 的订单的 total_amount 之和。退款中和已取消的订单不计入。"
    if "客单价" in q:
        return "客单价 = 销售额 / 订单数，只统计已完成订单。"
    if "利润" in q:
        return "利润 = 销售额 - 成本。成本需要关联 order_items.quantity × products.cost 计算。"
    return "抱歉，这个指标的口径暂时没有收录，请咨询数据团队。"