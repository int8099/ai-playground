"""
实验 02 —— 超时配置与错误分类
================================================================

【这个实验想搞清楚什么】
    网络请求会以哪些方式失败？每一种该不该重试？

【为什么要单独搞这个】
    Day 2 你学过「指数退避 + 抖动」来抗惊群。但那只回答了
    「失败之后等多久再试」—— 没回答【什么失败才该重试】。

    这是两个完全独立的问题，而且第二个更重要：
        盲目重试 = 把不可恢复的错误重试三遍 = 白烧三倍的钱 + 慢三倍

    尤其对大模型 API：【POST 请求默认不是幂等的】。
    你以为在"重试"，实际可能是在"重复下单"。

【四幕】
    第一幕：超时的四个参数，为什么默认的 5 秒对 LLM 是灾难
    第二幕：亲手制造 6 种失败，看清每种长什么样
    第三幕：可重试 / 不可重试 判断表
    第四幕：最危险的失败 —— HTTP 200，但结果是坏的（静默失败）

【怎么跑】
    PyCharm：右键本文件 → Run '02_timeout_errors'
    命令行：  python experiments/w1-05-httpx/02_timeout_errors.py

【成本】
    第二幕的失败请求绝大多数不消耗 token；第四幕两次真实生成。
    合计约 100 token，不到 ¥0.001。

【实测环境备注】
    本机存在 HTTP 代理（环境变量 HTTP_PROXY / HTTPS_PROXY），
    httpx 默认会自动读取它。这会影响「连不上时会抛什么异常」——
    第二幕的场景 6 专门演示这件事。
    如果你的机器没有代理，那个场景会走另一条分支，属于正常现象。
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

# 一台用于演示「连不上」的地址。
# 192.0.2.0/24 是 RFC 5737 保留给文档用的 TEST-NET-1 网段，
# 【保证不可路由】—— 包发出去必然石沉大海，正好用来触发 ConnectTimeout。
UNREACHABLE = "https://192.0.2.1/chat/completions"

# 一个保证解析不出来的域名（.invalid 是 RFC 2606 保留 TLD）
BAD_DOMAIN = "https://no-such-host-xyz-123.invalid/chat/completions"

HAS_PROXY = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY"))


def banner(title: str) -> None:
    print(f"\n{'═' * 62}\n  {title}\n{'═' * 62}")


def thin() -> None:
    print("─" * 62)


# ══════════════════════════════════════════════════════════════
# 异常 → 人话
# ══════════════════════════════════════════════════════════════
# 状态码 → 处置。第二幕和第三幕共用。
RETRY_BY_STATUS: dict[int, str] = {
    400: "❌ 不重试 —— 请求本身有问题（参数错 / 模型名错）",
    401: "❌ 不重试 —— 认证失败，重试只会再被拒一次",
    402: "❌ 不重试 —— 余额不足",
    403: "❌ 不重试 —— 没权限",
    404: "❌ 不重试 —— 端点不存在",
    422: "❌ 不重试 —— 参数校验失败",
    429: "✅ 重试 —— 限流了，等一会儿再来（优先看 Retry-After 响应头）",
    500: "✅ 重试 —— 服务端内部错误",
    502: "✅ 重试 —— 网关坏了",
    503: "✅ 重试 —— 服务暂时不可用",
    504: "✅ 重试 —— 网关超时",
}


def describe(exc: BaseException) -> tuple[str, str]:
    """把异常翻译成「人话 + 该不该重试」。

    ⚠️ 判断顺序必须【从具体到宽泛】：
       ConnectTimeout 继承自 TimeoutException，TimeoutException 又继承自 TransportError。
       如果先判 TransportError，后面所有细分类都永远走不到。
       这是 isinstance 链最常见的 bug。
    """
    # —— 超时家族（先判，因为最容易被子类吃掉）——
    if isinstance(exc, httpx.ConnectTimeout):
        return ("ConnectTimeout（连接超时）", "✅ 可重试 —— 对方没接客，稍后再来")
    if isinstance(exc, httpx.ReadTimeout):
        return ("ReadTimeout（读取超时）", "⚠️ 谨慎重试 —— 可能已产生费用，见第三幕")
    if isinstance(exc, httpx.WriteTimeout):
        return ("WriteTimeout（发送超时）", "✅ 可重试 —— 请求没发完整")
    if isinstance(exc, httpx.PoolTimeout):
        return ("PoolTimeout（连接池排队超时）", "✅ 可重试 —— 说明你并发开太大了")

    # —— 连接家族 ——
    if isinstance(exc, httpx.ProxyError):
        return ("ProxyError（代理出错）", "❌ 不重试 —— 先检查代理配置，重试没用")
    if isinstance(exc, httpx.ConnectError):
        return ("ConnectError（连不上主机）", "✅ 可重试 —— DNS 失败 / 目标端口不通")

    # —— 传输中断 ——
    if isinstance(exc, httpx.ReadError):
        return ("ReadError（读取中断）", "❌ 不要重试 —— 请求可能已被处理")
    if isinstance(exc, httpx.RemoteProtocolError):
        return ("RemoteProtocolError（对方协议异常）", "✅ 可重试 —— 常见于服务端中途掉线")

    # —— 业务层：请求成功但状态码不对 ——
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return (f"HTTPStatusError（状态码 {code}）", RETRY_BY_STATUS.get(code, "❌ 不重试"))

    # —— 兜底 ——
    if isinstance(exc, httpx.RequestError):
        return (f"RequestError 其他（{type(exc).__name__}）", "❓ 保守起见不重试")
    return (f"{type(exc).__name__}", "❓ 未知，不重试")


HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def chat_payload(model: str = MODEL, content: str = "hi", max_tokens: int = 4) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens}


async def show_failure(label: str, coro_factory, expect: str) -> None:
    """跑一个注定失败的请求，并把结果翻译好打出来。"""
    thin()
    print(f"\n【{label}】\n  预期：{expect}")
    try:
        await coro_factory()
        print("  → ⚠️ 居然成功了，说明这个场景在你的环境下没复现（不一定是你写错了）")
    except httpx.HTTPStatusError as exc:
        name, advice = describe(exc)
        print(f"  → 捕获：{name}")
        print(f"  → 服务端原话：{exc.response.text[:260]}")
        print(f"  → 该怎么办：{advice}")
    except httpx.RequestError as exc:
        name, advice = describe(exc)
        print(f"  → 捕获：{name}")
        print(f"  → 原始信息：{str(exc)[:120] or '(空)'}")
        print(f"  → 该怎么办：{advice}")


# ══════════════════════════════════════════════════════════════
# 第一幕：超时的四个参数
# ══════════════════════════════════════════════════════════════
async def act1_timeout_anatomy() -> None:
    banner("第一幕 · 超时的四个参数")

    print("""
