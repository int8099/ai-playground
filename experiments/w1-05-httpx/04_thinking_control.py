"""
实验 04 —— 思考模式的开关与成本控制
================================================================

【这个实验想搞清楚什么】
    DeepSeek V4 默认【开着思考模式】。这意味着：你问它一句话，
    它先在内部写一大段推理草稿（reasoning_content），然后才回答。

    推理 token 【也计费】。所以这个默认开启的开关，
    可能是你账单里最大的一笔隐形支出。

【这个实验为什么值得单独做】
    我在写实验 01 的时候发现：问「只回答两个字：收到」，
    它花了 51 个 token —— 其中 14 个是思考。
    更进一步测：让它写 200 字说明，给 400 个 token 的预算，
    结果 400 个 token 【全部被思考吃光，正文一个字都没输出】。

    也就是说，不控制这个开关，你可能付了钱却拿不到答案。
    这不是理论风险，是实测。

【四幕】
    第一幕：官方参数到底怎么用（含一个必踩的坑）
    第二幕：实测 —— 同一个问题，开/关思考的差别有多大
    第三幕：什么时候该开、什么时候该关
    第四幕：算一笔账

【怎么跑】
    PyCharm：右键本文件 → Run '04_thinking_control'
    命令行：  python experiments/w1-05-httpx/04_thinking_control.py

【成本】
    约 6 次真实调用，合计约 2000 token，不到 ¥0.01。

【官方文档依据】
    https://api-docs.deepseek.com/guides/thinking_mode
    核实日期：2026-10-11
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("DEFAULT_MODEL", "deepseek-flash")

CHAT_ENDPOINT = f"{BASE_URL}/chat/completions"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

# 参考单价（元 / 百万 token）—— 量级参考，真实扣费以控制台账单为准。
# 来源：docs/budget.md（核实日期 2026-10-09）
PRICE_IN = 1.1
PRICE_OUT = 4.3


def banner(title: str) -> None:
    print(f"\n{'═' * 62}\n  {title}\n{'═' * 62}")


def thin() -> None:
    print("─" * 62)


# ══════════════════════════════════════════════════════════════
# 第一幕：官方参数怎么用
# ══════════════════════════════════════════════════════════════
async def act1_parameters() -> None:
    banner("第一幕 · 官方参数：怎么开、怎么关、怎么调强度")

    print("""
【开关】thinking 字段（放在请求体顶层）

    {"thinking": {"type": "enabled"}}     ← 默认值，不开也是开
    {"thinking": {"type": "disabled"}}    ← 关掉推理，直接出答案

【强度】reasoning_effort 字段（也是顶层）

    {"reasoning_effort": "low"}    → 实际映射到 low
    {"reasoning_effort": "medium"} → 实际映射到 high
    {"reasoning_effort": "high"}   → 实际映射到 high   ← 默认
    {"reasoning_effort": "xhigh"}  → 实际映射到 high
    {"reasoning_effort": "max"}    → 实际映射到 max

    ⚠️ 注意这个映射表有个反直觉的地方：
       "low" 真的能降到 low，但 "medium" 和 "xhigh" 都被【吞掉】变成 high。
       也就是说除了 low 和 max，中间的档位是【无效的】——
       你写 medium 以为降低了强度，实际还是 high。

【⚠️ 必踩的坑：思考模式下这些参数全部无效】

    temperature / top_p / presence_penalty / frequency_penalty

    官方原话：「设置这些参数不会报错，但也不会生效。」

    这个坑阴险在哪：它【不报错】。
    你写了 temperature=0 以为能固定输出、方便做对比实验，
    结果每次结果还是不一样，你会怀疑是模型不稳定，
    而不会想到是参数压根没生效。

    → 想用 temperature，必须先思考模式关掉。
""")

    # 现场验证这个坑
    thin()
    print("\n【现场验证】用 temperature=0 连续问两次同样的简单问题\n")

    async def ask(extra: dict, label: str) -> str:
        body = {
            "model": MODEL,
            "messages": [{"role": "user", "content": "用一句话解释什么是幂等性。"}],
            "max_tokens": 600,
            "temperature": 0.0,          # 想固定输出
        }
        body.update(extra)
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as c:
            r = await c.post(CHAT_ENDPOINT, json=body, headers=HEADERS)
        d = r.json()
        m = d["choices"][0]["message"]
        content = (m.get("content") or "").strip()
        reasoning_len = len(m.get("reasoning_content") or "")
        print(f"  {label}")
        print(f"    思考 {reasoning_len} 字 / 正文 {len(content)} 字")
        print(f"    正文：{content[:100]}")
        return content

    c1 = await ask({}, "第 1 次（思考开启，temperature=0）")
    c2 = await ask({}, "第 2 次（思考开启，temperature=0）")
    print(f"\n  两次正文是否完全一样：{'一样' if c1 == c2 else '❌ 不一样'}")
    print("""
  → 思考开着的时候，temperature=0 也【保证不了确定性】，
    因为思考过程本身是带随机性的，而它又决定了正文。

  → 反过来，关掉思考之后 temperature 才真正生效。这是官方明确说明的。
