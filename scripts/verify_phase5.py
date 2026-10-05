"""阶段 5 验证脚本"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app.agents.graph import DataMindAgent


def main():
    print("=" * 60)
    print("🧪 DataMind · 阶段 5 验证")
    print("=" * 60)

    agent = DataMindAgent()

    test_questions = [
        "华东区的销售额是多少？",
        "最贵的商品是什么？",
        "每个区域的已完成订单金额？",
        "销量最高的商品是什么？",
        "总共有多少订单？",
        "你好",
        "GMV 怎么算",
    ]

    for q in test_questions:
        print(f"\n{'=' * 60}")
        print(f"👤 {q}")
        try:
            result = agent.ask(q)  # 不传 user_id，每次独立会话

            intent = result.get("intent", "")
            if intent in ("greeting", "unsupported", "explain_metric"):
                # 非查询意图，只打印回答
                print(f"💬 回复: {result['answer']}")
            else:
                print(f"📝 SQL: {result['sql']}")
                rows = result.get("rows", [])
                if not rows:
                    print(f"📊 结果: 空")
                elif len(rows) <= 10:
                    for r in rows:
                        print(f"    {r}")
                else:
                    print(f"📊 结果: 共 {len(rows)} 行，前 10 行：")
                    for r in rows[:10]:
                        print(f"    {r}")
                if result.get("error"):
                    print(f"❌ 错误: {result['error']}")
                else:
                    print(f"✅ 成功")
        except Exception as e:
            print(f"💥 异常: {type(e).__name__}: {e}")

    print(f"\n{'=' * 60}")
    print("🎉 阶段 5 验证完成")


if __name__ == "__main__":
    main()