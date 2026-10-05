"""
SQL 执行：支持参数化绑定
"""
from sqlalchemy import text
from app.db import engine


class SQLExecutor:
    def execute(self, sql: str, params: dict = None):
        """
        执行 SQL，支持参数绑定。
        返回 (success, rows_or_error)
        """
        try:
            with engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                rows = [dict(r._mapping) for r in result]
            return True, rows
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"


def format_result(rows: list) -> str:
    """把查询结果格式化成可读文本"""
    if not rows:
        return "（无数据）"

    if len(rows) == 1 and len(rows[0]) == 1:
        k, v = list(rows[0].items())[0]
        if isinstance(v, (int, float)):
            return f"{k}: {v:,}"
        return f"{k}: {v}"

    headers = list(rows[0].keys())
    lines = [" | ".join(headers)]
    lines.append("-" * 60)
    for row in rows[:20]:
        lines.append(" | ".join(str(row.get(h, "")) for h in headers))
    if len(rows) > 20:
        lines.append(f"... 共 {len(rows)} 行，只显示前 20 行")
    return "\n".join(lines)