"""
实验 03 —— 流式输出（SSE）与 TTFT
================================================================

【这个实验想搞清楚什么】
    非流式调用要等模型把话说完你才拿到东西。
    流式（streaming）是「它说一个字，你收一个字」。

    这中间的差别，可以用一个数字概括：TTFT（Time To First Token）。

【为什么这个数字重要】
    用户不会在意「总共花了 4 秒」，用户在意的是
    「我点了按钮之后，多久看到东西开始动」。

    非流式：TTFT ≈ 总耗时 —— 就是干等 4 秒，屏幕一动不动
    流式  ：TTFT ≈ 0.6 秒 然后内容开始滚 —— 体感完全不同

    这就是为什么 ChatGPT 看起来"很快"，而有些 API 客户端看起来"很卡"，
    哪怕它们背后是同一个模型。

【另外还有一个必须知道的区别】
    非流式的 read 超时 = 整个响应必须在这个时间内传完
    流式的   read 超时 = 【两个数据包之间】的最大间隔

    后者宽松得多，对长回答更友好 —— 因为只要模型在持续吐字，
    就一直不会触发超时，哪怕它总共说了 5 分钟。

【怎么跑】
    PyCharm：右键本文件 → Run '03_streaming'
    命令行：  python experiments/w1-05-httpx/03_streaming.py

【成本】
    两次真实调用，合计约 300 token，不到 ¥0.001。
"""

from __future__ import annotations

import asyncio
import json
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

# 一个「答案比较长」的问题 —— 这样流式的优势才看得出来。
# 如果问「1+1 等于几」，两种方式都是零点几秒，比不出差别。
QUESTION = "用大约 150 字介绍一下 HTTP 和 HTTPS 的区别，分点说明。"


def banner(title: str) -> None:
    print(f"\n{'═' * 62}\n  {title}\n{'═' * 62}")


def thin() -> None:
    print("─" * 62)


def payload(stream: bool) -> dict:
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": QUESTION}],
        "max_tokens": 1200,
        "stream": stream,
    }


# ══════════════════════════════════════════════════════════════
# 第一幕：非流式 —— 干等
# ══════════════════════════════════════════════════════════════
async def act1_non_streaming() -> dict:
    banner("第一幕 · 非流式：一直等到全部说完")

    print("""
做法：一次 post，等 response 完整回来。
    下面这行 await 期间，程序什么都拿不到 —— 屏幕上不会出现任何东西。
""")
    thin()

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        t0 = time.perf_counter()
        r = await client.post(CHAT_ENDPOINT, json=payload(stream=False), headers=HEADERS)
        total = time.perf_counter() - t0

    d = r.json()
    content = d["choices"][0]["message"].get("content") or ""
    reasoning = d["choices"][0]["message"].get("reasoning_content") or ""
    usage = d["usage"]

    print(f"  状态码            : {r.status_code}")
    print(f"  总耗时            : {total:.2f} 秒")
    print(f"  用户看到第一字    : {total:.2f} 秒   ← 和非流式总耗时【相等】")
    print(f"  字数              : {len(content)}")
    print(f"  token             : 输入 {usage['prompt_tokens']} + 输出 {usage['completion_tokens']}")
    thin()
    print(f"\n  正文：\n{content}")
    if reasoning:
        print(f"\n  （思考过程 {len(reasoning)} 字，只在 reasoning_content 里，不展示给用户）")

    return {"total": total, "chars": len(content), "usage": usage}


