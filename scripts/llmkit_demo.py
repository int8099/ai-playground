"""
llmkit 端到端演示
================================================================

用真实的 DeepSeek API 把 W1 做的客户端完整走一遍。
这个脚本同时充当「冒烟测试」—— 每次改动 client.py 之后跑一次，
五分钟内就能确认没把东西改坏。

六步：
    ① 启动自检          免费，但能拦住一整类静默失败
    ② 单次调用
    ③ 并发调用          对比不同 Semaphore 上限的耗时（Day 1 + Day 2a）
    ④ 流式输出          观察 TTFT（Day 4）
    ⑤ 静默失败防护      演示「HTTP 200 但内容被截断」如何被拦住（Day 4）
    ⑥ 统计与预算        成本台账 + 预算硬上限

【怎么跑】
    PyCharm：右键本文件 → Run 'llmkit_demo'
    命令行：  python scripts/llmkit_demo.py

【成本】
    约 25 次调用，大多是很短的任务。合计不到 ¥0.02。
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from llmkit import (  # noqa: E402  （放在 load_dotenv 之后是刻意的）
    BudgetExceededError,
    LLMClient,
    ModelMismatchError,
    TruncatedResponseError,
)


def banner(title: str) -> None:
    print(f"\n{'═' * 64}\n  {title}\n{'═' * 64}")


def thin() -> None:
    print("─" * 64)


# ══════════════════════════════════════════════════════════════
# ① 启动自检
# ══════════════════════════════════════════════════════════════
async def step1_verify(client: LLMClient) -> None:
    banner("① 启动自检 · 跟服务端核对模型名")

    print("""
这一步不消耗 token（GET /models 免费），但能拦住一整类静默失败：

    用过时的模型名 → 服务端不报错 → 悄悄换成别的模型 → 你的实验结论全错

所以真实项目里，客户端启动时应该先做一次这个检查。
""")
    thin()

    ids = await client.verify_models()
    print(f"  服务端可用模型：{ids}")
    print(f"  本客户端配置  ：{client.model}  ✅ 在列表里")

    # 故意用一个错误的名字，看看会不会被拦住
    print("\n  【反证】故意配一个过时的模型名：")
    try:
        bad = LLMClient(model="deepseek-v4-flash")
        await bad.verify_models()
        await bad.aclose()
        print("    ❌ 没拦住")
    except ModelMismatchError as exc:
        print(f"    ✅ 被拦住了：{str(exc).splitlines()[0]}")
        print("       如果我发起真实请求，这个名字【不会报错】——")
        print("       服务端会用 deepseek-flash 帮我服务，而我一直以为自己用的是别的模型。")


# ══════════════════════════════════════════════════════════════
# ② 单次调用
# ══════════════════════════════════════════════════════════════
async def step2_single(client: LLMClient) -> None:
    banner("② 单次调用")

    resp = await client.chat(
        "用一句话说明什么是 HTTP 404。",
        system="你是一个简洁的技术讲师，回答不超过 40 字。",
        max_tokens=512,
    )

    print(f"  正文        : {resp.content}")
    print(f"  finish      : {resp.finish_reason}")
    usage = resp.usage
    if usage:
        print(f"  token       : 输入 {usage.prompt_tokens} + 输出 {usage.completion_tokens}"
              f"（思考 {usage.reasoning_tokens}）")
    print(f"  单次成本    : ¥{client.stats.cost_cny:.6f}")
    thin()
    print("""
  📌 注意「思考 0」—— 因为 LLMClient 默认 disable_thinking=True。
     实验 04 实测：思考 token 能占到输出的 97%，而简单任务上
     它不产生任何用户可见价值。所以这里默认关掉，需要推理时再开。
""")


# ══════════════════════════════════════════════════════════════
# ③ 并发调用
# ══════════════════════════════════════════════════════════════
async def step3_concurrent() -> None:
    banner("③ 并发调用 · gather 与 Semaphore 的合作")

    print("""
Day 1 学了 gather（让任务同时开始等），
Day 2 学了 Semaphore（限制同时在飞的请求数）。
这里把两者放在一起，用【同一个任务集】跑两遍，只改闸门的宽度。

理论公式（Day 2 推过）：总耗时 ≈ ⌈任务数 / 并发上限⌉ × 单次耗时

  10 个任务，闸门 2 → ⌈10/2⌉ = 5 轮
  10 个任务，闸门 10 → ⌈10/10⌉ = 1 轮

⚠️ 但闸门开太大不是好事：服务端会限流你（429），
   你的重试率会上升，实际吞吐反而下降。这是要实测调优的。
