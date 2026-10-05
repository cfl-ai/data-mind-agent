"""
SQL 列级血缘追踪（兼容 sqllineage 新旧版本）
"""
from sqllineage.runner import LineageRunner


def _get_attr_or_call(obj, attr):
    """兼容 sqllineage 新旧版本：属性 vs 方法"""
    val = getattr(obj, attr)
    if callable(val):
        return val()
    return val


class SQLLineageTracker:
    def extract(self, sql: str) -> dict:
        """
        提取 SQL 的列级血缘。
        """
        try:
            runner = LineageRunner(sql)

            # ⚡ 兼容新旧 API
            source_tables = [str(t) for t in _get_attr_or_call(runner, "source_tables")]

            column_lineage = []
            try:
                col_lineage_raw = _get_attr_or_call(runner, "get_column_lineage")
            except AttributeError:
                col_lineage_raw = []

            for col in col_lineage_raw or []:
                try:
                    if isinstance(col, tuple):
                        # 老版本返回 tuple (sources..., target)
                        target = str(col[-1])
                        sources = [str(c) for c in col[:-1]]
                    else:
                        # 新版本返回对象
                        target = str(getattr(col, "target", col))
                        sources = [str(s) for s in getattr(col, "sources", [])]
                    column_lineage.append({"target": target, "sources": sources})
                except Exception:
                    continue

            return {
                "source_tables": source_tables,
                "column_lineage": column_lineage,
            }
        except Exception as e:
            return {
                "source_tables": [],
                "column_lineage": [],
                "error": f"{type(e).__name__}: {e}",
            }