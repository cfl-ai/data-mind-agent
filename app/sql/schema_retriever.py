"""
四层自适应 Schema 检索
参考 AriaSQL：BM25 + Dense + RRF + FK-Graph Expansion
"""
import os
import pickle
import networkx as nx
from rank_bm25 import BM25Okapi
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from sqlalchemy import text

from app.config import ZAI_API_KEY
from app.db import engine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INDEX_DIR = os.path.join(BASE_DIR, "schema_index")


SCHEMA_DOCS = {
    "departments": {
        "content": """departments 部门表
字段: id(主键), name(部门名称:销售一部/二部/三部), manager(经理)
用途: 按部门维度统计销售业绩""",
        "columns": ["id", "name", "manager"],
    },
    "employees": {
        "content": """employees 员工表
字段: id(主键), name(员工姓名), department_id(关联departments.id), role(角色:专员/经理/总监), hire_date(入职日期)
用途: 按员工统计业绩, 分析不同角色贡献""",
        "columns": ["id", "name", "department_id", "role", "hire_date"],
    },
    "regions": {
        "content": """regions 区域表
字段: id(主键), name(区域名称:华东/华南/华北/西南及下属省市), parent_region(上级区域)
用途: 按区域维度统计销售, 对比大区业绩""",
        "columns": ["id", "name", "parent_region"],
    },
    "categories": {
        "content": """categories 品类表
字段: id(主键), name(品类名称:跑步鞋/篮球鞋/服饰/配件及子类), parent_category(上级品类)
用途: 按品类维度统计销售, 分析各品类占比""",
        "columns": ["id", "name", "parent_category"],
    },
    "products": {
        "content": """products 商品表
字段: id(主键), name(商品名称), category_id(关联categories.id), price(售价), cost(成本价), launch_date(上市日期)
用途: 商品销售分析, 毛利计算, 热销商品排行""",
        "columns": ["id", "name", "category_id", "price", "cost", "launch_date"],
    },
    "orders": {
        "content": """orders 订单表
字段: id(主键), order_no(订单号), employee_id(关联employees.id), region_id(关联regions.id), order_date(下单日期), status(状态:已完成/退款中/已取消), total_amount(订单总金额)
用途: 销售总额统计, 趋势分析, 订单状态分析""",
        "columns": ["id", "order_no", "employee_id", "region_id",
                    "order_date", "status", "total_amount"],
    },
    "order_items": {
        "content": """order_items 订单明细表
字段: id(主键), order_id(关联orders.id), product_id(关联products.id), quantity(数量), unit_price(成交单价)
用途: 商品级销售分析, 计算某商品销售数量""",
        "columns": ["id", "order_id", "product_id", "quantity", "unit_price"],
    },
}


