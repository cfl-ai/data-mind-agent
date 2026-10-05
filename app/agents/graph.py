"""
DataMind Agent v7 - 集成 HITL + RLS + 自校正 + 自然语言总结
"""
import os
import sys
import uuid
import json
from typing import TypedDict, Annotated
import operator

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE_DIR, ".env"))

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

from app.config import ZAI_API_KEY
from app.sql.intent_extractor import IntentExtractor
from app.sql.compiler import DeterministicCompiler, CompileError
from app.sql.validator import SQLValidator
from app.sql.executor import SQLExecutor, format_result
from app.sql.risk_assessor import RiskAssessor
from app.rls import inject_region_filter
from app.agents.router import (
    IntentRouter, greeting_reply, unsupported_reply, metric_reply
)
from app.agents.correction import CorrectionAgent
from app.provenance.chain import ProvenanceChain
from app.provenance.lineage import SQLLineageTracker


class AgentState(TypedDict, total=False):
    messages: Annotated[list, operator.add]
    user_id: str
    question: str
    intent: str
    query_intent: dict
    sql: str
    params: dict
    final_sql: str
    rows: list
    error: str
    error_type: str
    chain: dict
    risk: str
    risk_reason: str
    approved: bool
    retry_count: int


def _ser_value(v):
    """序列化 Decimal / date"""
    from decimal import Decimal
    from datetime import date, datetime
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


