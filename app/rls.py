def inject_region_filter(sql: str, accessible_regions: list) -> str:
    """
    智能 RLS 注入：
    - 如果 SQL 已经指定了具体区域（regions.name = :pX 或 IN (...)），不再注入
    - 否则，如果是"看全部区域"的查询，才注入 accessible_regions
    """
    if not accessible_regions:
        return sql

    # 如果 SQL 里已经有具体的 regions.name 过滤，说明用户明确问了某个区域
    # 这时 RLS 只需保证该区域在用户权限内（应用层已通过 role_permissions 限制）
    import re
    has_specific_region = bool(re.search(r"regions\.name\s*(=|IN|LIKE)", sql, re.IGNORECASE))
    if has_specific_region:
        return sql  # 不注入，避免冗余

    # 没有具体区域过滤 → 说明是"查全部区域"的聚合查询
    if "regions.name" not in sql and "regions" not in sql:
        return sql  # 查询不涉及区域，跳过

    regions_quoted = ",".join(f"'{r}'" for r in accessible_regions)

    if " WHERE " in sql.upper():
        return sql.replace(
            " WHERE ",
            f" WHERE regions.name IN ({regions_quoted}) AND ",
            1,
        )

    for kw in [" GROUP BY ", " ORDER BY ", " LIMIT "]:
        if kw in sql.upper():
            idx = sql.upper().index(kw)
            return sql[:idx] + f" WHERE regions.name IN ({regions_quoted}) " + sql[idx:]

    return sql + f" WHERE regions.name IN ({regions_quoted})"