很多人以为「超时」就是一个数字。不是 —— 一次 HTTP 请求有四个阶段，
每个阶段都可能卡住，所以 httpx 给了四个独立的旋钮：

    ┌──────────────────────────────────────────────────────────┐
    │  connect   建立 TCP 连接（含 DNS + TLS 握手）要多久       │
    │  write     把请求体（你那段 JSON）发完要多久              │
    │  read      等服务器【把响应还给你】要多久  ← LLM 的瓶颈   │
    │  pool      在连接池里排队等一个空闲连接要多久             │
    └──────────────────────────────────────────────────────────┘
""")
    thin()
    print("\n【httpx 的默认值】")
    t = httpx.Timeout(5.0)
    print(f"  httpx.Timeout(5.0)  →  connect={t.connect}  read={t.read}  write={t.write}  pool={t.pool}")
    print("\n  ⚠️ 四个阶段全部 5 秒。对普通 REST API 够了，对大模型是灾难：")
    print("     模型要『先思考、再逐字生成』，一个稍长的回答轻松超过 5 秒。")
    thin()

    t_llm = httpx.Timeout(120.0, connect=10.0)
    print("\n【LLM 场景该用的配置】httpx.Timeout(120.0, connect=10.0)")
    print(f"    →  connect={t_llm.connect}  read={t_llm.read}  write={t_llm.write}  pool={t_llm.pool}")
    print("""
  怎么读这行：
    · connect=10  —— 连不上就赶紧失败。等 10 秒还没连上，大概率是网络问题，
                     再等也没意义，不如早报错、早重试。
    · read=120    —— 生成慢是【正常现象】，给足耐心。

  ⚠️ read 的含义容易误解：它是「两个数据包之间的最大间隔」，
     不是「整个响应必须在 120 秒内传完」。
     流式输出时这个区别特别关键（实验 03 会看到）。