""")


# ══════════════════════════════════════════════════════════════
# 第二幕：实测对比
# ══════════════════════════════════════════════════════════════
PROMPTS: list[tuple[str, str]] = [
    (
        "简单 · 改写",
        "把下面这句话改写得更简洁，只输出改写结果："
        "今天天气非常不错，我觉得我们可以一起出去散散步。",
    ),
    (
        "中等 · 容斥",
        "一个班 40 人，会游泳的有 25 人，会骑车的有 30 人。"
        "两种都会的最少有多少人？只给答案和一行理由。",
    ),
    (
        "较难 · 设计",
        "我要设计一个 API 重试策略，已知失败率约 60%、并发 20，"
        "要求不能出现惊群。给出关键参数取值和理由，150 字以内。",
    ),
]

MODES: list[tuple[str, dict]] = [
    ("思考开启（默认）", {}),
    ("思考关闭", {"thinking": {"type": "disabled"}}),
]


async def call(prompt: str, extra: dict) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 900,
    }
    body.update(extra)

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as c:
        r = await c.post(CHAT_ENDPOINT, json=body, headers=HEADERS)
    dt = time.perf_counter() - t0

    d = r.json()
    ch = d["choices"][0]
    m = ch["message"]
    u = d["usage"]
    content = m.get("content") or ""
    reasoning = m.get("reasoning_content") or ""

    return {
        "elapsed": dt,
        "finish": ch["finish_reason"],
        "content": content,
        "reasoning_len": len(reasoning),
        "pt": u["prompt_tokens"],
        "ct": u["completion_tokens"],
        "rt": u.get("completion_tokens_details", {}).get("reasoning_tokens", 0),
    }


async def act2_measure() -> list[dict]:
    banner("第二幕 · 实测：同一个问题，开与关差多少")

    print("""
下面 3 个问题难度递增，每个都跑「思考开启」和「思考关闭」两遍。
注意看三件事：耗时、输出 token、正文长度。
""")

    rows: list[dict] = []
    for prompt_name, prompt in PROMPTS:
        thin()
        print(f"\n▓ 问题：{prompt_name}")
        print(f"  {prompt[:60]}…" if len(prompt) > 60 else f"  {prompt}")

        for mode_name, extra in MODES:
            res = await call(prompt, extra)
            cost = (res["pt"] * PRICE_IN + res["ct"] * PRICE_OUT) / 1_000_000
            rows.append({"question": prompt_name, "mode": mode_name, "cost": cost, **res})

            print(f"\n  ├─ {mode_name}")
            print(f"  │    耗时          : {res['elapsed']:.2f} 秒")
            print(f"  │    finish_reason : {res['finish']}")
            print(f"  │    输出 token    : {res['ct']}（其中思考 {res['rt']}）")
            print(f"  │    正文 / 思考    : {len(res['content'])} 字 / {res['reasoning_len']} 字")
            print(f"  │    估算成本      : ¥{cost:.6f}")
            preview = res["content"].strip().replace("\n", " ")[:70]
            print(f"  │    正文预览      : {preview or '(空！)'}")
            if not res["content"].strip():
                print("  │    ⚠️ 正文是空的 —— 预算全被思考吃光了")

    return rows


# ══════════════════════════════════════════════════════════════
# 第三幕：汇总 + 决策
# ══════════════════════════════════════════════════════════════
def act3_summary(rows: list[dict]) -> None:
    banner("第三幕 · 汇总")

    print("\n  【逐题对比】\n")
    print(f"  {'问题':<12}{'模式':<14}{'耗时':>8}{'输出tok':>9}{'思考tok':>9}{'正文':>7}{'成本¥':>11}")
    print(f"  {'─' * 12}{'─' * 14}{'─' * 8}{'─' * 9}{'─' * 9}{'─' * 7}{'─' * 11}")
    for r in rows:
        print(f"  {r['question']:<12}{r['mode']:<14}{r['elapsed']:>7.2f}s"
              f"{r['ct']:>9}{r['rt']:>9}{len(r['content']):>7}{r['cost']:>11.6f}")

    print("\n  【按模式汇总】\n")
    for mode_name, _ in MODES:
        sub = [r for r in rows if r["mode"] == mode_name]
        if not sub:
            continue
        avg_t = sum(r["elapsed"] for r in sub) / len(sub)
        avg_rt = sum(r["rt"] for r in sub) / len(sub)
        tot_ct = sum(r["ct"] for r in sub)
        tot_cost = sum(r["cost"] for r in sub)
        empty = sum(1 for r in sub if not r["content"].strip())
        print(f"  {mode_name}")
        print(f"    平均耗时        : {avg_t:.2f} 秒")
        print(f"    输出 token 合计  : {tot_ct}（其中思考 {sum(r['rt'] for r in sub)}，"
              f"平均占比 {sum(r['rt'] for r in sub) / max(tot_ct, 1) * 100:.0f}%）")
        print(f"    正文为空的情况   : {empty} / {len(sub)} 次")
        print(f"    估算成本合计     : ¥{tot_cost:.6f}")
        print()

    print("""
