"""
FastAPI 路由定义
"""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Optional, List

from app.agents.graph import DataMindAgent

router = APIRouter(prefix="/api")

# 全局 Agent 实例
agent = DataMindAgent()


# ============ 请求/响应模型 ============

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    user_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    sql: str = ""
    rows: List[dict] = []
    error: str = ""
    interrupted: bool = False
    thread_id: str = ""
    interrupt_info: Optional[dict] = None
    risk: str = ""


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
    reason: Optional[str] = ""


# ============ 路由 ============

@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest, x_user_id: Optional[str] = Header(None)):
    """查询接口"""
    user_id = req.user_id or x_user_id or "anonymous"
    try:
        result = agent.ask(req.question, user_id=user_id)
        # 处理 rows 里的 Decimal/date 类型
        rows = _serialize_rows(result.get("rows", []))
        return AskResponse(
            answer=result.get("answer", ""),
            sql=result.get("sql", ""),
            rows=rows,
            error=result.get("error", ""),
            interrupted=result.get("interrupted", False),
            thread_id=result.get("thread_id", ""),
            interrupt_info=result.get("interrupt_info"),
            risk=result.get("risk", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


@router.post("/approve", response_model=AskResponse)
def approve(req: ApproveRequest):
    """HITL 审批接口"""
    try:
        result = agent.resume(
            approval={"approved": req.approved, "reason": req.reason or ""},
            thread_id=req.thread_id,
        )
        rows = _serialize_rows(result.get("rows", []))
        return AskResponse(
            answer=result.get("answer", ""),
            sql=result.get("sql", ""),
            rows=rows,
            error=result.get("error", ""),
            interrupted=result.get("interrupted", False),
            thread_id=req.thread_id,
            risk="",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


def _serialize_rows(rows: list) -> list:
    """把 Decimal/date 转为字符串，便于 JSON 序列化"""
    from decimal import Decimal
    from datetime import date, datetime
    result = []
    for r in rows:
        item = {}
        for k, v in r.items():
            if isinstance(v, Decimal):
                item[k] = float(v)
            elif isinstance(v, (date, datetime)):
                item[k] = v.isoformat()
            else:
                item[k] = v
        result.append(item)
    return result