"""
SQL 风险评级
输入：QueryIntent + 生成的 SQL
输出：{risk: low/high/forbidden, reason: str}
"""
import os
import yaml
from typing import Dict
import sqlglot
from sqlglot import exp

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POLICY_PATH = os.path.join(BASE_DIR, "config", "risk_policy.yaml")


def _load_policy() -> dict:
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class RiskAssessor:
    def __init__(self):
        self.policy = _load_policy()

    def assess(self, sql: str, intent_dict: dict, user_role: str = "analyst") -> Dict[str, str]:
        """
        评估 SQL 风险。
        返回 {"risk": "low/high/forbidden", "reason": "..."}
        """
        # 1. 禁止访问的表
        tables = intent_dict.get("tables", [])
        forbidden = self.policy.get("forbidden_tables", [])
        for t in tables:
            if t in forbidden:
                return {"risk": "forbidden", "reason": f"禁止访问表 {t}"}

        # 2. 敏感表访问
        sensitive = self.policy.get("sensitive_tables", [])
        if sensitive:
            sensitive_tables = {s.split(".")[0] for s in sensitive}
            if any(t in sensitive_tables for t in tables):
                return {"risk": "high", "reason": "访问敏感表需审批"}

        # 3. 全表扫描（无 WHERE，非聚合）
        try:
            parsed = sqlglot.parse_one(sql, dialect="postgres")
            has_where = parsed.args.get("where") is not None
            has_group = parsed.args.get("group") is not None
            has_aggregation = any(
                isinstance(n, (exp.Sum, exp.Count, exp.Avg, exp.Max, exp.Min))
                for n in parsed.walk()
            )
            if not has_where and not has_group and not has_aggregation:
                return {"risk": "high", "reason": "无 WHERE 条件的全表扫描"}
        except Exception as e:
            return {"risk": "high", "reason": f"SQL 解析异常：{e}"}

        # 4. 多表 JOIN
        joins = intent_dict.get("joins", [])
        if len(joins) >= 3:
            return {"risk": "high", "reason": f"涉及 {len(joins)} 张表的 JOIN"}

        # 5. 全部通过
        return {"risk": "low", "reason": "常规查询"}

    def get_user_role(self, user_id: str) -> str:
        """从 Redis 或数据库查用户角色（简化：按用户 ID 前缀判断）"""
        # 生产环境从用户表查
        if user_id.startswith("admin"):
            return "admin"
        if user_id.startswith("mgr"):
            return "manager"
        return "analyst"

    def get_accessible_regions(self, user_role: str) -> list:
        """获取用户可访问的区域列表"""
        perms = self.policy.get("role_permissions", {}).get(user_role, {})
        regions = perms.get("accessible_regions", ["华东"])  # 默认只有华东
        if regions == "*":
            return None  # None 表示全部可见
        return regions