【什么时候该开思考，什么时候该关】

  ┌──────────────────────────────────────────────────────────────┐
  │ 场景                          思考模式   为什么               │
  ├──────────────────────────────────────────────────────────────┤
  │ 简单改写 / 翻译 / 格式转换    关闭       答案显然，想了也白想  │
  │ 意图分类 / 打标签             关闭       判断只需要看关键词    │
  │ 批量数据清洗、批量标注        关闭       省钱是唯一目的        │
  │ 单元测试 / 冒烟测试           关闭       只验证链路通不通      │
  ├──────────────────────────────────────────────────────────────┤
  │ 数学 / 逻辑推理               开启       这正是思考的强项      │
  │ 多步代码调试                  开启       需要推演分支          │
  │ 复杂方案设计 / 架构比较       开启       需要权衡取舍          │
  │ 需要高准确率的关键判断        开启       宁可多花钱也别答错    │
  └──────────────────────────────────────────────────────────────┘

  📌 一句话判据：

        这个任务，一个熟练的人【需要停下来想一下】吗？
            不需要 → 关掉思考，省 80% 以上
            需要   → 开着，或者用 reasoning_effort=low 折中

  ⚠️ 还有第三种做法，比"一刀切"更好：先关着跑一遍。
     如果输出质量达标就保持关闭；不达标再开。
     把"思考"当成一个【可用性兜底】，而不是默认打开的奢侈品。
""")


# ══════════════════════════════════════════════════════════════
# 第四幕：算账
# ══════════════════════════════════════════════════════════════
def act4_cost(rows: list[dict]) -> None:
    banner("第四幕 · 算一笔账")

    on = [r for r in rows if r["mode"] == "思考开启（默认）"]
    off = [r for r in rows if r["mode"] == "思考关闭"]
    cost_on = sum(r["cost"] for r in on)
    cost_off = sum(r["cost"] for r in off)
    n = max(len(on), 1)

    print(f"""
  本次实验实测（{len(PROMPTS)} 个问题）：

      思考开启  合计 ¥{cost_on:.6f}   平均 ¥{cost_on / n:.6f} / 次
      思考关闭  合计 ¥{cost_off:.6f}   平均 ¥{cost_off / n:.6f} / 次
""")
    if cost_off > 0:
        print(f"      倍数     思考开启是关闭的 {cost_on / cost_off:.1f} 倍")
    print(f"""
  把这个倍数放到预算里看（参照 docs/budget.md 的学习强度假设：
  每天 200 次调用、平均输入 1500 token、平均输出 400 token）：

      · 全部开思考：输出侧可能从 400 token 涨到 1000+ token
      · 其中思考部分【不产生任何用户可见价值】，只有账单价值

  📌 三条可执行的省钱规则：

    1. 【默认关思考，按需打开】
       把 thinking=disabled 作为 client 的默认值，
       只有明确需要推理的任务才开。反过来做的话，
       你会为大量"根本不需要想"的请求付思考费。

    2. 【给 max_tokens 留够"思考预算"】
       开着思考时，max_tokens 必须 > 你预期的正文长度 + 思考开销。
       实测：要 200 字正文，给 400 token 都可能全被思考吃光。
       经验值：开着思考时，max_tokens 至少给正文预期的 3 倍。

    3. 【用低成本模型做链路验证】
       调通代码、验证协议、写回归测试时，用免费模型
       （智谱 glm-4.7-flash，见 budget.md）——
       这些场景你根本不需要 DeepSeek 的质量。

  ⚠️ 最后提醒：单价是会变的。
     上面的 ¥ 数字是【量级参考】，真实扣费一律以控制台账单为准。
     但"思考 token 占比很高"这个【结构性事实】不会变。
""")


# ══════════════════════════════════════════════════════════════
async def main() -> None:
    await act1_parameters()
    rows = await act2_measure()
    act3_summary(rows)
    act4_cost(rows)

    banner("一句话带走")
    print("""
  1. DeepSeek V4 默认【开着思考】，思考 token 也计费。
  2. 开关：thinking = {"type": "enabled" | "disabled"}
  3. 强度：reasoning_effort = "low" | "high" | "max"
     （medium / xhigh 会被吞成 high，只有 low 和 max 真正有效）
  4. 思考模式下 temperature / top_p 等采样参数【全部无效】，且不报错。
  5. 判据：这个任务需要"停下来想一下"吗？不需要就关掉。
  6. 开思考时 max_tokens 至少给正文预期的 3 倍，否则正文可能一个字都出不来。
""")


if __name__ == "__main__":
    asyncio.run(main())
