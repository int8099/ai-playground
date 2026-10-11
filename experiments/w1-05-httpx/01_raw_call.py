"""
实验 01 —— 最小可跑的原始 httpx 请求
================================================================

【这个实验想搞清楚什么】
    在 Pydantic、在封装、在任何「优雅」的抽象之前，
    一次真实的大模型 API 调用，在 HTTP 层面到底长什么样？

【为什么要先看「原始」的】
    httpx 的 post() 其实只做两件事：
        把你给的 dict 变成 JSON 字节流 → 发出去 → 把回来的字节流变回 dict

    它不知道什么是「模型」，什么是「对话」，什么是「token」。
    所谓「OpenAI 兼容接口」，本质就是【一串约定好字段名的 JSON 交换】。

    把这一层看穿之后，所有 SDK / 框架都只是包装 ——
    这句话不是修辞，是真的。看完这个文件你就知道了。

【两幕】
    第一幕：一次真实调用，把原始请求和原始响应全部打印出来
    第二幕：连接池 —— 为什么 AsyncClient 必须复用而不是每次新建

【怎么跑】
    PyCharm：右键本文件 → Run '01_raw_call'
    命令行：  python experiments/w1-05-httpx/01_raw_call.py

【成本】
    第一幕约 51 token；第二幕用 /models 端点，不消耗 token。
    合计不到 ¥0.001，可以放心跑。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# ══════════════════════════════════════════════════════════════
# 1. 定位配置
# ══════════════════════════════════════════════════════════════
# 用 __file__ 而不是「当前工作目录」，这样无论在哪儿启动都能找到 .env。
# 这是刻意的设计：避免「命令行能跑、IDE 里跑不了」这类问题。
#
# __file__                  → .../experiments/w1-05-httpx/01_raw_call.py
# .parents[0]               → .../experiments/w1-05-httpx
# .parents[1]               → .../experiments
# .parents[2]               → .../ai-playground   ← 项目根
ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
MODEL = os.environ.get("DEFAULT_MODEL", "deepseek-flash")

CHAT_ENDPOINT = f"{BASE_URL}/chat/completions"
MODELS_ENDPOINT = f"{BASE_URL}/models"


# ══════════════════════════════════════════════════════════════
# 2. 小工具
# ══════════════════════════════════════════════════════════════
def mask(secret: str) -> str:
    """脱敏：只显示到「能分辨是哪把 key」为止。

    真实项目里，「日志把 key 打出来」是最常见的翻车方式之一 ——
    一张截图、一次 CI 日志外泄，key 就没了。
    所以不要显示「看起来打码了」的字符串（那样常常已经泄露了一半），
    只显示够你分辨身份的信息。
    """
    if not secret:
        return "(未设置)"
    return f"{secret[:3]}…  共 {len(secret)} 字符"


def banner(title: str) -> None:
    print(f"\n{'═' * 62}\n  {title}\n{'═' * 62}")


def thin() -> None:
    print("─" * 62)


# ══════════════════════════════════════════════════════════════
# 3. 第一幕：一次真实的原始调用
# ══════════════════════════════════════════════════════════════
async def act1_raw_call() -> None:
    banner("第一幕 · 一次真实的原始调用")

    print(f"BASE_URL  = {BASE_URL}")
    print(f"MODEL     = {MODEL}")
    print(f"KEY       = {mask(API_KEY)}")

    if not API_KEY:
        print("\n❌ .env 里没有 DEEPSEEK_API_KEY，先填上再跑。")
        return

    # ── HTTP 请求由四部分组成 ──────────────────────────────────
    #   ① 方法 + URL   POST https://api.deepseek.com/chat/completions
    #   ② 请求头        Authorization / Content-Type
    #   ③ 请求体        JSON（"OpenAI 兼容"约定的字段名全在这里）
    #   ④ （可选）查询串 / cookie 等
    #
    # 下面把①②③ 显式拆开 —— 只有显式写出来，你才知道框架替你做了什么。

    # ② 请求头
    headers = {
        # 这是认证：把 key 放在 Authorization 头里，格式固定是 "Bearer <key>"
        "Authorization": f"Bearer {API_KEY}",
        # 告诉服务器「我发的body是JSON」。很多服务端不检查这个头，
        # 但正确的客户端必须发 —— 规范如此。
        "Content-Type": "application/json",
    }

    # ③ 请求体：这就是「OpenAI 兼容」的全部秘密 —— 一个约定好字段名的 dict
    payload = {
        "model": MODEL,                       # 用哪个模型
        "messages": [                         # 对话历史，一个列表
            {"role": "user", "content": "只回答两个字：收到"}
        ],
        "max_tokens": 32,                     # 最多生成多少 token（花钱的上限闸门）
        # ⚠️ 这个 temperature 其实【没生效】—— 我一开始也不知道，查文档才明白：
        #    DeepSeek 默认开启「思考模式」，而思考模式下
        #    temperature / top_p / presence_penalty / frequency_penalty
        #    【全部被忽略】（不报错，静静地不生效）。
        #    所以想用 temperature 控制输出稳定性，必须先把思考关掉。
        #    实验 04 专门讲这个开关。
        "temperature": 0.0,
    }

    print(f"\n【我发出去的东西】POST {CHAT_ENDPOINT}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    thin()

    # ① 方法 + URL + 超时
    #
    # ⚠️ timeout 必须显式设！httpx 的默认是「全部 5 秒」。
    #    对普通 API 够用，但对大模型完全不够 —— 模型要想、要生成。
    #    正确姿势是「连接快、读取慢」：
    #        connect=10  连不上就赶紧失败，别让用户干等
    #        read=90     生成慢是正常的，给足时间
    #    后面实验 02 会专门拆解超时。
    timeout = httpx.Timeout(90.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        t0 = time.perf_counter()
        # ⚠️ json=payload（而不是 data=json.dumps(payload)）
        #    json= 会自动做两件事：序列化成 JSON 字节 + 设 Content-Type 头
        #    写 data= 就得自己 json.dumps 还得自己设头，容易漏
        response = await client.post(CHAT_ENDPOINT, json=payload, headers=headers)
        elapsed = time.perf_counter() - t0

    # ── HTTP 层的信息 ─────────────────────────────────────────
    print(f"\n【HTTP 层】")
    print(f"  状态码      = {response.status_code}")
    print(f"  耗时        = {elapsed:.2f} 秒")
    print(f"  Content-Type= {response.headers.get('content-type')}")
    print(f"  服务端       = {response.headers.get('server', '(未提供)')}")
    thin()

    # ── 应用层的信息 ──────────────────────────────────────────
    print(f"\n【应用层】原始响应体（未经任何加工）")
    print(json.dumps(response.json(), ensure_ascii=False, indent=2)[:1600])

    # ── 拆解给你看 ────────────────────────────────────────────
    if response.status_code == 200:
        data = response.json()
        msg = data["choices"][0]["message"]
        usage = data["usage"]

        banner("拆解")
        # 注意这里是「按路径取值」，路径就是上面那个 JSON 的结构。
        # Day 3 学的 Pydantic，做的事就是「把这种易错的取值变成有校验的对象」。
        print(f"  模型回答        : {msg['content']!r}")
        if msg.get("reasoning_content"):
            print(f"  它的思考过程    : {msg['reasoning_content']!r}")
        print(f"  结束原因        : {data['choices'][0]['finish_reason']}")
        thin()
        print(f"  输入 token      : {usage['prompt_tokens']}")
        print(f"  输出 token      : {usage['completion_tokens']}")
        print(f"    └ 其中思考    : {usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)}")
        print(f"  合计 token      : {usage['total_tokens']}")

        thin()
        print("  ⚠️ 注意上面：我只让它回答「收到」两个字，")
        print("     它却花了 51 个 token —— 因为【思考过程本身也计费】。")
        print("     这是推理模型和省钱策略的核心矛盾，后面 Q2/Q3 会反复遇到。")


# ══════════════════════════════════════════════════════════════
# 4. 第二幕：为什么 AsyncClient 必须复用
# ══════════════════════════════════════════════════════════════
async def act2_connection_reuse() -> None:
    banner("第二幕 · 连接池：为什么 AsyncClient 必须复用")

    print("""
