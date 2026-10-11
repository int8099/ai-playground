"""
W1-03：失败重试 —— 指数退避 + 抖动（Exponential Backoff with Jitter）

━━━ 想搞清楚什么 ━━━

网络请求会失败，而且多数不是「坏了」，是「这一下没成」：

    · 429 Too Many Requests   —— 你发太快了
    · 502 / 503 / 504         —— 网关或服务端打了个盹
    · 连接超时、连接被重置

这类失败，过一会儿再试往往就成功了。所以工程代码里必须有重试。

但重试做错了，比不重试还糟：

    假设 100 个客户端全都在 0.5 秒后一起重试。
    服务刚刚缓过来，又被这 100 个请求同时打垮 —— 如此循环。
    这叫【惊群效应 / thundering herd】。

━━━ 四个策略 ━━━

    A. 不重试                       失败就失败
    B. 固定延迟重试                  每次都等 0.2 秒
    C. 指数退避，无抖动               等 0.2 → 0.4 → 0.8 秒
    D. 指数退避 + 抖动（生产推荐）     等待时间在 0 ~ 2^n × 0.2 之间随机

━━━ 怎么看 ━━━

盯着「最密集窗口」这个指标：任意 0.05 秒内，最多有几个客户端同时重试。

    B、C  → 很高，说明重试全撞在一起
    D     → 很低，说明重试被摊平了

━━━ 注意 ━━━

四个策略面对的是【完全一样的失败序列】（固定了随机种子），
所以成功率、重试次数可以直接横向比较。

运行：
    python retry_backoff.py
"""

import asyncio
import random
import sys
import time


def _parse_clients() -> int:
    """从命令行读客户端数量：python retry_backoff.py 200   （默认 20）"""
    if len(sys.argv) < 2:
        return 20
    try:
        return int(sys.argv[1])
    except ValueError:
        print(f"参数必须是整数，收到的是 {sys.argv[1]!r}")
        raise SystemExit(1)


CLIENTS = _parse_clients()   # 同时请求的客户端数
BASE_DELAY = 0.2       # 基础退避时间（秒）
MAX_RETRIES = 3        # 最多重试几次
FAIL_RATE = 0.6        # 单次调用的失败概率
CALL_COST = 0.05       # 单次调用本身的耗时（网络往返）

_fail_rng = random.Random(2026)      # 控制「成功 / 失败」
_jitter_rng = random.Random(1011)    # 控制「抖动」

_t0 = 0.0
_retry_log: list[float] = []


def now() -> str:
    """返回形如 14:30:01.421 的时间戳。"""
    return f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}"


def reset_rng() -> None:
    """每个策略开始前重置随机序列 —— 保证四个策略面对一模一样的失败模式。"""
    _fail_rng.seed(2026)
    _jitter_rng.seed(1011)


async def call_service() -> bool:
    """模拟一次 API 调用：按 FAIL_RATE 的概率返回失败。"""
    await asyncio.sleep(CALL_COST)
    return _fail_rng.random() >= FAIL_RATE


def next_delay(strategy: str, attempt: int) -> float:
    """第 attempt 次重试之前，该等多久。

    attempt 从 0 开始：0 = 第一次重试、1 = 第二次、2 = 第三次。
    """
    base = BASE_DELAY * (2 ** attempt)      # 0.2 → 0.4 → 0.8
    if strategy == "fixed":
        return BASE_DELAY
    if strategy == "exp":
        return base
    if strategy == "jitter":
        # full jitter：在 [0, base] 之间随机取值。
        # 这是 AWS 推荐的默认做法 —— 上限保住「退避」，随机保住「不撞车」。
        return _jitter_rng.uniform(0, base)
    raise ValueError(f"未知策略: {strategy}")