【关于超时的两条铁律】

  ① 永远不要写 timeout=None
     那等于「永不超时」。请求会一直挂着，把并发额度全吃光，
     程序看起来"卡死"，实际是 100 个请求都在无限等。
     要「不限时」必须是有意识的决策，不能是默认行为。

  ② 超时值要【分层】，不要一个数字走天下
     连接快、读取慢 —— 它们对应完全不同的东西：
     一个问"网络通不通"，一个问"对方算得快不快"。
""")

    thin()
    print("\n【⚠️ httpx 0.28 的行为变更（实测会踩）】")
    print("  httpx.Timeout()   ← 不传参数，0.27 及以前合法")
    try:
        httpx.Timeout()  # type: ignore[call-arg]
    except ValueError as exc:
        print(f"  在 0.28 直接报错：ValueError: {exc}")
    print("\n  正确写法：要么给默认值 httpx.Timeout(5.0)，要么四个参数全给。")


# ══════════════════════════════════════════════════════════════
# 第二幕：亲手制造失败
# ══════════════════════════════════════════════════════════════
async def act2_manufacture_errors() -> None:
    banner("第二幕 · 亲手制造 6 种失败")

    print("""
看的时候注意一件事：httpx 把失败分成了【完全不同的两大族】。

    ┌────────────────────┬──────────────────────────────────────────┐
    │ HTTPStatusError    │ 请求成功到达并被处理了，但状态码是 4xx/5xx │
    │ RequestError 家族  │ 请求【根本没到达】或【没等到响应】         │
    └────────────────────┴──────────────────────────────────────────┘

这个区别是第三幕判断「该不该重试」的全部依据。
""")

    # 场景 1：缺 key
    async def s1():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as c:
            r = await c.post(CHAT_ENDPOINT, json=chat_payload(), headers={"Content-Type": "application/json"})
            r.raise_for_status()

    await show_failure("场景 1 · 忘了带 API Key", s1, "401 —— 服务器认不出你是谁")

    # 场景 2：完全瞎写的模型名
    async def s2():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as c:
            r = await c.post(CHAT_ENDPOINT, json=chat_payload(model="totally-made-up-model-xyz"), headers=HEADERS)
            r.raise_for_status()

    await show_failure(
        "场景 2 · 模型名完全瞎写",
        s2,
        "400 —— 服务器会告诉你正确可用的名字有哪些（这点很贴心）",
    )
    print("  → 💡 服务端的报错信息里还带了 request_id，找客服时给这个号，比截图有用。")

    # 场景 3：DNS 失败
    async def s3():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0), trust_env=False) as c:
            await c.post(BAD_DOMAIN, json=chat_payload(), headers=HEADERS)

    await show_failure(
        "场景 3 · 域名根本不存在（DNS 失败）",
        s3,
        "ConnectError —— 注意这里用了 trust_env=False 绕开代理，才看得到真实 DNS 错误",
    )

    # 场景 4：目标不可路由 → ConnectTimeout
    async def s4():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=3.0), trust_env=False) as c:
            await c.post(UNREACHABLE, json=chat_payload(), headers=HEADERS)

    t0 = time.perf_counter()
    await show_failure(
        "场景 4 · 目标地址不可路由（包被丢掉）",
        s4,
        "ConnectTimeout —— 要等满 3 秒，因为 connect 超时设的是 3 秒",
    )
    print(f"  → 实际耗时：{time.perf_counter() - t0:.1f} 秒")
    print("""
  💡 对比场景 3 和场景 4，这是【排障时最重要的一个区分】：
       场景 3 用了 0.2 秒就报错 —— DNS 查不到，本地立刻就知道
       场景 4 硬等了 3.0 秒才报错 —— 域名解析成功了，包发出去了，没人应答
     一个快一个慢，指向的原因完全不同。看耗时就能分辨，不用猜。
