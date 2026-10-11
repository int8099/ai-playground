"""
W1 Day 1（扩展版）：三类任务对比

目标：证明 asyncio 只能「重叠等待」，不能「加速计算」。

三类：
  ① 同步串行    I/O 密集，一个请求等完再等下一个        预期 ≈ 3.0 秒
  ② 异步并发    I/O 密集，三个请求的等待期重叠          预期 ≈ 1.0 秒
  ③ 异步并发    CPU 密集，三个任务都在算，谁都不让位    预期 ≈ 3.0 秒  ← 重点

② 比 ① 快，是因为「等待」可以重叠 —— 这叫【并发】。
③ 和 ① 一样慢，是因为「计算」没有等待可以重叠 —— 这就是为什么
   asyncio 给不了你【并行】，它自始至终只跑在一个线程上。

运行：
    python sync_vs_async.py
"""

import asyncio
import time


def now() -> str:
    """返回形如 14:20:31.421 的时间戳，用来观察时间区间是否重叠。"""
    return f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}"


def burn_cpu(seconds: float) -> int:
    """在 CPU 上实打实地跑满 seconds 秒（忙循环，不是 sleep）。

    注意：这个函数从头到尾没有 await，也不会主动让出控制权。
    """
    t0 = time.perf_counter()
    spins = 0
    while time.perf_counter() - t0 < seconds:
        spins += 1
    return spins


# ============================================================
# ① 同步串行 —— I/O 密集
# ============================================================

def request_sync(n: int) -> str:
    """一次耗时 1 秒的网络请求（同步阻塞）。"""
    print(f"[①同步] 请求 {n} 开始  {now()}")
    time.sleep(1)
    print(f"[①同步] 请求 {n} 结束  {now()}")
    return f"结果{n}"


def run_sync() -> float:
    t0 = time.perf_counter()
    results = [request_sync(i) for i in range(1, 4)]
    elapsed = time.perf_counter() - t0
    print(f"[①同步] 结果={results}")
    print(f"[①同步] 总耗时 = {elapsed:.2f} 秒")
    return elapsed


# ============================================================
# ② 异步并发 —— I/O 密集
# ============================================================

async def request_io(n: int) -> str:
    """一次耗时 1 秒的网络请求（异步）。

    asyncio.sleep 会主动让出控制权，让别的协程接着跑。
    """
    print(f"[②IO异步] 请求 {n} 开始  {now()}")
    await asyncio.sleep(1)
    print(f"[②IO异步] 请求 {n} 结束  {now()}")
    return f"结果{n}"


async def run_io() -> float:
    t0 = time.perf_counter()
    results = await asyncio.gather(request_io(1), request_io(2), request_io(3))
    elapsed = time.perf_counter() - t0
    print(f"[②IO异步] 结果={results}")
    print(f"[②IO异步] 总耗时 = {elapsed:.2f} 秒")
    return elapsed


# ============================================================
# ③ 异步并发 —— CPU 密集（关键对照组）
# ============================================================
# 看清楚：下面这个函数确实是 async def，
# 也确实是三个一起塞进 gather 里的 —— 写法上和第 ② 类一模一样。
# 区别只有一个：它内部 1 秒钟都在算，没有 await 让位。

async def request_cpu(n: int) -> str:
    """一次耗时 1 秒的 CPU 计算任务（也是 async def，但没地方可让位）。"""
    print(f"[③CPU异步] 任务 {n} 开始  {now()}")
    burn_cpu(1.0)
    print(f"[③CPU异步] 任务 {n} 结束  {now()}")
    return f"结果{n}"


async def run_cpu() -> float:
    t0 = time.perf_counter()
    results = await asyncio.gather(request_cpu(1), request_cpu(2), request_cpu(3))
    elapsed = time.perf_counter() - t0
    print(f"[③CPU异步] 结果={results}")
    print(f"[③CPU异步] 总耗时 = {elapsed:.2f} 秒")
    return elapsed


# ============================================================
# 入口
# ============================================================

def section(title: str) -> None:
    print()
    print("=" * 52)
    print(title)
    print("=" * 52)


if __name__ == "__main__":
    section("① 同步串行 —— I/O 密集")
    t1 = run_sync()

    section("② 异步并发 —— I/O 密集")
    t2 = asyncio.run(run_io())

    section("③ 异步并发 —— CPU 密集")
    t3 = asyncio.run(run_cpu())

    section("对比小结")
    print(f"① 同步串行（I/O 密集）    {t1:.2f} 秒")
    print(f"② 异步并发（I/O 密集）    {t2:.2f} 秒   ← 等待被重叠了，快了")
    print(f"③ 异步并发（CPU 密集）    {t3:.2f} 秒   ← 没有等待，gather 白写了")
    print()
    print("结论：asyncio 只能重叠「等待」，不能加速「计算」。")
    print("      它给的是【并发】，不是【并行】。")
