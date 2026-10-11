"""
W1 Day 2：并发上限 —— Semaphore（信号量）

━━━ 想搞清楚什么 ━━━

昨天你用 gather 把 3 个请求压成了 1 秒。那 100 个请求呢？

直接 gather 100 个，等于瞬间甩出 100 个连接。后果：
    · 对端限流 / 直接拒绝（绝大多数 API 都有 QPS 限制）
    · 本地文件描述符被吃光
    · 一个慢请求会把整批拖住

所以真实工程里，并发必须设上限。asyncio 里最常用的闸门就是 Semaphore。

━━━ 怎么看这个实验 ━━━

每个请求开始 / 结束时打印一行，带上「当前并发数」：
    A 版（裸 gather）      → 并发数会一路冲到 20
    B 版（Semaphore(5)）   → 并发数最多卡在 5，其余在门口排队

━━━ 先猜后跑 ━━━

跑之前先在心里（或 README 里）估一下总耗时：
    A 版 ≈ ____ 秒
    B 版 ≈ ____ 秒

运行：
    python limit_concurrency.py
"""

import asyncio
import time

TOTAL = 20            # 总共发多少个请求
COST = 0.5            # 每个请求耗时（秒）
MAX_CONCURRENT = 5    # B 版允许的最大同时在跑数量

_active = 0           # 当前正在跑的请求数
_peak = 0             # 历史峰值并发数


def now() -> str:
    """返回形如 14:30:01.421 的时间戳。"""
    return f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}"


async def fetch(n: int) -> str:
    """模拟一次耗时 COST 秒的网络请求，并记录瞬时并发数。"""
    global _active, _peak
    _active += 1
    _peak = max(_peak, _active)
    print(f"  请求 {n:2d} 开始 | 并发 {_active:2d} | {now()}")
    await asyncio.sleep(COST)
    _active -= 1
    print(f"  请求 {n:2d} 结束 | 并发 {_active:2d} | {now()}")
    return f"结果{n}"


def reset_stats() -> None:
    global _active, _peak
    _active = 0
    _peak = 0


# ============================================================
# A 版：裸 gather —— 没有任何限制
# ============================================================

async def run_unlimited() -> float:
    reset_stats()
    t0 = time.perf_counter()
    await asyncio.gather(*[fetch(i) for i in range(1, TOTAL + 1)])
    return time.perf_counter() - t0


# ============================================================
# B 版：Semaphore 限流
# ============================================================
#
# Semaphore 想象成一串「钥匙」：
#     进门前先领一把，出门时还回去。
#     钥匙总共只有 MAX_CONCURRENT 把，
#     所以同一时刻最多只有这么多人待在屋里 —— 其余的在门口排队。
#
# 文档：https://docs.python.org/zh-cn/3/library/asyncio-sync.html
#     在这页里搜「Semaphore」，看官方例子怎么用。


async def fetch_limited(n: int, sem: asyncio.Semaphore) -> str:
    """带闸门的 fetch：最多 MAX_CONCURRENT 个同时进屋。

    ────────────── async with sem 到底做了什么 ──────────────

    Semaphore(5) 内部只维护一个计数器，初始值是 5。

        进门时 acquire()：计数器 -1
            · 减完仍然 >= 0  → 直接放行
            · 已经减到 0     → 挂起等待，排进等待队列
        出门时 release()：计数器 +1，并唤醒队列里的下一个

    所以「同时最多 5 个」不是什么魔法，就是一个计数器在加减。
    这行 async with 是下面这段的语法糖：

        await sem.acquire()
        try:
            return await fetch(n)
        finally:
            sem.release()

    用 async with 的好处：哪怕 fetch(n) 中途抛异常，钥匙也一定会还回去，
    计数器不会永久漏掉一把（否则并发数会越限越小，最后卡死）。
    """
    async with sem:
        return await fetch(n)


async def run_limited() -> float:
    reset_stats()
    sem = asyncio.Semaphore(MAX_CONCURRENT)
    t0 = time.perf_counter()
    await asyncio.gather(*[fetch_limited(i, sem) for i in range(1, TOTAL + 1)])
    return time.perf_counter() - t0


# ============================================================
# 入口
# ============================================================

def section(title: str) -> None:
    print()
    print("=" * 56)
    print(title)
    print("=" * 56)


if __name__ == "__main__":
    section(f"A 版：裸 gather（完全不限并发，共 {TOTAL} 个请求）")
    ta = asyncio.run(run_unlimited())
    peak_a = _peak

    section(f"B 版：Semaphore({MAX_CONCURRENT}) 限流")
    try:
        tb = asyncio.run(run_limited())
        peak_b = _peak
    except NotImplementedError as e:
        tb, peak_b = None, None
        print(f"  [TODO 还没填] {e}")

    section("对比小结")
    print("             总耗时       峰值并发")
    print(f"A 裸 gather  {ta:6.2f} 秒       {peak_a:2d}")
    if tb is None:
        print("B 限流        ——          ——   （TODO 未完成，先填上再跑）")
        print()
        print("填完 TODO 后再跑一次，这里会自动出现 B 版的数据。")
    else:
        print(f"B 限流 {MAX_CONCURRENT}     {tb:6.2f} 秒       {peak_b:2d}")
        print()
        print(f"限流把峰值并发从 {peak_a} 压到 {peak_b}，")
        print(f"代价是总耗时从 {ta:.2f} 秒涨到 {tb:.2f} 秒。")
        print("这就是限流的本质：用时间换稳定。")