""")

    # 场景 5：读取超时
    async def s5():
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0, read=0.05)) as c:
            await c.post(CHAT_ENDPOINT, json=chat_payload(max_tokens=1), headers=HEADERS)

    await show_failure(
        "场景 5 · 读取超时（连上了，但对方迟迟不吐字）",
        s5,
        "ReadTimeout —— 做法：把 read 压到 0.05 秒，而真实生成至少要几百毫秒",
    )
    print("  ⚠️ 这一个【可能已经产生了费用】—— 请求确实到达了服务端并开始生成。")
    print("     这正是 ReadTimeout 危险的地方，第三幕会展开。")

    # 场景 6：代理介入
    if HAS_PROXY:
        async def s6():
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as c:  # 默认 trust_env=True
                await c.post(BAD_DOMAIN, json=chat_payload(), headers=HEADERS)

        await show_failure(
            "场景 6 · 有代理时，同样的请求抛出的是另一个异常",
            s6,
            "ProxyError —— 和场景 3 是【同一个 URL】，但异常类型变了",
        )
        print("""
  ⭐ 这个场景是本实验最重要的一课：

     同一个 URL、同样的代码，仅仅因为环境里多了两个环境变量
     （HTTP_PROXY / HTTPS_PROXY），失败的【类型】就完全不一样了：

         无代理 → ConnectError（DNS 查不到）
         有代理 → ProxyError（代理替你去查，然后告诉你 502）

     httpx 默认 trust_env=True，会自动读这两个环境变量。
     这是好事（公司内网需要），但也意味着：

         【你的代码在别人机器上抛出的异常，可能和你本地不一样。】

     所以写 except 时必须留一个宽基类兜底：
         except httpx.RequestError:   ← 所有网络层异常的父类
     而不是只列几个你本地见过的具体类型。
""")
    else:
        thin()
        print("\n【场景 6】跳过 —— 本机没检测到 HTTP_PROXY / HTTPS_PROXY。")
        print("  这个场景演示的是「环境变量里的代理会改变异常类型」，没有代理就无从演示。")


# ══════════════════════════════════════════════════════════════
# 第三幕：可重试 / 不可重试
# ══════════════════════════════════════════════════════════════
async def act3_retry_matrix() -> None:
    banner("第三幕 · 这个错误，到底该不该重试？")

    print("""
判断的口诀只有一句：

        ┌───────────────────────────────────────────────┐
        │  重试能不能改变结果？                          │
        │  不能 → 别重试，直接失败（fast fail）          │
        │  能   → 才谈「等多久再试」                     │
        └───────────────────────────────────────────────┘
""")
    thin()
    print("\n【HTTP 状态码：查表就够】\n")
    meanings = {
        400: "请求格式错", 401: "未认证", 402: "余额不足", 403: "无权限",
        404: "端点不存在", 422: "参数校验失败",
        429: "限流", 500: "服务端错误", 502: "网关错误",
        503: "服务不可用", 504: "网关超时",
    }
    print(f"  {'状态码':<6} {'含义':<14} 处置")
    print(f"  {'─' * 6} {'─' * 14} {'─' * 46}")
    for code, advice in RETRY_BY_STATUS.items():
        print(f"  {code:<6} {meanings[code]:<14} {advice}")

    thin()
    print("""
【网络异常：按「请求到底走到哪一步了」来分】

  异常                    请求到了吗？     能安全重试吗？
  ─────────────────────   ──────────────   ──────────────────────────
  ConnectTimeout          没到             ✅ 能
  ConnectError            没到             ✅ 能
  WriteTimeout            发了一半         ✅ 能
  PoolTimeout             还没发出去       ✅ 能
  RemoteProtocolError     到了，对方崩了   ✅ 能
  ─────────────────────   ──────────────   ──────────────────────────
  ReadTimeout             到了，在生成中   ⚠️  见下
  ReadError               到了，读崩了     ❌ 别重试
""")
    thin()
    print("""
