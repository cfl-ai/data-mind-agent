"""
QueryIntent：简化的查询意图 DSL
- 扁平结构（"表.列" 用字符串表示），GLM-4-Flash 容易输出
- extra="ignore"：LLM 多输出字段也不报错
"""
from enum import Enum
from typing import List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class QueryType(str, Enum):
    SELECT = "select"
    COUNT = "count"
    AGGREGATE = "aggregate"


class Condition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    column: str = Field(..., description="表.列 格式，如 'regions.name'")
    op: str = Field(default="=", description="=, !=, >, >=, <, <=, IN, LIKE, BETWEEN")
    value: Any = Field(..., description="值或列表")


class Aggregation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    func: str = Field(..., description="COUNT / SUM / AVG / MAX / MIN")
    column: Optional[str] = Field(None, description="表.列；COUNT(*) 时可为空")
    alias: str = Field(..., description="结果别名")


class JoinSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    join_type: str = Field(default="INNER")


class OrderBy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    column: str = Field(..., description="别名或表.列")
    direction: str = Field(default="DESC", description="ASC / DESC")


class QueryIntent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query_type: str = Field(default="aggregate")
    tables: List[str] = Field(default_factory=list)
    joins: List[JoinSpec] = Field(default_factory=list)
    filters: List[Condition] = Field(default_factory=list)
    aggregations: List[Aggregation] = Field(default_factory=list)
    group_by: List[str] = Field(default_factory=list)   # 扁平："表.列"
    order_by: List[OrderBy] = Field(default_factory=list)
    limit: Optional[int] = Field(None, ge=1, le=1000)


# ============ 白名单 ============

ALLOWED_TABLES = {
    "departments", "employees", "regions",
    "categories", "products", "orders", "order_items"
}

ALLOWED_COLUMNS = {
    "departments": ["id", "name", "manager"],
    "employees": ["id", "name", "department_id", "role", "hire_date"],
    "regions": ["id", "name", "parent_region"],
    "categories": ["id", "name", "parent_category"],
    "products": ["id", "name", "category_id", "price", "cost", "launch_date"],
    "orders": ["id", "order_no", "employee_id", "region_id",
               "order_date", "status", "total_amount"],
    "order_items": ["id", "order_id", "product_id", "quantity", "unit_price"],
}

ALLOWED_JOINS = {
    ("employees", "departments", "department_id", "id"),
    ("orders", "employees", "employee_id", "id"),
    ("orders", "regions", "region_id", "id"),
    ("products", "categories", "category_id", "id"),
    ("order_items", "orders", "order_id", "id"),
    ("order_items", "products", "product_id", "id"),
}