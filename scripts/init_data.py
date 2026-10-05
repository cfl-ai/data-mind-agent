"""
数据生成脚本：建表 + 生成 5000 订单 + 15000 明细
运行：python scripts/init_data.py
"""
import os
import sys
import random
from datetime import datetime, timedelta

# 让脚本能导入 app 模块
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from sqlalchemy import text
from app.db import engine

random.seed(42)  # 结果可复现


def run_schema():
    """执行建表 SQL"""
    schema_path = os.path.join(BASE_DIR, "scripts", "init_schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql_script = f.read()

    with engine.connect() as conn:
        for stmt in sql_script.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        conn.commit()
    print("✅ 建表完成")


def gen_departments(conn):
    data = [
        {"name": "销售一部", "manager": "张伟"},
        {"name": "销售二部", "manager": "李娜"},
        {"name": "销售三部", "manager": "王强"},
    ]
    for d in data:
        conn.execute(text(
            "INSERT INTO departments (name, manager) VALUES (:name, :manager)"
        ), d)
    conn.commit()
    print(f"✅ 部门: {len(data)} 条")
    return list(range(1, len(data) + 1))


def gen_employees(conn, dept_ids):
    surnames = ["张", "李", "王", "刘", "陈", "杨", "赵", "黄", "周", "吴",
                "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗"]
    given = ["伟", "娜", "强", "静", "磊", "敏", "洋", "丽", "勇", "艳",
             "杰", "娟", "涛", "芳", "明", "霞", "超", "燕", "军", "红"]
    roles = ["专员", "经理", "总监"]

    count = 0
    for i in range(30):
        name = random.choice(surnames) + random.choice(given)
        dept = random.choice(dept_ids)
        role = random.choices(roles, weights=[7, 2, 1])[0]
        hire = datetime(2022, 1, 1) + timedelta(days=random.randint(0, 1000))
        conn.execute(text(
            "INSERT INTO employees (name, department_id, role, hire_date) "
            "VALUES (:name, :department_id, :role, :hire_date)"
        ), {"name": name, "department_id": dept, "role": role, "hire_date": hire.date()})
        count += 1
    conn.commit()
    print(f"✅ 员工: {count} 条")
    return list(range(1, count + 1))


def gen_regions(conn):
    data = [
        {"name": "华东", "parent_region": None},
        {"name": "华南", "parent_region": None},
        {"name": "华北", "parent_region": None},
        {"name": "西南", "parent_region": None},
        {"name": "上海", "parent_region": "华东"},
        {"name": "江苏", "parent_region": "华东"},
        {"name": "浙江", "parent_region": "华东"},
        {"name": "广东", "parent_region": "华南"},
        {"name": "福建", "parent_region": "华南"},
        {"name": "北京", "parent_region": "华北"},
        {"name": "天津", "parent_region": "华北"},
        {"name": "河北", "parent_region": "华北"},
        {"name": "四川", "parent_region": "西南"},
        {"name": "重庆", "parent_region": "西南"},
        {"name": "云南", "parent_region": "西南"},
        {"name": "贵州", "parent_region": "西南"},
    ]
    for d in data:
        conn.execute(text(
            "INSERT INTO regions (name, parent_region) VALUES (:name, :parent_region)"
        ), d)
    conn.commit()
    print(f"✅ 区域: {len(data)} 条")
    major = [1, 2, 3, 4]
    cities = list(range(5, 17))
    return major, cities


def gen_categories(conn):
    data = [
        {"name": "跑步鞋", "parent_category": None},
        {"name": "篮球鞋", "parent_category": None},
        {"name": "服饰", "parent_category": None},
        {"name": "配件", "parent_category": None},
        {"name": "竞速跑鞋", "parent_category": "跑步鞋"},
        {"name": "训练跑鞋", "parent_category": "跑步鞋"},
        {"name": "休闲跑鞋", "parent_category": "跑步鞋"},
        {"name": "实战篮球鞋", "parent_category": "篮球鞋"},
        {"name": "休闲篮球鞋", "parent_category": "篮球鞋"},
        {"name": "T恤", "parent_category": "服饰"},
        {"name": "卫衣", "parent_category": "服饰"},
        {"name": "运动裤", "parent_category": "服饰"},
        {"name": "袜子", "parent_category": "配件"},
        {"name": "帽子", "parent_category": "配件"},
        {"name": "背包", "parent_category": "配件"},
        {"name": "水壶", "parent_category": "配件"},
    ]
    for d in data:
        conn.execute(text(
            "INSERT INTO categories (name, parent_category) VALUES (:name, :parent_category)"
        ), d)
    conn.commit()
    print(f"✅ 品类: {len(data)} 条")
    return [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]


def gen_products(conn, category_ids):
    templates = [
        ("绝尘5", 6, 399, 150),
        ("芷境4", 5, 499, 180),
        ("芷境飞鸿", 5, 899, 320),
        ("极风4", 7, 329, 120),
        ("闪电4", 6, 318, 130),
        ("云逐2", 7, 258, 100),
        ("悦驰2", 7, 238, 95),
        ("方舟", 6, 249, 90),
        ("奇弹板鞋", 9, 299, 110),
        ("冰丝T恤", 10, 129, 45),
        ("户外卫衣", 11, 129, 50),
        ("风栖梧3", 7, 239, 90),
    ]
    for name, cat_id, price, cost in templates:
        launch = datetime(2024, random.randint(1, 12), random.randint(1, 28))
        conn.execute(text(
            "INSERT INTO products (name, category_id, price, cost, launch_date) "
            "VALUES (:name, :category_id, :price, :cost, :launch_date)"
        ), {"name": name, "category_id": cat_id, "price": price,
            "cost": cost, "launch_date": launch.date()})
    conn.commit()
    print(f"✅ 商品: {len(templates)} 条")
    return list(range(1, len(templates) + 1))


def gen_orders(conn, employee_ids, region_ids, product_ids):
    """生成 5000 订单 + 明细"""
    start = datetime(2025, 1, 1)
    end = datetime(2026, 9, 30)
    total_days = (end - start).days

    # 区域权重
    region_weights = {1: 35, 2: 25, 3: 22, 4: 18}
    region_pool = []
    for rid, w in region_weights.items():
        region_pool.extend([rid] * w)

    # 月份波动
    def month_weight(d):
        m = d.month
        if m in (11, 12): return 3
        if m == 6: return 2
        if m in (1, 2): return 1
        return 2

    # 商品权重
    product_weights = {
        1: 12, 2: 8, 3: 4, 4: 6, 5: 6, 6: 5,
        7: 4, 8: 4, 9: 5, 10: 8, 11: 6, 12: 5,
    }
    product_pool = []
    for pid, w in product_weights.items():
        product_pool.extend([pid] * w)

    # 预取所有商品价格
    price_map = {}
    for row in conn.execute(text("SELECT id, price FROM products")):
        price_map[row[0]] = float(row[1])

    total_items = 0

    # 批量插入
    for i in range(5000):
        # 用月份加权抽样日期
        while True:
            d = start + timedelta(days=random.randint(0, total_days))
            if random.randint(1, 3) <= month_weight(d):
                break

        region_id = random.choice(region_pool)
        employee_id = random.choice(employee_ids)

        status = random.choices(
            ["已完成", "退款中", "已取消"], weights=[85, 10, 5]
        )[0]

        num_items = random.choices([1, 2, 3, 4], weights=[50, 30, 15, 5])[0]

        items = []
        total_amount = 0
        for _ in range(num_items):
            pid = random.choice(product_pool)
            qty = random.choices([1, 2, 3], weights=[80, 15, 5])[0]
            unit_price = price_map[pid]
            total_amount += unit_price * qty
            items.append({
                "product_id": pid,
                "quantity": qty,
                "unit_price": unit_price,
            })

        order_no = f"ORD{i + 1:08d}"

        result = conn.execute(text(
            "INSERT INTO orders (order_no, employee_id, region_id, order_date, status, total_amount) "
            "VALUES (:order_no, :employee_id, :region_id, :order_date, :status, :total_amount) "
            "RETURNING id"
        ), {
            "order_no": order_no,
            "employee_id": employee_id,
            "region_id": region_id,
            "order_date": d.date(),
            "status": status,
            "total_amount": round(total_amount, 2),
        })
        order_id = result.fetchone()[0]

        for item in items:
            conn.execute(text(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price) "
                "VALUES (:order_id, :product_id, :quantity, :unit_price)"
            ), {"order_id": order_id, **item})
            total_items += 1

        # 每 500 条提交一次，避免长事务
        if (i + 1) % 500 == 0:
            conn.commit()
            print(f"   已生成 {i + 1} 条订单...")

    conn.commit()
    print(f"✅ 订单: 5000 条")
    print(f"✅ 订单明细: {total_items} 条")


def main():
    print("🚀 开始初始化数据库...\n")

    run_schema()

    with engine.connect() as conn:
        dept_ids = gen_departments(conn)
        emp_ids = gen_employees(conn, dept_ids)
        major_ids, city_ids = gen_regions(conn)
        cat_ids = gen_categories(conn)
        prod_ids = gen_products(conn, cat_ids)
        gen_orders(conn, emp_ids, major_ids + city_ids, prod_ids)

    print("\n🎉 数据库初始化完成！")
    print("\n验证 SQL：")
    print("  docker exec -it datamind-pg psql -U postgres -d datamind -c \"SELECT COUNT(*) FROM orders;\"")


if __name__ == "__main__":
    main()