【⚠️ 为什么 ReadTimeout 和 ReadError 要特别小心】

  这是大模型 API 与普通 REST API 最大的差别：

      【POST /chat/completions 不是幂等的。】

  普通 REST 里 GET 一个资源失败重试，结果一样，没问题。
  但「生成一段文本」这件事：重新发一次 = 服务器重新生成一遍 = 【重新计费一次】。

  你 ReadTimeout 的时候，真实情况可能是三种之一：

      · 服务器已经算完了，只是响应包在路上丢了  → 重试 = 白花一次钱
      · 服务器还在算                            → 重试 = 现在有两份在算
      · 服务器根本没收到                        → 重试 = 正确的

  ⚠️ 这三种情况你【分不出来】。

  所以：
      · ReadTimeout：可以重试，但要【少重试 + 长间隔】，
        并且接受「可能重复计费」这个代价
      · ReadError：连接被破坏、响应不完整，重试收益不稳定，保守不重试

【工程上的正解】

  1. 幂等键（idempotency key）
     请求头带一个唯一 ID，服务端见到同样的 ID 就【直接返回上次结果】，
     不重新生成。这样重试才真正安全。
     （各家字段名不同，用前查文档）

  2. 流式 + 断点续传
     边生成边收。断了之后你知道【已经收到多少】，
     可以把已收到的内容作为「助手已说的部分」拼进下一轮，让它接着写。
     复杂度高，且【仍不能保证零重复计费】。

  3. 最省事的兜底：给单次成本设天花板
     max_tokens 设小 → 单次最坏成本可控
     进程设预算上限（见 .env 的 MONTHLY_BUDGET_CNY）
     即使重试策略写错了，损失也有上限。
""")


# ══════════════════════════════════════════════════════════════
# 第四幕：静默失败
# ══════════════════════════════════════════════════════════════
async def act4_silent_failures() -> None:
    banner("第四幕 · 最危险的失败：HTTP 200，但结果是坏的")

    print("""
前三幕都是「明显的失败」—— 报错、抛异常，你一定会发现。

真正能把你坑到线上的是【静默失败】：
状态码 200，程序一路绿灯，但拿到的结果其实不能用。
""")

    # ── 静默失败 0：模型名被静默替换 ──────────────────────
    thin()
    print("\n【静默失败 0】用过时的模型名，不报错，而是被【悄悄换掉】")
    print("  这个是我写这个实验时真踩的：我把模型名写成了 deepseek-v4-flash，")
    print("  而 GET /models 列出来的是 deepseek-flash —— 名字对不上。")
    print("  下面看看服务端到底怎么处理这个旧名字：\n")

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as c:
        r = await c.post(CHAT_ENDPOINT, json=chat_payload(model="deepseek-v4-flash"), headers=HEADERS)
    d = r.json()
    print(f"  HTTP 状态码    : {r.status_code}")
    print(f"  我请求的模型   : 'deepseek-v4-flash'")
    print(f"  响应里的 model : {d.get('model')!r}   ← ⚠️ 被换掉了")
    print("""
  ⭐ 危险在哪：

     状态码 200，程序不会报任何错。你以为自己在用 A 模型，
     实际在用的是 B 模型。

     我先说清楚【这不是 bug】，是官方有意设计的兼容：

         「legacy names 仍然被接受，但对应模型已退役，
           请求由 DeepSeek-V4.1-Flash 服务并按 Flash 价格计费。」

     所以钱没多花。但有个更隐蔽的坑 —— 设想你在做模型对比评测：

         while 遍历 ["deepseek-v4-flash", "deepseek-flash"]:
             跑同一批题
         结论：两个模型表现完全一样！

     你会以为自己发现了什么规律，实际上【两个名字打的是同一个模型】，
     整个 A/B 对比从根上就是无效的。

     对比一下：完全瞎写的名字（第二幕场景 2）会老实报 400，
     反而更容易发现。旧名字「能跑但被换掉」才是最危险的那类。

     【对策】不要相信你记得的模型名。启动时先调一次 GET /models，
     跟服务端核对一遍，对不上就立刻炸。
     这就是 client.py 要做的第一件事（下一节就要写了）。