""")

    prompts = [f"用一个词回答：{i} 的英文是几？" for i in range(1, 11)]
    # 换一个更干净的任务集，避免模型输出过长
    prompts = [f"只输出这一个数字，不要任何其他文字：{i * 7}" for i in range(1, 11)]

    results: dict[int, float] = {}

    for concurrency in (2, 10):
        thin()
        print(f"\n  ▓ 并发上限 = {concurrency}")

        client = LLMClient(max_concurrency=concurrency, base_delay=0.3)
        try:
            t0 = time.perf_counter()
            answers = await client.chat_many(prompts, max_tokens=512, fail_fast=False)
            elapsed = time.perf_counter() - t0

            ok = sum(1 for a in answers if a is not None)
            failed = len(answers) - ok
            results[concurrency] = elapsed

            print(f"    总耗时      : {elapsed:.2f} 秒")
            print(f"    成功 / 失败  : {ok} / {failed}")
            print(f"    重试次数    : {client.stats.retries}")
            print(f"    平均单次    : {elapsed / len(prompts):.2f} 秒（串行的话大概就是这个数 × 10）")
            sample = [a.content.strip()[:12] for a in answers[:5] if a]
            print(f"    前 5 个结果 : {sample}")
            if failed:
                for a in answers:
                    pass
        finally:
            await client.aclose()

    thin()
    print(f"\n  【对比】闸门 2 → {results.get(2, 0):.2f} 秒 ；闸门 10 → {results.get(10, 0):.2f} 秒")
    if results.get(2, 0) > results.get(10, 0):
        print(f"  快了 {results[2] / max(results[10], 1e-9):.1f} 倍 —— 和理论公式吻合。")
    print("""
  📌 注意 chat_many 的两个细节：

     1. 返回的顺序 = 输入的顺序，【不是】完成的顺序。
        asyncio.gather 保序，所以 answers[i] 一定对应 prompts[i]。

     2. fail_fast=False 时，失败的条目返回 None，其余照常完成。
        批量任务里通常更想要这个 —— 一条失败不该让另外 99 条白跑。
""")


# ══════════════════════════════════════════════════════════════
# ④ 流式输出
# ══════════════════════════════════════════════════════════════
async def step4_stream(client: LLMClient) -> None:
    banner("④ 流式输出 · 观察 TTFT")

    print("\n  实时输出：\n  ", end="", flush=True)

    t0 = time.perf_counter()
    first_at: float | None = None
    chars = 0

    async for piece in client.chat_stream(
        "用大约 80 字说明为什么指数退避要加随机抖动。",
        max_tokens=2048,
    ):
        if first_at is None:
            first_at = time.perf_counter() - t0
        chars += len(piece)
        print(piece, end="", flush=True)

    total = time.perf_counter() - t0
    print("\n")
    thin()
    print(f"  首个字符       : {first_at:.2f} 秒" if first_at else "  首个字符       : (无输出)")
    print(f"  总耗时         : {total:.2f} 秒")
    print(f"  字符数         : {chars}")
    thin()
    print("""
  📌 chat_stream 是【异步生成器】—— 所以调用方用 async for 消费。
     这种写法的好处：调用方可以随时 break，连接会被正确关闭，
     不会像回调式 API 那样留下一堆悬空的资源。
""")


# ══════════════════════════════════════════════════════════════
# ⑤ 静默失败防护
# ══════════════════════════════════════════════════════════════
async def step5_guard(client: LLMClient) -> None:
    banner("⑤ 静默失败防护 · 把 200 但坏掉的结果变成异常")

    print("""
这是 W1 最容易被忽略、但在真实项目里最要命的一件事。

服务端返回 HTTP 200，不代表你拿到了能用的东西。三种典型：
    · finish_reason = "length"  → 回答被截断
    · content 是空的            → 预算被思考吃光
    · 格式对但字段名不对        → 业务层问题，靠 Pydantic 拦

LLMClient 默认把前两种【转成异常抛出】，而不是让你在不知情的情况下
用一段残缺文本继续往下跑。
""")
    thin()

    # 统一变量：同一个问题、同样的 max_tokens，唯一的差别是 thinking 开关。
    # 这才是干净的对照实验 —— 一次只改一个变量。
    question = "用不超过 30 个字说明什么是 HTTP 404。"
    budget = 64

    # 场景 A：开着思考，预算被思考吃光
    print(f"\n  【场景 A】max_tokens={budget} + thinking=True（预算会被思考吃光）")
    try:
        await client.chat(question, thinking=True, max_tokens=budget)
        print("    ❌ 居然成功了（说明这次思考比较短，换个问题再试）")
    except TruncatedResponseError as exc:
        print("    ✅ 抛出 TruncatedResponseError")
        print(f"       {str(exc).splitlines()[0]}")
    print("""
       ⚠️ 注意：如果没有这个检查，这段代码会【静默返回一段不完整的内容】，
          然后在某个下游环节引发难以定位的 bug。