class AdaptiveSchemaRetriever:
    """四层自适应检索"""

    def __init__(self):
        self.embeddings = OpenAIEmbeddings(
            model="embedding-2",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
        )
        # ⚡ 关键：先初始化 table_names，加载分支也能用
        self.table_names = list(SCHEMA_DOCS.keys())
        self.bm25 = None
        self.fk_graph = None
        self.vectorstore = None
        self._load_or_build_index()

    def _load_or_build_index(self):
        os.makedirs(INDEX_DIR, exist_ok=True)
        bm25_path = os.path.join(INDEX_DIR, "bm25.pkl")
        fk_path = os.path.join(INDEX_DIR, "fk_graph.pkl")
        chroma_dir = os.path.join(INDEX_DIR, "chroma")

        if os.path.exists(bm25_path) and os.path.exists(fk_path) and os.path.exists(chroma_dir):
            try:
                with open(bm25_path, "rb") as f:
                    self.bm25 = pickle.load(f)
                with open(fk_path, "rb") as f:
                    self.fk_graph = pickle.load(f)
                self.vectorstore = Chroma(
                    persist_directory=chroma_dir,
                    embedding_function=self.embeddings,
                )
                print(f"✅ 四层索引已加载（{len(SCHEMA_DOCS)} 表）")
                return
            except Exception as e:
                print(f"⚠️ 加载索引失败，重建：{e}")

        self._build_index()
        with open(bm25_path, "wb") as f:
            pickle.dump(self.bm25, f)
        with open(fk_path, "wb") as f:
            pickle.dump(self.fk_graph, f)
        print(f"✅ 四层索引已构建（{len(SCHEMA_DOCS)} 表）")

    def _build_index(self):
        # 1. BM25
        corpus = []
        self.table_names = []
        for tbl, doc in SCHEMA_DOCS.items():
            tokens = list(doc["content"].lower())
            corpus.append(tokens)
            self.table_names.append(tbl)
        self.bm25 = BM25Okapi(corpus)

        # 2. 向量
        texts = [doc["content"] for doc in SCHEMA_DOCS.values()]
        metadatas = [{"table": tbl} for tbl in SCHEMA_DOCS.keys()]
        chroma_dir = os.path.join(INDEX_DIR, "chroma")
        self.vectorstore = Chroma.from_texts(
            texts=texts,
            embedding=self.embeddings,
            metadatas=metadatas,
            persist_directory=chroma_dir,
        )

        # 3. FK 图
        self._build_fk_graph()

    def _build_fk_graph(self):
        self.fk_graph = nx.DiGraph()
        for tbl in SCHEMA_DOCS.keys():
            self.fk_graph.add_node(tbl)

        # 用 pg_class + pg_attribute 精确查询（最可靠的写法）
        fk_sql = """
        SELECT
            src.relname AS source_table,
            tgt.relname AS target_table,
            sa.attname AS source_column,
            ta.attname AS target_column
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class tgt ON tgt.oid = c.confrelid
        JOIN pg_attribute sa
            ON sa.attrelid = c.conrelid AND sa.attnum = c.conkey[1]
        JOIN pg_attribute ta
            ON ta.attrelid = c.confrelid AND ta.attnum = c.confkey[1]
        WHERE c.contype = 'f'
        """
        try:
            with engine.connect() as conn:
                rows = conn.execute(text(fk_sql)).fetchall()

            print(f"🔍 [FK 调试] SQL 返回 {len(rows)} 行")
            for row in rows:
                print(f"    {row}")

            for row in rows:
                src_tbl, tgt_tbl, src_col, tgt_col = row
                if src_tbl in self.fk_graph and tgt_tbl in self.fk_graph:
                    self.fk_graph.add_edge(
                        src_tbl, tgt_tbl,
                        source_column=src_col,
                        target_column=tgt_col,
                    )
            print(f"✅ FK 关系图: {self.fk_graph.number_of_edges()} 条外键")
        except Exception as e:
            print(f"⚠️ FK 抽取失败，使用硬编码：{e}")
            # 硬编码兜底
            edges = [
                ("employees", "departments", "department_id", "id"),
                ("orders", "employees", "employee_id", "id"),
                ("orders", "regions", "region_id", "id"),
                ("products", "categories", "category_id", "id"),
                ("order_items", "orders", "order_id", "id"),
                ("order_items", "products", "product_id", "id"),
            ]
            for src, tgt, sc, tc in edges:
                self.fk_graph.add_edge(src, tgt,
                                       source_column=sc, target_column=tc)

    def retrieve(self, query: str, top_k: int = 8) -> str:
        print(f"🔍 [Schema 检索] query='{query[:40]}'")

        bm25_results = self._bm25_search(query, top_k=20)
        print(f"  L1 BM25: {bm25_results[:8]}")

        dense_results = self._dense_search(query, top_k=20)
        print(f"  L2 Dense: {dense_results[:8]}")

        fused = self._rrf_merge(bm25_results, dense_results)
        print(f"  L3 RRF: {fused[:top_k]}")

        expanded = self._expand_by_fk(fused[:top_k])
        print(f"  L4 FK扩展: {expanded}")

        lines = ["以下是可能相关的表结构：\n"]
        for tbl in expanded:
            if tbl in SCHEMA_DOCS:
                lines.append(SCHEMA_DOCS[tbl]["content"])
                lines.append("")
        return "\n".join(lines)

    def _bm25_search(self, query: str, top_k: int = 20) -> list:
        tokens = list(query.lower())
        scores = self.bm25.get_scores(tokens)
        indices = scores.argsort()[-top_k:][::-1]
        return [self.table_names[i] for i in indices if scores[i] > 0]

    def _dense_search(self, query: str, top_k: int = 20) -> list:
        results = self.vectorstore.similarity_search(query, k=top_k)
        return [r.metadata["table"] for r in results]

    def _rrf_merge(self, bm25_list: list, dense_list: list, k: int = 60) -> list:
        scores = {}
        for i, tbl in enumerate(bm25_list):
            scores[tbl] = scores.get(tbl, 0) + 1.0 / (k + i + 1)
        for i, tbl in enumerate(dense_list):
            scores[tbl] = scores.get(tbl, 0) + 1.0 / (k + i + 1)
        return [t for t, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)]

    def _expand_by_fk(self, tables: list) -> list:
        expanded = set(tables)
        for tbl in tables:
            if tbl not in self.fk_graph:
                continue
            for neighbor in self.fk_graph.successors(tbl):
                expanded.add(neighbor)
            for neighbor in self.fk_graph.predecessors(tbl):
                expanded.add(neighbor)
        return list(expanded)[:12]