""")

    # ── 静默失败 1：finish_reason = length ────────────────
    thin()
    print("\n【静默失败 1】回答被 max_tokens 截断 —— finish_reason = 'length'")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as c:
        r = await c.post(
            CHAT_ENDPOINT,
            json=chat_payload(content="请写一段 200 字左右的说明，介绍什么是 HTTP。", max_tokens=24),
            headers=HEADERS,
        )
    choice = r.json()["choices"][0]
    print(f"  HTTP 状态码   : {r.status_code}          ← 一切正常")
    print(f"  finish_reason : {choice['finish_reason']!r}   ← ⚠️ 是 length，不是 stop")
    print(f"  正文（截断）   : {choice['message'].get('content')!r}")
    print("""
  ⚠️ 状态码 200，程序不报错。如果你的代码只判断 status_code == 200 就往下走，
     拿到的是一段【被砍掉一半的话】，而且你永远不会知道。

     正确做法：把 finish_reason 也纳入校验 ——
         stop            正常结束
         length          被 max_tokens 截断 → 加 max_tokens，或标记为不完整
         content_filter  被内容策略拦       → 业务上单独处理
""")

    # ── 静默失败 2：content 空但 reasoning 有 ─────────────
    thin()
    print("\n【静默失败 2】content 是空的，但 reasoning_content 有东西")
    print("  推理模型特有：max_tokens 被思考过程吃光，正文一个字都没吐。")
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as c:
        r = await c.post(
            CHAT_ENDPOINT,
            json=chat_payload(content="简要说明一下 HTTPS 和 HTTP 的区别。", max_tokens=40),
            headers=HEADERS,
        )
    d = r.json()
    msg = d["choices"][0]["message"]
    usage = d["usage"]
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or ""

    print(f"  HTTP 状态码   : {r.status_code}")
    print(f"  finish_reason : {d['choices'][0]['finish_reason']!r}")
    print(f"  content 长度  : {len(content)} 字符")
    print(f"  reasoning 长度: {len(reasoning)} 字符")
    print(f"  思考 token / 输出 token : "
          f"{usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0)} / {usage['completion_tokens']}")
    print(f"  费用          : 输入 {usage['prompt_tokens']} + 输出 {usage['completion_tokens']} "
          f"= {usage['total_tokens']} token")

    if not content.strip():
        print("""
  ⚠️ 正文是空的，但状态码 200、费用照扣。
     如果你的代码写 messages.append({"role": "assistant", "content": msg["content"]})，
     就会往对话历史里塞一条空消息 —— 下一轮模型看到更懵，
     错误会往后累积，直到某天彻底崩掉，而你已经忘了源头在哪。
""")
    else:
        print("""
  （这次正文恰好写出了一点东西，但看 token 分配就知道：
    budget 的大头被思考过程吃掉了。调大 max_tokens 才稳。）
""")

    # ── 静默失败 3：格式对、内容错 ────────────────────────
    thin()
    print("""
【静默失败 3】最隐蔽的一种：格式对、内容错

    · 你让它「返回 JSON」，它返回了 JSON 但字段名不对
    · 你让它「只输出数字」，它输出「数字是 42」

    这类问题 HTTP 层面完全看不出来，只有【业务校验】能拦住。

    ⭐ 这就是 Day 3 学 Pydantic 的终极理由：

        把「我以为的响应格式」写成模型 → 让程序在【收到响应那一瞬间】
        就校验 → 不对就立刻炸在离现场最近的地方，而不是三天后线上。

      Day 1 的并发、Day 2 的限流与重试、Day 3 的 Pydantic、
      加上今天的 httpx —— 四天学的东西，就要在 client.py 里合体了。
""")


# ══════════════════════════════════════════════════════════════
async def main() -> None:
    await act1_timeout_anatomy()
    await act2_manufacture_errors()
    await act3_retry_matrix()
    await act4_silent_failures()

    banner("一句话带走")
    print("""
  1. 超时是四个旋钮，不是一个。connect 快、read 慢。
  2. 「该不该重试」问的是【重试能不能改变结果】。
     4xx 基本不改，5xx 和 ConnectError 能改。
  3. POST 不幂等 —— 重试可能重复计费。要么用幂等键，要么限制单次成本。
  4. 最危险的不是报错，是「HTTP 200 但结果是坏的」。
     finish_reason 和 Pydantic 校验是拦它的两道网。
  5. except httpx.RequestError 一定要写 —— 你本地见到的异常类型，
     换个环境（比如多两个代理环境变量）就变了。
""")


if __name__ == "__main__":
    asyncio.run(main())
