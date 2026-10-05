"""
构建 Schema 索引（BM25 + 向量 + FK 图）
首次运行或 Schema 变更后执行
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.sql.schema_retriever import AdaptiveSchemaRetriever

if __name__ == "__main__":
    print("🚀 构建 Schema 索引...")
    retriever = AdaptiveSchemaRetriever()
    print("✅ 索引构建完成")