async def client(cid: int, strategy: str, max_retries: int) -> bool:
    """一个客户端：调用失败就按策略重试，直到成功或耗尽次数。"""
    for attempt in range(max_retries + 1):
        if attempt > 0:
            _retry_log.append(time.perf_counter() - _t0)
        if await call_service():
            return True
        if attempt < max_retries:
            await asyncio.sleep(next_delay(strategy, attempt))
    return False


async def run_strategy(strategy: str, max_retries: int) -> tuple[int, float, list[float]]:
    """让 CLIENTS 个客户端同时跑同一个策略，返回 (成功数, 总耗时, 重试时刻表)。"""
    global _t0, _retry_log
    reset_rng()
    _retry_log = []
    _t0 = time.perf_counter()

    results = await asyncio.gather(
        *[client(i, strategy, max_retries) for i in range(CLIENTS)]
    )

    elapsed = time.perf_counter() - _t0
    return sum(results), elapsed, list(_retry_log)


def burst_peak(times: list[float], window: float = 0.05) -> int:
    """任意 window 秒的窗口里，最多有几个客户端同时在重试。

    这个数字就是「惊群」的量化指标：越大越糟。
    """
    if not times:
        return 0
    ts = sorted(times)
    best = 0
    j = 0
    for i in range(len(ts)):
        while ts[i] - ts[j] > window:
            j += 1
        best = max(best, i - j + 1)
    return best


def section(title: str) -> None:
    print()
    print("=" * 58)
    print(title)
    print("=" * 58)


STRATEGIES = [
    ("A  不重试", "none", 0),
    ("B  固定延迟重试（每次等 0.2 秒）", "fixed", MAX_RETRIES),
    ("C  指数退避，无抖动（0.2 → 0.4 → 0.8 秒）", "exp", MAX_RETRIES),
    ("D  指数退避 + 抖动（0 ~ 2^n × 0.2 秒随机）", "jitter", MAX_RETRIES),
]


if __name__ == "__main__":
    summary: list[tuple[str, int, float, int]] = []

    for name, strategy, max_retries in STRATEGIES:
        section(name)

        if strategy == "none":
            ok, elapsed, log = asyncio.run(run_strategy("fixed", 0))
        else:
            ok, elapsed, log = asyncio.run(run_strategy(strategy, max_retries))

        peak = burst_peak(log)
        summary.append((name.split()[0], ok, elapsed, peak))

        print(f"    成功率      {ok}/{CLIENTS}  ({ok / CLIENTS:.0%})")
        print(f"    总耗时      {elapsed:.2f} 秒")
        print(f"    重试总次数  {len(log)}")

        if log:
            crowd = peak >= CLIENTS // 2
            note = "   ← 惊群：全撞在同一时刻" if crowd else "   ← 摊平了"
            print(f"    最密集窗口  任意 0.05 秒内最多同时重试 {peak} 个{note}")
            sample = " ".join(f"{t:.3f}" for t in sorted(log)[:10])
            print(f"    重试时刻    {sample}{' ...' if len(log) > 10 else ''}")
        else:
            print("    没有发生任何重试")

    section("小结")
    print(f"    {'策略':<8}{'成功率':<9}{'总耗时':<10}{'最密集':<9}{'占比'}")
    print("    " + "-" * 50)
    for tag, ok, elapsed, peak in summary:
        print(f"    {tag:<8}{ok / CLIENTS:<9.0%}{elapsed:<10.2f}"
              f"{peak:<9}{peak / CLIENTS:.0%}")

    print()
    _, ok_a, _, _ = summary[0]
    _, ok_retry, _, peak_bc = summary[1]
    _, _, _, peak_d = summary[3]

    print("结论：")
    print(f"  · 重试把成功率从 {ok_a / CLIENTS:.0%} 拉到 {ok_retry / CLIENTS:.0%}"
          f" —— 这是重试的价值。")
    print(f"  · B 和 C 的最密集窗口都是 {peak_bc} 个 —— 说明【光有指数退避还不够】。")
    print(f"  · 只有 D 降到了 {peak_d} 个 —— 抖动才是解决惊群的那一半。")