每次新建一个 AsyncClient 并发请求，都要重走一遍：

    DNS 解析  →  TCP 三次握手  →  TLS 握手（含证书校验）

这一串在公网上通常要 100~300 毫秒。如果【每次请求都付这个钱】，
1000 次请求就白扔 100~300 秒。

AsyncClient 内部维护一个【连接池】：请求完不关连接，留在池里给下次用。
所以正确用法是「一个进程一个 client，长期活着」，而不是每次请求新建。

下面用 GET /models 做对比（这个端点不消耗 token）。
""")
    thin()

    # ── A：每次新建 client ────────────────────────────────────
    print("\n【A】每次请求都新建 client（3 次）")
    times_a: list[float] = []
    for i in range(3):
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as c:
            await c.get(MODELS_ENDPOINT, headers={"Authorization": f"Bearer {API_KEY}"})
        dt = time.perf_counter() - t0
        times_a.append(dt)
        print(f"  第 {i + 1} 次：{dt * 1000:7.1f} 毫秒")

    # ── B：复用一个 client ────────────────────────────────────
    print("\n【B】复用一个 client（3 次）")
    times_b: list[float] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as c:
        for i in range(3):
            t0 = time.perf_counter()
            await c.get(MODELS_ENDPOINT, headers={"Authorization": f"Bearer {API_KEY}"})
            dt = time.perf_counter() - t0
            times_b.append(dt)
            print(f"  第 {i + 1} 次：{dt * 1000:7.1f} 毫秒")

    # ── 对比 ──────────────────────────────────────────────────
    thin()
    print(f"\n  A 新建：第一次 {times_a[0] * 1000:.1f} ms，后续 {times_a[1] * 1000:.1f} / {times_a[2] * 1000:.1f} ms")
    print(f"  B 复用：第一次 {times_b[0] * 1000:.1f} ms，后续 {times_b[1] * 1000:.1f} / {times_b[2] * 1000:.1f} ms")

    # 只看「第二次及以后」—— 第一次两边都要建连，比的是「后续」
    avg_a = sum(times_a[1:]) / 2 * 1000
    avg_b = sum(times_b[1:]) / 2 * 1000
    print(f"\n  后续请求均值：A = {avg_a:.1f} ms   B = {avg_b:.1f} ms")
    if avg_b > 0:
        print(f"  倍数关系    ：B 比 A 快 {avg_a / avg_b:.1f} 倍")

    print("""
  注：具体数字会随网络波动，但【B 的后续请求明显更稳更快】是必然的 ——
      因为 A 每次都在重新握手，B 走的是池子里已经热好的连接。

  ⚠️ 这条规律对后面第 4 天要写的 client.py 是硬约束：
      AsyncClient 必须在整个生命周期里只建一次，用 async with 管起来。
      每次请求新建 client 是新手最常见的性能事故。
""")


# ══════════════════════════════════════════════════════════════
# 5. 入口
# ══════════════════════════════════════════════════════════════
async def main() -> None:
    await act1_raw_call()
    await act2_connection_reuse()

    banner("一句话带走")
    print("""
  1. 「大模型 API」就是【一个约定好字段名的 JSON 交换】，没有魔法。
  2. HTTP 200 只代表「服务器收到了并且处理了」，
     业务是否成功要看响应体里的字段 —— 这个坑实验 02 会展开。
  3. AsyncClient 要复用，不要每次新建。
""")


if __name__ == "__main__":
    asyncio.run(main())
