# W1-02：并发上限 —— Semaphore

## 想搞清楚什么

昨天证明了 `gather` 能把 3 个请求压成 1 秒。**但并发不是越多越好。**

同时甩出 20 个请求 = 同时开 20 个连接。真实 API 的后果：

- 触发对端 QPS 限制 → `429 Too Many Requests`
- 本地文件描述符被吃光 → `Too many open files`
- 某个慢请求拖住整批 → 超时雪崩

所以工程代码里，并发一定有个上限。`asyncio.Semaphore` 就是最常用的那道闸门。

## 填空答案

`fetch_limited()` 里要填的就一行 —— `async with`：

```python
async def fetch_limited(n: int, sem: asyncio.Semaphore) -> str:
    async with sem:
        return await fetch(n)
```

## 怎么跑

**PyCharm**：目录树里右键 `limit_concurrency.py` → `Run 'limit_concurrency'`

**命令行**：

```bash
cd experiments/w1-02-semaphore
python limit_concurrency.py
```

只用到标准库。A 版约 0.5 秒，B 版约 2 秒。

## 实测结果

| 版本 | 总耗时 | 峰值并发 |
| --- | --- | --- |
| A 裸 gather | 0.51 秒 | 20 |
| B 限流 5 | 2.05 秒 | 5 |

**A 版：所有请求在同一毫秒涌出来**

```
请求  1 开始 | 并发  1 | 14:24:44.172
请求  2 开始 | 并发  2 | 14:24:44.172
...
请求 20 开始 | 并发 20 | 14:24:44.172
```

**B 版：涨到 5 就停住，空位一出来立刻补人**

```
请求 15 结束 | 并发  0 | 14:24:46.231
请求 16 开始 | 并发  1 | 14:24:46.231
请求 17 开始 | 并发  2 | 14:24:46.231
请求 18 开始 | 并发  3 | 14:24:46.231
请求 19 开始 | 并发  4 | 14:24:46.231
请求 20 开始 | 并发  5 | 14:24:46.231
```

## 原理：`async with sem` 做了什么

`Semaphore(5)` 内部只有一个**计数器**，初始值是 5。

| 动作 | 计数器怎么变 |
| --- | --- |
| 进门 `acquire()` | 减 1；如果已经是 0，就挂起排队 |
| 出门 `release()` | 加 1，并唤醒队列里的下一个 |

`async with sem:` 是下面这段的语法糖：

```python
await sem.acquire()
try:
    return await fetch(n)
finally:
    sem.release()
```

用 `async with` 而不是手写这五行的理由，是**异常安全**：哪怕 `fetch(n)` 中途抛异常，钥匙也一定会还回去。

手写时忘了 `finally`，计数器就会永久漏掉一把 —— 并发额度越限越小，跑着跑着整个程序卡死。这是新手最常踩的坑之一。

（`asyncio` 还提供 `BoundedSemaphore`：release 次数超过 acquire 时会直接报错，帮你早点暴露这类 bug。）

## 思考题 ③：B 版总耗时怎么算

> **答：** 请求被按批处理，每批最多放 `MAX_CONCURRENT` 个进去。

```
批数 = ⌈TOTAL / MAX_CONCURRENT⌉ = ⌈20 / 5⌉ = 4
总耗时 ≈ 批数 × COST = 4 × 0.5 = 2.0 秒
```

实测 2.05 秒，多出来的 0.05 秒是协程调度开销。

**一般式**（记这一个就够）：

```
T ≈ ⌈N / C⌉ × t        N = 请求数, C = 并发上限, t = 单次耗时
```

拿昨天的实验验证一下：3 个请求、上限无限大、每个 1 秒 → ⌈3/∞⌉ = 1 批 → 1 秒 ✅

## 思考题 ④：限流是亏了还是赚了

> **答：** 亏了速度，赚了可用性。

**亏的**：总耗时从 0.51 秒涨到 2.05 秒，慢了 4 倍。只看吞吐量，限流是倒退。

**赚的**：

- 峰值并发恒定 = 5，对端不会看到流量尖刺 → 不触发 429
- 本机连接数 / 文件描述符有上界 → 不会 `Too many open files`
- 负载可预测：一次发 20 个还是 2000 个，对服务端的瞬时压力完全一样

**一句话**：限流不是为了跑得快，是为了**在高压下还能活着**。

这个取舍在 W1 后半段会原样出现在 `llmkit/client.py` 里 —— 调 LLM API 时并发不设上限，轻则被限流，重则账单爆炸。

## 自查清单

- [x] A 版峰值并发 ≥ 20，B 版峰值并发 = 5
- [x] B 版总耗时 ≈ 2 秒（不是 0.5 秒）
- [x] 能说出 `async with sem:` 干了什么（计数器加减 + 异常安全）
- [x] 知道为什么并发要设上限（429 / 文件描述符 / 雪崩）
- [x] 会用公式 ⌈N / C⌉ × t 估算总时长

## 踩的坑

> **PyCharm 把标准库当成了第三方包。**
> 刚打开项目时，PyCharm 对着 `import asyncio` 报「缺少包」，一点 Install 就从 PyPI 装了个同名的空壳包 `asyncio 4.0.0`，还顺手改写了 `pyproject.toml` 和 `uv.lock`。
>
> **教训**：`asyncio` / `json` / `os` / `pathlib` / `typing` / `time` 这些是 Python **自带的**，永远不要装。PyCharm 弹「Install package」时，先判断一下这个模块是不是标准库。