# ══════════════════════════════════════════════════════════════
# 第二幕：流式 —— 边生成边收
# ══════════════════════════════════════════════════════════════
async def act2_streaming() -> dict:
    banner("第二幕 · 流式：收到一个字就吐一个字")

    print("""
做法：用 client.stream() 而不是 client.post()。
      stream() 返回的是一个【还没读完的响应】，
      然后 aiter_lines() 一行一行地读。

一个 SSE 数据包长这样（原始文本）：

      data: {"choices":[{"delta":{"content":"你"},"index":0}]}
      (空行)
      data: {"choices":[{"delta":{"content":"好"},"index":0}]}
      (空行)
      ...
      data: [DONE]

  注意几个关键点：
    · 每个包以 "data: " 开头（data 后面有一个空格）
    · 包与包之间用一个【空行】分隔
    · 流结束时发一个固定的哨兵值 [DONE]，而不是靠连接关闭来判断
    · delta 是「增量」的意思 —— 每个包只带新增的那一小段，不是全文
""")
    thin()

    first_output_at: float | None = None    # 第一个 delta（无论思考还是正文）
    first_content_at: float | None = None   # 第一段【正文】
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    content_chunks = 0
    reasoning_shown = 0
    gaps: list[float] = []          # 记录相邻两个包之间的间隔

    t_start = time.perf_counter()
    last_at = t_start

    print("\n  实时输出：", end="", flush=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        # ⚠️ stream() 必须放进 async with —— 它管理的是一个"半开"的连接，
        #    不关的话连接会一直占着，就是 Day 2 讲的连接泄漏。
        async with client.stream("POST", CHAT_ENDPOINT, json=payload(stream=True), headers=HEADERS) as resp:
            print(f"\n  （HTTP 状态码 {resp.status_code}，响应头已到，正文还没开始）\n")
            print("  ", end="", flush=True)

            # aiter_lines() 逐行给，空行也会给（就是那个 '' ）
            async for line in resp.aiter_lines():
                now = time.perf_counter()
                gaps.append(now - last_at)
                last_at = now

                # 只关心以 "data: " 开头的行；空行、注释行跳过
                if not line.startswith("data: "):
                    continue

                data = line[len("data: "):]
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if not chunk.get("choices"):
                    continue

                delta = chunk["choices"][0].get("delta") or {}

                # 推理内容（思考过程）在 reasoning_content，正文在 content。
                # ⚠️ 两者是【两条独立的流】—— 模型先流式吐出全部思考，
                #    再流式吐正文。所以「有没有输出」和「有没有答案」是两回事。
                if delta.get("reasoning_content"):
                    now_off = time.perf_counter() - t_start
                    if first_output_at is None:
                        first_output_at = now_off
                        print("\n  〔思考〕", end="", flush=True)
                    reasoning_parts.append(delta["reasoning_content"])
                    # 只实时显示前 60 字，避免刷屏；完整内容仍然累计
                    if reasoning_shown < 60:
                        piece = delta["reasoning_content"]
                        take = piece[: max(0, 60 - reasoning_shown)]
                        print(take, end="", flush=True)
                        reasoning_shown += len(take)
                        if reasoning_shown >= 60:
                            print("…", end="", flush=True)
                    continue

                if delta.get("content"):
                    now_off = time.perf_counter() - t_start
                    if first_output_at is None:
                        first_output_at = now_off
                    if first_content_at is None:
                        first_content_at = now_off
                        print("\n\n  〔正文〕", end="", flush=True)
                    content_parts.append(delta["content"])
                    content_chunks += 1
                    # flush=True 很重要 —— 不刷缓冲的话，
                    # 你会看到内容"攒一批一起出"，白费了流式的意义
                    print(delta["content"], end="", flush=True)

    total = time.perf_counter() - t_start
    content = "".join(content_parts)
    reasoning = "".join(reasoning_parts)

    print("\n")
    thin()
    fo = first_output_at if first_output_at is not None else float("nan")
    fc = first_content_at if first_content_at is not None else float("nan")
    print(f"  总耗时                : {total:.2f} 秒")
    print(f"  首个输出（含思考）     : {fo:.2f} 秒")
    print(f"  首个【正文】           : {fc:.2f} 秒   ← 用户真正看到答案的时间")
    print(f"  收到正文包数           : {content_chunks}")
    print(f"  正文长度              : {len(content)} 字")
    print(f"  思考长度              : {len(reasoning)} 字")

    if fo == fo and fc == fc and fc > fo + 0.05:
        print(f"\n  ⚠️ 注意上面两个数字的差距：{fc - fo:.2f} 秒。")
        print("     这段时间里模型在流式吐 reasoning_content —— 也就是「它在思考」。")
        print("     如果你只把 content 显示给用户，用户在这几秒里【依然看不到任何东西】，")
        print("     流式的优势就被思考过程吃掉了。这是推理模型上很反直觉的一点。")

    if gaps:
        # 掐头去尾：第一个间隔包含"等到首包"的时间
        middle = sorted(gaps[1:-1]) if len(gaps) > 3 else gaps
        print(f"\n  包间隔 中位数          : {middle[len(middle) // 2] * 1000:.1f} 毫秒")
        print(f"  包间隔 最大            : {max(gaps) * 1000:.1f} 毫秒")

    return {
        "total": total,
        "first_output": fo,
        "first_content": fc,
        "chars": len(content),
    }


# ══════════════════════════════════════════════════════════════
# 第三幕：流式下的超时语义
# ══════════════════════════════════════════════════════════════
async def act3_timeout_semantics(a: dict, b: dict) -> None:
    banner("第三幕 · 对比，以及流式下超时的语义变化")

    thin()
    print("\n  【非流式 vs 流式：用户等待感】\n")
    print(f"  {'':<12}{'总耗时':>10}{'首个输出':>12}{'首个正文':>12}{'字数':>8}")
    print(f"  {'─' * 12}{'─' * 10}{'─' * 12}{'─' * 12}{'─' * 8}")
    print(f"  {'非流式':<12}{a['total']:>9.2f}s{a['total']:>11.2f}s{a['total']:>11.2f}s{a['chars']:>8}")
    print(f"  {'流式':<12}{b['total']:>9.2f}s{b['first_output']:>11.2f}s{b['first_content']:>11.2f}s{b['chars']:>8}")

    print("""
  📌 怎么读这张表：

     · 「首个输出」= 流式下第一段【任何东西】到达的时间（含思考）
     · 「首个正文」= 第一段【答案】到达的时间
     · 非流式没有这个区别 —— 它的「首个输出」和「首个正文」都等于总耗时，
       因为在 response 完整回来之前，你手里什么都没有。

     · 关键对比是【非流式的总耗时】vs【流式的首个输出】：
       前者是用户干等的时间，后者是用户看到"有动静了"的时间。
       这两个数的差距，才是流式真正的价值。

     · ⚠️ 但如果模型要思考很久，「首个输出」和「首个正文」会拉开很大差距，
       这时候只显示正文，用户体感就和非流式差不多了。
       解决办法有两个（实验 04 会展开）：
           a) 把思考过程也显示出来（很多产品就是这么做的，用户反而觉得"它在认真想"）
           b) 关掉思考模式，让它直接出正文

【另一个反直觉的事实】

     流式的【总耗时往往比非流式还略长一点点】——
     因为每个包都要单独编解码、单独走一次网络。

     所以：如果你的下游消费者是【程序】而不是【人】
     （比如批量数据处理、后台任务），流式没有意义，反而更慢。

     用不用流式，取决于【谁在消费这个输出】。这是判断标准，不是"越新越好"。
""")
    thin()
    print("""
【流式下 read 超时的语义，完全变了】

  非流式：
      read=120  →  「整个响应必须在 120 秒内传完，否则超时」
      模型输出一篇 3000 字的长文可能要 3 分钟 → 直接超时，前功尽弃

  流式：
      read=120  →  「两个数据包之间最多能间隔 120 秒」
      只要模型在持续吐字，就一直不会超时 —— 哪怕总时长 5 分钟
      真正会触发超时的情况变成：
          · 模型卡住了，超过 120 秒一个包都不发（这才是真出问题了）
          · 网络断了

  ⭐ 所以流式不只是「体验更好」，它让【超时语义变得合理】了：
     超时终于是在描述「有没有在正常工作」，
     而不是「有没有在限时内完成」。

     这也是为什么长文档生成、Agent 长链条推理，
     几乎都跑在流式上。
""")


# ══════════════════════════════════════════════════════════════
async def main() -> None:
    a = await act1_non_streaming()
    b = await act2_streaming()
    await act3_timeout_semantics(a, b)

    banner("一句话带走")
    print("""
  1. 流式的价值是 TTFT（首字时间）小，不是总耗时短。
  2. SSE 格式：`data: {...}` + 空行分隔 + `[DONE]` 结束。
  3. delta 是增量，要自己拼。
  4. 流式让 read 超时从「整个响应限时」变成「包间隔限时」——
     这才是长文本和 Agent 场景必须用流式的真正原因。
  5. 用不用流式，取决于消费输出的是【人】还是【程序】。
""")


if __name__ == "__main__":
    asyncio.run(main())
