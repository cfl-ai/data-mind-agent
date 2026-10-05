"""
SQL 校验：安全拦截 + 智能加 LIMIT
"""
import re
import sqlglot
from sqlglot import exp

FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete", "drop", "alter", "truncate",
    "create", "grant", "revoke", "copy", "vacuum",
]

MAX_ROWS = 1000


def _has_aggregation(sql: str) -> bool:
    """判断 SQL 是否包含聚合函数或 GROUP BY"""
    sql_upper = sql.upper()
    # 关键词检测
    if any(fn in sql_upper for fn in ["SUM(", "COUNT(", "AVG(", "MAX(", "MIN("]):
        return True
    if "GROUP BY" in sql_upper:
        return True
    # AST 检测（双保险）
    try:
        parsed = sqlglot.parse_one(sql, dialect="postgres")
        for node in parsed.walk():
            if isinstance(node, (exp.Sum, exp.Count, exp.Avg, exp.Max, exp.Min)):
                return True
            if isinstance(node, exp.Group):
                return True
    except Exception:
        pass
    return False


class SQLValidator:
    def validate(self, sql: str) -> tuple:
        """
        校验 SQL。
        返回 (is_safe, reason_or_sql)
        """
        sql = sql.strip().rstrip(";")

        if not sql:
            return False, "SQL 为空"

        # 1. 关键词检查
        sql_lower = sql.lower()
        for kw in FORBIDDEN_KEYWORDS:
            if re.search(r"\b" + kw + r"\b", sql_lower):
                return False, f"检测到危险操作: {kw}"

        # 2. 语法校验
        try:
            parsed = sqlglot.parse_one(sql, dialect="postgres")
        except Exception as e:
            return False, f"SQL 语法错误: {e}"

        # 3. 只允许 SELECT
        if not isinstance(parsed, exp.Select):
            return False, "只允许 SELECT 查询"

        # 4. 聚合查询跳过 LIMIT
        if _has_aggregation(sql):
            print(f"⚙️ [校验] 聚合查询，跳过 LIMIT")
            return True, sql

        # 5. 非聚合查询自动加 LIMIT
        if not parsed.args.get("limit"):
            sql = sql + f" LIMIT {MAX_ROWS}"
            print(f"⚙️ [校验] 已自动添加 LIMIT {MAX_ROWS}")

        return True, sql