""")

    # 场景 B：同样的预算，关掉思考 —— 应该成功
    thin()
    print(f"\n  【场景 B】max_tokens={budget}（完全一样）+ thinking=False")
    try:
        resp = await client.chat(question, thinking=False, max_tokens=budget)
        print(f"    ✅ 成功：{resp.content.strip()}")
        print(f"       token：输出 {resp.usage.completion_tokens if resp.usage else '?'}"
              f"（思考 {resp.usage.reasoning_tokens if resp.usage else '?'}）")
        print(f"       finish_reason = {resp.finish_reason!r}")
        print("""
       → 同样的预算、同样的问题，关掉思考就能拿到完整答案。
         这个对比就是实验 04 那个结论在工程上的直接体现：

             思考 token 会【挤占】正文的预算。
             预算紧的时候，关掉思考是从「拿不到答案」到「拿到答案」的开关，
             不只是省钱的问题。
""")
    except Exception as exc:
        print(f"    {type(exc).__name__}: {str(exc).splitlines()[0]}")

    # 场景 C：确实想要截断的内容怎么办
    thin()
    print("\n  【场景 C】我就想要被截断的内容（比如做流式预览 / 分段生成）")
    try:
        resp = await client.chat(
            "用 100 字左右介绍一下 HTTP 协议。",   # 故意问一个注定写不完的
            thinking=False,
            max_tokens=24,          # 故意小到一定截断
            allow_truncated=True,   # ← 显式放行
        )
        print(f"    ✅ 拿到了不完整的内容：{resp.content.strip()!r}…")
        print(f"       finish_reason = {resp.finish_reason!r}（调用方自己判断要不要用）")
        print("       → 关键是【显式】：默认拦住，想要就明说，不能靠默认值蒙。")
    except Exception as exc:
        print(f"    {type(exc).__name__}: {str(exc).splitlines()[0]}")


# ══════════════════════════════════════════════════════════════
# ⑥ 统计与预算
# ══════════════════════════════════════════════════════════════
async def step6_stats(client: LLMClient) -> None:
    banner("⑥ 统计与预算")

    print("\n  【本次进程的统计】\n")
    client.print_stats()

    thin()
    print("""
  📌 预算硬上限的实现方式：

     LLMClient(monthly_budget_cny=100, already_spent_cny=<本月已花>)
         ↓
     每次发请求【之前】检查：already_spent + 本次进程花费 >= 上限 ?
         ↓ 是
     raise BudgetExceededError   ← 直接拒绝，而不是事后统计

     为什么要在【之前】检查？因为事后发现就晚了，钱已经花出去了。
     这道闸门对应 docs/budget.md 里承诺过的保护措施。
""")

    # 现场演示：预算设成 0，第一次调用就该被拒
    print("  【现场演示】把预算上限设成 ¥0.000001：")
    tiny_budget = LLMClient(monthly_budget_cny=0.000001)
    try:
        await tiny_budget.chat("你好", max_tokens=512)
        print("    ❌ 居然放行了")
    except BudgetExceededError as exc:
        print(f"    ✅ 被拦住：{str(exc).splitlines()[0]}")
    finally:
        await tiny_budget.aclose()


# ══════════════════════════════════════════════════════════════
async def main() -> None:
    banner("llmkit 端到端演示")

    async with LLMClient() as client:
        await step1_verify(client)
        await step2_single(client)
        await step3_concurrent()
        await step4_stream(client)
        await step5_guard(client)
        await step6_stats(client)

    banner("演示结束")
    print("""
  这个客户端里，每个能力都能对应到 W1 的某一天：

      chat_many 的 gather ................ Day 1  并发思维
      _sem（Semaphore 闸门）.............. Day 2a 限流
      _post_with_retry（full jitter）.... Day 2b 抗惊群
      models.py（Pydantic 校验）.......... Day 3  类型安全
      连接池 / 四段超时 / 错误分类 / SSE ... Day 4  真实 HTTP

  这些都是【拼起来】用的，不是各自孤立的技巧。
  下一步（W2）要做的，是把重试逻辑从 client 里抽成装饰器，
  再用 pytest + respx 给它补上不烧钱的测试。
""")


if __name__ == "__main__":
    asyncio.run(main())
