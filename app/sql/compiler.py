"""
确定性 SQL 编译器（适配扁平 QueryIntent）
把 QueryIntent 编译为 PostgreSQL 参数化 SQL
- 不经过 LLM
- 所有值用 :param 绑定
- 白名单校验表/字段/JOIN
"""
from typing import Dict, Any

from app.sql.query_intent import (
    QueryIntent, ALLOWED_TABLES, ALLOWED_COLUMNS, ALLOWED_JOINS,
)


class CompileError(Exception):
    pass


class DeterministicCompiler:

    def compile(self, intent: QueryIntent) -> Dict[str, Any]:
        self._validate(intent)

        select_clause = self._build_select(intent)
        from_clause = self._build_from(intent)
        where_clause, params = self._build_where(intent)
        group_clause = self._build_group_by(intent)
        order_clause = self._build_order_by(intent)
        limit_clause = self._build_limit(intent)

        parts = [select_clause, from_clause]
        if where_clause:
            parts.append(where_clause)
        if group_clause:
            parts.append(group_clause)
        if order_clause:
            parts.append(order_clause)
        if limit_clause:
            parts.append(limit_clause)

        return {
            "sql": " ".join(parts),
            "params": params,
            "tables_used": intent.tables,
        }

    # ============ 白名单校验 ============

    def _validate(self, intent: QueryIntent):
        for t in intent.tables:
            if t not in ALLOWED_TABLES:
                raise CompileError(f"表不在白名单：{t}")

        for j in intent.joins:
            key = (j.left_table, j.right_table, j.left_column, j.right_column)
            key_rev = (j.right_table, j.left_table, j.right_column, j.left_column)
            if key not in ALLOWED_JOINS and key_rev not in ALLOWED_JOINS:
                raise CompileError(
                    f"JOIN 不在白名单：{j.left_table}.{j.left_column} = "
                    f"{j.right_table}.{j.right_column}"
                )

        for f in intent.filters:
            self._check_qualified(f.column)

        for a in intent.aggregations:
            if a.column:
                self._check_qualified(a.column)

        for g in intent.group_by:
            self._check_qualified(g)

    def _check_qualified(self, name: str):
        if "." not in name:
            raise CompileError(f"字段必须是 表.列 格式：{name}")
        table, col = name.split(".", 1)
        if table not in ALLOWED_TABLES:
            raise CompileError(f"表不在白名单：{table}")
        if col not in ALLOWED_COLUMNS.get(table, []):
            raise CompileError(f"字段不在白名单：{table}.{col}")

    # ============ 构建 SQL 子句 ============

    def _build_select(self, intent: QueryIntent) -> str:
        items = []

        for a in intent.aggregations:
            func = (a.func or "").upper()
            if func not in ("COUNT", "SUM", "AVG", "MAX", "MIN"):
                raise CompileError(f"非法聚合函数：{func}")
            if a.column:
                expr = f"{func}({a.column})"
            else:
                expr = f"{func}(*)"
            items.append(f"{expr} AS \"{a.alias}\"")

        for g in intent.group_by:
            items.append(g)

        if not items:
            items.append("*")

        return "SELECT " + ", ".join(items)

    def _build_from(self, intent: QueryIntent) -> str:
        if not intent.tables:
            raise CompileError("tables 不能为空")

        base = intent.tables[0]
        sql = f"FROM {base}"

        for j in intent.joins:
            jt = (j.join_type or "INNER").upper()
            if jt not in ("INNER", "LEFT", "RIGHT"):
                jt = "INNER"
            if j.left_table == base:
                sql += (
                    f" {jt} JOIN {j.right_table} "
                    f"ON {j.left_table}.{j.left_column} = "
                    f"{j.right_table}.{j.right_column}"
                )
            else:
                sql += (
                    f" {jt} JOIN {j.left_table} "
                    f"ON {j.left_table}.{j.left_column} = "
                    f"{j.right_table}.{j.right_column}"
                )

        return sql

    def _build_where(self, intent: QueryIntent) -> tuple:
        clauses = []
        params = {}
        idx = 1

        for f in intent.filters:
            op = (f.op or "=").upper()
            col = f.column

            if op == "IN":
                if not isinstance(f.value, list):
                    continue
                phs = []
                for v in f.value:
                    key = f"p{idx}"
                    phs.append(f":{key}")
                    params[key] = v
                    idx += 1
                clauses.append(f"{col} IN ({', '.join(phs)})")
            elif op == "BETWEEN":
                if not isinstance(f.value, list) or len(f.value) != 2:
                    continue
                k1, k2 = f"p{idx}", f"p{idx+1}"
                params[k1] = f.value[0]
                params[k2] = f.value[1]
                clauses.append(f"{col} BETWEEN :{k1} AND :{k2}")
                idx += 2
            elif op in ("=", "!=", ">", ">=", "<", "<=", "LIKE"):
                key = f"p{idx}"
                clauses.append(f"{col} {op} :{key}")
                params[key] = f.value
                idx += 1

        if not clauses:
            return "", {}

        return "WHERE " + " AND ".join(clauses), params

    def _build_group_by(self, intent: QueryIntent) -> str:
        if not intent.group_by:
            return ""
        return "GROUP BY " + ", ".join(intent.group_by)

    def _build_order_by(self, intent: QueryIntent) -> str:
        if not intent.order_by:
            return ""
        # 收集所有聚合别名（用于识别 ORDER BY 是否引用了别名）
        aliases = {a.alias for a in intent.aggregations}

        parts = []
        for o in intent.order_by:
            d = (o.direction or "DESC").upper()
            if d not in ("ASC", "DESC"):
                d = "DESC"
            col = o.column
            # ⚡ 如果 ORDER BY 引用的是聚合别名，加双引号
            if col in aliases:
                parts.append(f'"{col}" {d}')
            else:
                parts.append(f"{col} {d}")
        return "ORDER BY " + ", ".join(parts)

    def _build_limit(self, intent: QueryIntent) -> str:
        # 用户明确指定 limit 时，用用户的
        if intent.limit:
            return f"LIMIT {intent.limit}"
        # 其他情况都不加 LIMIT，交给 validator 决定
        # - 聚合查询（SUM/COUNT/GROUP BY）→ validator 跳过
        # - 非聚合查询 → validator 自动加 LIMIT 1000
        return ""