class DataMindAgent:
    def __init__(self):
        self.router = IntentRouter()
        self.extractor = IntentExtractor()
        self.compiler = DeterministicCompiler()
        self.validator = SQLValidator()
        self.executor = SQLExecutor()
        self.risk = RiskAssessor()
        self.correction = CorrectionAgent()
        self.lineage = SQLLineageTracker()
        self.checkpointer = MemorySaver()

        # LLM 用于自然语言总结
        self.llm = ChatOpenAI(
            model="glm-4-flash",
            api_key=ZAI_API_KEY,
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            temperature=0.3,
        )

        self.graph = self._build_graph()

    # ============================================================
    # 自然语言总结
    # ============================================================
    def _natural_summary(self, question: str, sql: str, rows: list) -> str:
        """用 LLM 把查询结果转成自然语言"""
        rows_ser = [{k: _ser_value(v) for k, v in r.items()} for r in rows[:10]]
        rows_str = json.dumps(rows_ser, ensure_ascii=False, indent=2)

        prompt = f"""用户问题：{question}

查询结果（JSON）：
{rows_str}

请用一句简洁的中文回答用户问题。

【要求】
1. 直接给结论，例如"华东区已完成订单的销售额为 1,012,924 元"
2. 有数字时用千分位分隔（1,012,924）
3. 多行结果时用"分别为"或"依次是"列出
4. 不要重复问题，不要说"根据查询结果"
5. 不超过 60 个字

只输出回答，不要任何其他文字。"""

        try:
            reply = self.llm.invoke([HumanMessage(content=prompt)]).content.strip()
            return reply if reply else format_result(rows)
        except Exception as e:
            print(f"⚠️ 自然语言总结失败：{e}")
            return format_result(rows)

    # ============================================================
    # 构建 LangGraph
    # ============================================================
    def _build_graph(self):
        workflow = StateGraph(AgentState)

        # ============ 节点 1：意图路由 ============
        def route_node(state: AgentState):
            return {"intent": self.router.route(state.get("question", ""))}

        # ============ 节点 2：QueryIntent 提取 ============
        def extract_intent_node(state: AgentState):
            try:
                qi = self.extractor.extract(state.get("question", ""))
                return {"query_intent": qi.model_dump()}
            except Exception as e:
                return {"error": f"意图提取失败：{type(e).__name__}: {e}",
                        "error_type": "extract"}

        # ============ 节点 3：编译 ============
        def compile_node(state: AgentState):
            if state.get("error"):
                return {}
            from app.sql.query_intent import QueryIntent
            try:
                qi = QueryIntent(**state.get("query_intent", {}))
                result = self.compiler.compile(qi)
                return {"sql": result["sql"], "params": result["params"]}
            except CompileError as e:
                return {"error": f"编译失败：{e}", "error_type": "compile"}
            except Exception as e:
                return {"error": f"编译异常：{type(e).__name__}: {e}",
                        "error_type": "compile"}

        # ============ 节点 4：安全校验 ============
        def validate_node(state: AgentState):
            if state.get("error"):
                return {}
            is_safe, result = self.validator.validate(state.get("sql", ""))
            if not is_safe:
                return {"error": f"安全拦截：{result}", "error_type": "validate"}
            return {"final_sql": result}

        # ============ 节点 5：风险评级 ============
        def assess_risk_node(state: AgentState):
            if state.get("error"):
                return {}
            user_role = self.risk.get_user_role(state.get("user_id", ""))
            assessment = self.risk.assess(
                state.get("final_sql", ""),
                state.get("query_intent", {}),
                user_role,
            )
            print(f"🎯 [风险评级] {assessment['risk']} - {assessment['reason']}")
            if assessment["risk"] == "forbidden":
                return {"error": f"操作被拒绝：{assessment['reason']}",
                        "error_type": "forbidden"}
            return {
                "risk": assessment["risk"],
                "risk_reason": assessment["reason"],
            }

        # ============ 节点 6：HITL 挂起 ============
        def hitl_gate_node(state: AgentState):
            user_id = state.get("user_id", "anon")
            print(f"⏸️  [HITL] SQL 挂起等待审批")
            approval = interrupt({
                "action": "sql_approval",
                "sql": state.get("final_sql", ""),
                "params": state.get("params", {}),
                "risk_reason": state.get("risk_reason", ""),
                "user_id": user_id,
            })
            print(f"🔄 [HITL] 收到审批结果：{approval}")

            if approval.get("approved"):
                return {"approved": True}
            return {
                "approved": False,
                "error": f"审批未通过：{approval.get('reason', '用户拒绝')}",
                "error_type": "hitl_rejected",
            }

        # ============ 节点 7：执行（带 RLS） ============
        def execute_node(state: AgentState):
            if state.get("error"):
                return {}

            user_role = self.risk.get_user_role(state.get("user_id", ""))
            accessible = self.risk.get_accessible_regions(user_role)
            final_sql = state.get("final_sql", "")

            if accessible:
                new_sql = inject_region_filter(final_sql, accessible)
                if new_sql != final_sql:
                    print(f"🔒 [RLS] 已注入区域过滤：{accessible}")
                final_sql = new_sql

            ok, rows = self.executor.execute(final_sql, state.get("params", {}))
            if not ok:
                return {
                    "error": f"执行失败：{rows}",
                    "error_type": "execute",
                    "final_sql": final_sql,
                }
            return {"rows": rows, "final_sql": final_sql}

        # ============ 节点 8：自校正 ============
        def correct_node(state: AgentState):
            retry = state.get("retry_count", 0) + 1
            print(f"🔧 [自校正] 第 {retry} 次重试")

            sql = state.get("final_sql") or state.get("sql", "")
            params = state.get("params", {}) or {}
            error = state.get("error", "")

            if not sql:
                return {"error": "SQL 丢失，无法修正", "error_type": "correct"}

            new_sql = self.correction.correct(sql, params, error)
            return {
                "final_sql": new_sql,
                "error": "",
                "error_type": "",
                "retry_count": retry,
            }

        # ============ 节点 9：总结 + 溯源 ============
        def summarize_node(state: AgentState):
            intent = state.get("intent", "")

            if intent == "greeting":
                return {"messages": [AIMessage(content=greeting_reply())]}
            if intent == "unsupported":
                return {"messages": [AIMessage(content=unsupported_reply())]}
            if intent == "explain_metric":
                return {"messages": [AIMessage(content=metric_reply(state.get("question", "")))]}

            if state.get("error"):
                return {"messages": [AIMessage(content=f"抱歉，{state['error']}")]}

            rows = state.get("rows", [])
            if not rows:
                return {"messages": [AIMessage(content="查询结果为空。")]}

            # 用 LLM 生成自然语言总结
            answer = self._natural_summary(
                question=state.get("question", ""),
                sql=state.get("final_sql", ""),
                rows=rows,
            )

            sql = state.get("final_sql", "")
            lineage = self.lineage.extract(sql) if sql else {"source_tables": [], "column_lineage": []}
            chain = ProvenanceChain(session_id=state.get("user_id", "anon"))
            chain.record("sql", {"sql": sql})
            chain.record("execution", {"row_count": len(rows)})
            chain.record("lineage", lineage)

            return {"messages": [AIMessage(content=answer)], "chain": chain.to_dict()}

        # ============ 注册节点 ============
        workflow.add_node("route", route_node)
        workflow.add_node("extract_intent", extract_intent_node)
        workflow.add_node("compile", compile_node)
        workflow.add_node("validate", validate_node)
        workflow.add_node("assess_risk", assess_risk_node)
        workflow.add_node("hitl_gate", hitl_gate_node)
        workflow.add_node("execute", execute_node)
        workflow.add_node("correct", correct_node)
        workflow.add_node("summarize", summarize_node)

        workflow.set_entry_point("route")

        workflow.add_conditional_edges(
            "route",
            lambda s: s.get("intent", "query_data"),
            {
                "greeting": "summarize",
                "unsupported": "summarize",
                "explain_metric": "summarize",
                "query_data": "extract_intent",
            }
        )

        workflow.add_edge("extract_intent", "compile")
        workflow.add_edge("compile", "validate")
        workflow.add_edge("validate", "assess_risk")

        workflow.add_conditional_edges(
            "assess_risk",
            lambda s: "hitl_gate" if s.get("risk") == "high" and not s.get("error")
                      else ("summarize" if s.get("error") else "execute"),
            {
                "hitl_gate": "hitl_gate",
                "execute": "execute",
                "summarize": "summarize",
            }
        )

        workflow.add_conditional_edges(
            "hitl_gate",
            lambda s: "execute" if s.get("approved") else "summarize",
            {"execute": "execute", "summarize": "summarize"}
        )

        workflow.add_conditional_edges(
            "execute",
            lambda s: (
                "summarize" if not s.get("error")
                else (
                    "correct"
                    if s.get("error_type") == "execute" and s.get("retry_count", 0) < 3
                    else "summarize"
                )
            ),
            {"summarize": "summarize", "correct": "correct"}
        )

        workflow.add_edge("correct", "execute")
        workflow.add_edge("summarize", END)

        return workflow.compile(checkpointer=self.checkpointer)

    # ============================================================
    # 对外接口
    # ============================================================
    def ask(self, question: str, user_id: str = None) -> dict:
        if user_id:
            session_id = user_id
        else:
            session_id = f"anon_{uuid.uuid4().hex[:8]}"

        config = {"configurable": {"thread_id": session_id}}
        result = self.graph.invoke(
            {
                "question": question,
                "user_id": session_id,
                "messages": [HumanMessage(content=question)],
                "retry_count": 0,
            },
            config=config,
        )

        snapshot = self.graph.get_state(config)
        if snapshot.next:
            interrupt_info = None
            for task in snapshot.tasks:
                if hasattr(task, "interrupts") and task.interrupts:
                    interrupt_info = task.interrupts[0].value
                    break

            return {
                "interrupted": True,
                "thread_id": session_id,
                "interrupt_info": interrupt_info,
                "answer": "⏸️ 该操作需要人工审批，已挂起。",
                "sql": result.get("final_sql", ""),
                "rows": [],
                "error": "",
                "chain": {},
                "intent": result.get("intent", ""),
                "risk": result.get("risk", ""),
            }

        intent = result.get("intent", "")
        if intent in ("greeting", "unsupported", "explain_metric"):
            return {
                "interrupted": False,
                "answer": result.get("messages", [{}])[-1].content if result.get("messages") else "",
                "sql": "", "rows": [], "error": "", "chain": {}, "intent": intent,
            }

        return {
            "interrupted": False,
            "answer": result.get("messages", [{}])[-1].content if result.get("messages") else "",
            "sql": result.get("final_sql", ""),
            "rows": result.get("rows", []),
            "error": result.get("error", ""),
            "chain": result.get("chain", {}),
            "intent": intent,
            "risk": result.get("risk", ""),
        }

    def resume(self, approval: dict, thread_id: str) -> dict:
        config = {"configurable": {"thread_id": thread_id}}
        result = self.graph.invoke(Command(resume=approval), config=config)

        snapshot = self.graph.get_state(config)
        if snapshot.next:
            return {
                "interrupted": True,
                "answer": "⏸️ 仍在等待审批。",
                "rows": [],
            }

        return {
            "interrupted": False,
            "answer": result.get("messages", [{}])[-1].content if result.get("messages") else "",
            "sql": result.get("final_sql", ""),
            "rows": result.get("rows", []),
            "error": result.get("error", ""),
        }