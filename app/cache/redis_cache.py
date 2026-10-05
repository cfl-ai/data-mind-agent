"""
Redis 语义缓存
- 相同问题 or 语义相似（>0.92）直接返回缓存
- 精确缓存优先（0 成本），miss 时走语义匹配
"""
import hashlib
import json
import re
import redis
import numpy as np
from langchain_openai import OpenAIEmbeddings

from app.config import REDIS_URL, ZAI_API_KEY


EMBEDDING_KEY_PREFIX = "datamind:emb:"
CACHE_KEY_PREFIX = "datamind:query:"


class QueryCache:
    def __init__(self, ttl: int = 3600, similarity_threshold: float = 0.75):
        self.r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self.ttl = ttl
        self.threshold = similarity_threshold
        self.embeddings = OpenAIEmbeddings(
            model="embedding-2",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
        )
    def invalidate_by_pattern(self, pattern: str):
        """
        按关键词失效缓存。
        比如数据更新后，清掉所有含"订单"或"销售"的缓存。
        """
        cleared = 0
        for key in self.r.scan_iter(f"{CACHE_KEY_PREFIX}*"):
            raw = self.r.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                if pattern in data.get("question", ""):
                    self.r.delete(key)
                    cleared += 1
            except Exception:
                pass
        print(f"🧹 [缓存] 按 '{pattern}' 失效 {cleared} 条")
    def _normalize(self, question: str) -> str:
        q = question.strip().lower()
        return re.sub(r"[？?！!。.,，、\s]+", "", q)

    def _exact_key(self, question: str) -> str:
        h = hashlib.md5(self._normalize(question).encode("utf-8")).hexdigest()[:16]
        return f"{CACHE_KEY_PREFIX}{h}"

    def _embed(self, text: str) -> list:
        return self.embeddings.embed_query(self._normalize(text))

    def _cosine(self, a: list, b: list) -> float:
        a, b = np.array(a), np.array(b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    def get(self, question: str) -> dict:
        """先精确查，再语义查"""
        # 1. 精确缓存
        exact_key = self._exact_key(question)
        try:
            raw = self.r.get(exact_key)
            if raw:
                print(f"⚡ [缓存] 精确命中")
                return json.loads(raw)
        except Exception as e:
            print(f"⚠️ [缓存] 精确查失败: {e}")

        # 2. 语义缓存
        try:
            q_emb = self._embed(question)
            # 拉取所有历史问题的 embedding
            best_score = 0.0
            best_key = None
            for emb_key in self.r.scan_iter(f"{EMBEDDING_KEY_PREFIX}*"):
                raw = self.r.get(emb_key)
                if not raw:
                    continue
                cached = json.loads(raw)
                score = self._cosine(q_emb, cached["embedding"])
                if score > best_score:
                    best_score = score
                    best_key = cached["cache_key"]

            if best_score >= self.threshold and best_key:
                raw = self.r.get(best_key)
                if raw:
                    print(f"⚡ [缓存] 语义命中 (相似度 {best_score:.3f})")
                    return json.loads(raw)
            elif best_score > 0:
                print(f"🔍 [缓存] 相似度 {best_score:.3f} < {self.threshold}，未命中")
        except Exception as e:
            print(f"⚠️ [缓存] 语义查失败: {e}")
        return None

    MAX_CACHE_ITEMS = 1000  # 最多缓存 1000 条

    def set(self, question: str, sql: str, rows: list, answer: str = ""):
        """写精确缓存 + 语义 embedding（带容量控制）"""
        exact_key = self._exact_key(question)
        data = {
            "question": question,
            "sql": sql,
            "rows": rows[:100],
            "answer": answer,
        }
        try:
            # ⚡ 容量检查：超过上限时，清最早的 20%
            current_count = sum(1 for _ in self.r.scan_iter(f"{CACHE_KEY_PREFIX}*"))
            if current_count >= self.MAX_CACHE_ITEMS:
                print(f"🧹 [缓存] 超上限({current_count})，清理最旧的 20%")
                self._evict_oldest(percent=0.2)

            self.r.setex(exact_key, self.ttl, json.dumps(data, ensure_ascii=False, default=str))

            emb = self._embed(question)
            emb_key = f"{EMBEDDING_KEY_PREFIX}{hashlib.md5(question.encode()).hexdigest()[:16]}"
            self.r.setex(emb_key, self.ttl, json.dumps({
                "cache_key": exact_key,
                "embedding": emb,
                "question": question,
            }, ensure_ascii=False))
            print(f" [缓存] 已写入（精确 + 语义）")
        except Exception as e:
            print(f"⚠️ [缓存] 写入失败: {e}")

    def _evict_oldest(self, percent: float = 0.2):
        """淘汰最旧的 N% 缓存（按 TTL 剩余时间）"""
        keys_with_ttl = []
        for key in self.r.scan_iter(f"{CACHE_KEY_PREFIX}*"):
            ttl = self.r.ttl(key)
            if ttl > 0:
                keys_with_ttl.append((key, ttl))

        # TTL 越接近 0 说明越旧，优先淘汰
        keys_with_ttl.sort(key=lambda x: x[1])
        to_delete = max(1, int(len(keys_with_ttl) * percent))
        for key, _ in keys_with_ttl[:to_delete]:
            self.r.delete(key)
        print(f"🧹 [缓存] 已淘汰 {to_delete} 条")

    def clear(self):
        for prefix in [CACHE_KEY_PREFIX, EMBEDDING_KEY_PREFIX]:
            for key in self.r.scan_iter(f"{prefix}*"):
                self.r.delete(key)
        print("🧹 [缓存] 已清空")


# 会话上下文（多轮对话）
class SessionStore:
    def __init__(self, ttl: int = 1800):
        self.r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        self.ttl = ttl

    def push(self, session_id: str, role: str, content: str):
        key = f"datamind:session:{session_id}"
        self.r.rpush(key, json.dumps({"role": role, "content": content}, ensure_ascii=False))
        self.r.ltrim(key, -10, -1)
        self.r.expire(key, self.ttl)

    def get_history(self, session_id: str) -> list:
        items = self.r.lrange(f"datamind:session:{session_id}", 0, -1)
        return [json.loads(i) for i in items]

    def clear(self, session_id: str):
        self.r.delete(f"datamind:session:{session_id}")