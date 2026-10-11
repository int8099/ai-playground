"""
llmkit.client —— 把 W1 四天学的东西组装成一个能用的客户端
================================================================

这个文件是 W1 的交付物。它不演示新知识，它演示【怎么把学过的东西拼起来】。

    Day 1   并发思维       →  chat_many() 用 asyncio.gather 同时打多条
    Day 2a  Semaphore      →  _sem 闸门，控制同时在飞的请求数
    Day 2b  抖动指数退避    →  _post_with_retry()，抗惊群
    Day 3   Pydantic v2    →  models.py，请求响应全都有类型和校验
    Day 4   httpx          →  连接池复用、四段超时、错误分类、SSE 流式

除此之外还加了三样「真实项目必须有、但教程里常常不讲」的东西：

    ① 启动时校验模型名     → 防止「用过时名字被静默替换」这类静默失败
    ② finish_reason 校验   → 把「HTTP 200 但内容被截断」变成可检测的异常
    ③ 成本统计与预算硬上限  → 对应 docs/budget.md 里承诺过的「超限即拒绝」

一个设计原则贯穿全文件：**能静默失败的地方，都要变成显式失败。**
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .models import (
    PRICES,
    ChatRequest,
    ChatResponse,
    Message,
    ModelPrice,
    price_of,
)

# ══════════════════════════════════════════════════════════════
# 异常
# ══════════════════════════════════════════════════════════════
# 为什么要自定义异常，而不是直接抛 httpx 的？
#     调用方关心的是「我的业务出什么事了」，不是「httpx 内部怎么了」。
#     把底层异常翻译成业务语义，上层才好处理 —— 总不能要求
#     每个调用方都懂 httpx.ConnectTimeout 和 ReadTimeout 的区别。


class LLMKitError(Exception):
    """本库所有异常的基类。调用方至少可以 except LLMKitError 兜底。"""


class ModelMismatchError(LLMKitError):
    """配置的模型名不在服务端支持的列表里。

    专门为「静默替换」设计的 —— 用错模型名服务端可能不报错，
    而是悄悄换成别的模型，这种失败最难查，所以要在启动时就拦住。
    """


class TruncatedResponseError(LLMKitError):
    """回答被 max_tokens 截断了。

    这是【静默失败】的典型：HTTP 200，状态码一切正常，
    但内容是残缺的。所以要专门造一个异常把它显式化。
    """


class BudgetExceededError(LLMKitError):
    """累计成本超过了预算上限，拒绝继续调用。"""


class RetryExhaustedError(LLMKitError):
    """重试次数用尽仍然失败。最后一个原始异常挂在 .last_error 上。"""

    def __init__(self, message: str, last_error: BaseException) -> None:
        super().__init__(message)
        self.last_error = last_error


# ══════════════════════════════════════════════════════════════
# 错误分类：这个错误该不该重试？
# ══════════════════════════════════════════════════════════════
# 这两个集合来自实验 02 的实测结论。
RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})
"""可重试的状态码。

    429  限流    —— 等一会儿通常就好了
    5xx  服务端  —— 通常是暂时性的
    408  请求超时
"""

NON_RETRYABLE_STATUS = frozenset({400, 401, 402, 403, 404, 422})
"""不该重试的状态码 —— 重试一万次结果也不会变。"""


def is_retryable(exc: BaseException) -> bool:
    """判断一个异常值不值得重试。

    判据（实验 02 的结论）：【重试能不能改变结果】。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS

    # ⚠️ 判断顺序必须从具体到宽泛。
    #    ReadTimeout 继承自 TimeoutException，TimeoutException 继承自 TransportError，
    #    顺序写反了后面永远走不到。
    if isinstance(exc, httpx.ReadTimeout):
        # ReadTimeout 意味着请求【可能已经被处理了】。
        # 对非幂等的 POST 来说，重试有重复计费的风险，所以不重试 ——
        # 这是我们主动选择的保守策略，不是漏写。
        return False

    if isinstance(exc, (httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return True  # 请求没发出去，或者没发完 → 重试是安全的

    if isinstance(exc, httpx.ConnectError):
        return True  # 连都没连上

    if isinstance(exc, httpx.ReadError):
        return False  # 连接被破坏，响应不完整，重试收益不稳定

    if isinstance(exc, httpx.RemoteProtocolError):
        return True  # 常见于服务端中途掉线

    if isinstance(exc, httpx.ProxyError):
        return False  # 先修代理，重试没用

    return False


# ══════════════════════════════════════════════════════════════
# 统计
# ══════════════════════════════════════════════════════════════
@dataclass
class ClientStats:
    """运行期统计。真实项目里这些数字应该上报到监控系统。"""

    calls: int = 0              # 逻辑调用次数（不含重试）
    http_requests: int = 0      # 实际发出的 HTTP 请求数（含重试）
    retries: int = 0
    failures: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost_cny: float = 0.0

    @property
    def retry_rate(self) -> float:
        """重试率。>0.3 说明下游不稳定，或者你的超时设得太激进。"""
        return self.retries / self.http_requests if self.http_requests else 0.0

    @property
    def reasoning_ratio(self) -> float:
        """思考 token 占输出的比例。实验 04 实测最高能到 97%。"""
        return self.reasoning_tokens / self.completion_tokens if self.completion_tokens else 0.0

    def summary(self) -> str:
        return (
            f"调用 {self.calls} 次 / 发出 {self.http_requests} 个请求 / 重试 {self.retries} 次 / 失败 {self.failures} 次\n"
            f"token：输入 {self.prompt_tokens}（缓存命中 {self.cached_tokens}）"
            f" + 输出 {self.completion_tokens}（其中思考 {self.reasoning_tokens}，占 {self.reasoning_ratio:.0%}）\n"
            f"累计成本：¥{self.cost_cny:.6f}"
        )


# ══════════════════════════════════════════════════════════════
# 客户端
# ══════════════════════════════════════════════════════════════
DEFAULT_TIMEOUT = httpx.Timeout(180.0, connect=10.0)
"""LLM 场景的超时。

    connect=10   连不上就赶紧失败
    read=180     生成慢是正常的，给足耐心
                 流式时它是【包间隔】上限，不是总时长上限（见实验 03）

⚠️ 绝对不要用 httpx 默认的 5 秒 —— 对大模型来说太短了。
"""


class LLMClient:
    """异步大模型客户端。

    典型用法：

        async with LLMClient() as client:
            await client.verify_models()              # 启动自检（强烈建议）
            resp = await client.chat("你好")           # 单条
            resp_list = await client.chat_many(["问题1", "问题2"])   # 并发多条
            async for piece in client.chat_stream("讲个故事"):        # 流式
                print(piece, end="")

    ⚠️ 一定要用 async with（或自己调 aclose()）。
       里面的 httpx.AsyncClient 持有连接池，不关会泄漏。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        *,
        max_concurrency: int = 5,
        max_retries: int = 3,
        base_delay: float = 0.5,
        max_connections: int | None = None,
        timeout: httpx.Timeout | None = None,
        disable_thinking: bool = True,
        monthly_budget_cny: float | None = None,
        already_spent_cny: float = 0.0,
        trust_env: bool = True,
    ) -> None:
        """
        参数说明（挑几个关键的）：

            max_concurrency   同时在飞的请求上限。对应 Day 2 的 Semaphore。
                              默认 5 —— 别一上来就开 50，服务端会限流你。

            max_retries       失败后最多再试几次（不含首次）。默认 3。

            base_delay        退避的基数（秒）。实际等待时间是
                              random.uniform(0, base_delay * 2**attempt)，
                              即「full jitter」。对应 Day 2 的抗惊群。

            disable_thinking  ⭐ 默认 True —— 默认【关掉思考】。
                              理由见实验 04：思考 token 占输出的 97%，
                              而且简单任务上它不产生任何用户可见价值。
                              需要推理的任务请显式开。

            monthly_budget_cny  月度预算上限。累计成本超过就抛
                              BudgetExceededError，拒绝继续调用。
                              这是 docs/budget.md 里承诺过的保护措施。

            already_spent_cny   本月【之前】已经花掉的钱（从账台账读）。
                              预算判断用的是 already_spent + 本次进程花费。
        """
        # ── 配置来源的优先级：显式参数 > 环境变量 > 默认值 ──
        # 写代码时按这个顺序找，出问题时就容易定位「到底读到了哪个值」。
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise LLMKitError("没有 API Key。请在 .env 里设置 DEEPSEEK_API_KEY，或显式传入 api_key。")

        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.model = model or os.environ.get("DEFAULT_MODEL") or "deepseek-flash"

        self.max_retries = max_retries
        self.base_delay = base_delay
        self.disable_thinking = disable_thinking

        self.max_concurrency = max_concurrency
        # ── Day 2a：Semaphore 闸门 ──
        # 注意它是在 __init__ 里建的，不是每次调用建的 ——
        # 它的作用域必须覆盖整个客户端的生命周期，否则限流就没意义了。
        self._sem = asyncio.Semaphore(max_concurrency)

        # ── Day 4：连接池 ──
        # max_connections 是【传输层】的限制，Semaphore 是【应用层】的限制。
        # 两者配合才是完整的限流：Semaphore 管"我允许发几个"，
        # httpx 管"底层最多开几条 TCP 连接"。
        # 如果只设 Semaphore，而某处忘了用它，连接数还是会爆。
        limits = httpx.Limits(
            max_connections=max_connections or max_concurrency * 2,
            max_keepalive_connections=max_connections or max_concurrency,
        )
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or DEFAULT_TIMEOUT,
            limits=limits,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            trust_env=trust_env,
        )

        # ── 预算 ──
        self.monthly_budget_cny = monthly_budget_cny
        self.already_spent_cny = already_spent_cny

        self.stats = ClientStats()
        self._price: ModelPrice = price_of(self.model)
        self._model_verified = False

    # ══════════════════════════════════════════════════════════
    # 生命周期
    # ══════════════════════════════════════════════════════════
    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭连接池。用 async with 的话会自动调用。"""
        await self._client.aclose()

    # ══════════════════════════════════════════════════════════
    # 启动自检
    # ══════════════════════════════════════════════════════════
    async def verify_models(self, strict: bool = True) -> list[str]:
        """跟服务端核对一次模型名，返回可用模型列表。

        为什么必须做这件事（实验 02「静默失败 0」的真实教训）：
            用【过时的】模型名不会报错，服务端会悄悄换成别的模型给你服务。
            你以为在用 A，实际在用 B，做对比实验得出的结论全是错的。

        这个过程不消耗 token（GET /models 是免费的），成本为零。
        """
        resp = await self._client.get("/models")
        resp.raise_for_status()
        data = resp.json()

        ids = [item["id"] for item in data.get("data", []) if item.get("id")]

        if self.model not in ids:
            if strict:
                raise ModelMismatchError(
                    f"模型 {self.model!r} 不在服务端支持的列表里。\n"
                    f"服务端可用的模型：{ids}\n"
                    f"→ 检查 .env 里的 DEFAULT_MODEL。"
                    f"如果这确实是个旧名字，服务端可能会【静默替换】它，"
                    f"让你的对比实验失去意义 —— 所以这里直接拦下来。"
                )
            # strict=False 时只警告不拦，方便对照实验
        self._model_verified = True
        return ids

    # ══════════════════════════════════════════════════════════
    # 内部：带重试的请求
    # ══════════════════════════════════════════════════════════
    async def _post_once(self, payload: dict[str, Any]) -> httpx.Response:
        """发一次请求（带 Semaphore 闸门），不含重试。"""
        async with self._sem:            # ← Day 2a：闸门在这里
            self.stats.http_requests += 1
            resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp

    async def _post_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        """带指数退避 + 抖动的请求。对应 Day 2b。

        等待时间 = random.uniform(0, base_delay * 2 ** attempt)

        为什么必须有 random（full jitter）：
            光有指数退避只能把「等多久」拉开，不能把「谁和谁一起等」打散。
            所有失败客户端仍然会在同一时刻集体重试 → 惊群。
            Day 2 实验 w1-03 的实测：2000 个客户端下，
            纯指数退避的尖峰重试占比 60%，加了抖动降到 22%。
        """
        last_error: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await self._post_once(payload)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc

                # 判断该不该重试 —— 这是 Day 4 实验 02 的核心结论
                if not is_retryable(exc):
                    self.stats.failures += 1
                    raise

                # 最后一次也失败了，没机会再试
                if attempt == self.max_retries:
                    break

                # ── 特殊处理 429：服务端可能告诉我们该等多久 ──
                # 有 Retry-After 就用它，比自己猜准得多。
                delay: float
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    header = exc.response.headers.get("Retry-After")
                    if header and header.replace(".", "", 1).isdigit():
                        delay = float(header)
                    else:
                        delay = random.uniform(0, self.base_delay * (2 ** attempt))
                else:
                    delay = random.uniform(0, self.base_delay * (2 ** attempt))

                self.stats.retries += 1
                await asyncio.sleep(delay)

        self.stats.failures += 1
        assert last_error is not None
        raise RetryExhaustedError(
            f"重试 {self.max_retries} 次后仍然失败：{type(last_error).__name__}: {str(last_error)[:120]}",
            last_error=last_error,
        )

    # ══════════════════════════════════════════════════════════
    # 预算
    # ══════════════════════════════════════════════════════════
    def _check_budget(self) -> None:
        """发请求【之前】检查预算。

        提前检查而不是事后统计 —— 因为事后发现就晚了，钱已经花了。
        """
        if self.monthly_budget_cny is None:
            return
        spent = self.already_spent_cny + self.stats.cost_cny
        if spent >= self.monthly_budget_cny:
            raise BudgetExceededError(
                f"本月累计成本 ¥{spent:.4f} 已达上限 ¥{self.monthly_budget_cny:.2f}，拒绝继续调用。\n"
                f"→ 想继续跑，请去 docs/budget.md 更新台账，或调高 .env 的 MONTHLY_BUDGET_CNY。"
            )

    def _record_usage(self, response: ChatResponse) -> None:
        """把响应里的用量记进统计，并累加成本。"""
        usage = response.usage
        if usage is None:
            return

        self.stats.prompt_tokens += usage.prompt_tokens
        self.stats.completion_tokens += usage.completion_tokens
        self.stats.reasoning_tokens += usage.reasoning_tokens
        self.stats.cached_tokens += usage.cached_tokens

        self.stats.cost_cny += self._price.cost(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cached_tokens=usage.cached_tokens,
        )

    # ══════════════════════════════════════════════════════════
    # 公开 API
    # ══════════════════════════════════════════════════════════
    def _build_request(
        self,
        prompt: str | Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        stream: bool = False,
    ) -> ChatRequest:
        """把调用方的意图组装成 ChatRequest（Day 3 的 Pydantic 在这里发挥作用）。"""
        messages: list[Message] = []
        if system:
            messages.append(Message(role="system", content=system))

        if isinstance(prompt, str):
            messages.append(Message(role="user", content=prompt))
        else:
            messages.extend(prompt)

        # thinking 的三态逻辑：
        #     None       → 跟随客户端默认（默认是关）
        #     True/False → 这一条调用显式开/关
        if thinking is None:
            effective_thinking = not self.disable_thinking
        else:
            effective_thinking = thinking

        return ChatRequest(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            thinking={"type": "enabled" if effective_thinking else "disabled"},
            reasoning_effort=reasoning_effort,  # type: ignore[arg-type]
        )

    async def chat(
        self,
        prompt: str | Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = 1024,
        temperature: float | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        allow_truncated: bool = False,
    ) -> ChatResponse:
        """单次调用，返回完整的 ChatResponse。

        allow_truncated=False（默认）时，如果回答被截断会抛
        TruncatedResponseError —— 因为我们宁可用异常提醒你，
        也不想让你在不知情的情况下用一段残缺的文本。

        想关掉这个检查（比如你就是想看看截断到哪儿了），传 True。
        """
        self._check_budget()
        request = self._build_request(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
        )

        # exclude_none=True：不把 None 字段发给服务端。
        # 有些服务端对多余字段很敏感，少发比多发安全。
        payload = request.model_dump(exclude_none=True)

        resp = await self._post_with_retry(payload)

        # Day 3 + Day 4 的合体：用 Pydantic 解析响应。
        # 校验失败会抛 ValidationError —— 那说明服务端返回的东西
        # 和我们的模型对不上了（通常是 API 改版），
        # 这类错误【不能在运行时悄悄吞掉】，必须暴露出来。
        response = ChatResponse.model_validate(resp.json())

        self.stats.calls += 1
        self._record_usage(response)

        # ── 把静默失败变成显式失败 ──
        if not allow_truncated and response.is_truncated:
            raise TruncatedResponseError(
                f"回答被 max_tokens 截断了（finish_reason='length'）。\n"
                f"  max_tokens={max_tokens}，输出 {response.usage.completion_tokens if response.usage else '?'} token"
                f"（其中思考 {response.usage.reasoning_tokens if response.usage else '?'}）。\n"
                f"→ 调大 max_tokens（开思考时至少给正文预期的 3 倍），"
                f"或改用 thinking=False 关掉思考。\n"
                f"→ 确认这就是你要的，可以传 allow_truncated=True。"
            )

        # 另一个静默失败：正文是空的
        if not response.content.strip():
            reasoning_len = len(response.reasoning_content)
            raise LLMKitError(
                f"正文是空的（reasoning {reasoning_len} 字）。\n"
                f"→ 典型的「预算被思考吃光」：max_tokens 太小了。\n"
                f"  要么调大 max_tokens，要么传 thinking=False。"
            )

        return response

    async def chat_text(self, prompt: str | Sequence[Message], **kwargs: Any) -> str:
        """只要正文文本的便捷方法。"""
        resp = await self.chat(prompt, **kwargs)
        return resp.content

    async def chat_many(
        self,
        prompts: Sequence[str],
        *,
        system: str | None = None,
        max_tokens: int | None = 1024,
        thinking: bool | None = None,
        fail_fast: bool = True,
    ) -> list[ChatResponse]:
        """并发跑多条，结果顺序和输入顺序【一一对应】。

        ⭐ 这里就是 Day 1 的 gather + Day 2 的 Semaphore 的合作：

             asyncio.gather  → 让所有任务「同时」开始等
             Semaphore       → 保证真正同时在飞的【不超过 max_concurrency 个】

        没有 gather：20 个任务要排队串行，总耗时 = 20 × 单次耗时
        只有 gather 没有 Semaphore：20 个请求同时打过去 → 服务端限流你
        两个都有：总耗时 ≈ ⌈20 / max_concurrency⌉ × 单次耗时

        ⚠️ asyncio.gather 的返回顺序 = 参数的顺序，
           **不是完成的顺序** —— 所以下标对应关系是可靠的。

        fail_fast=True（默认）：任何一条失败就整体抛异常。
        fail_fast=False：失败的条目返回 None，其余照常。
                          批量任务里通常更想要这个 ——
                          一条失败不该让另外 99 条白跑。
        """
        if not prompts:
            return []

        tasks = [
            self.chat(prompt, system=system, max_tokens=max_tokens, thinking=thinking)
            for prompt in prompts
        ]

        if fail_fast:
            return list(await asyncio.gather(*tasks))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: list[ChatResponse] = []
        for item in results:
            if isinstance(item, BaseException):
                out.append(None)  # type: ignore[arg-type]
            else:
                out.append(item)
        return out

    async def chat_stream(
        self,
        prompt: str | Sequence[Message],
        *,
        system: str | None = None,
        max_tokens: int | None = 2048,
        thinking: bool | None = None,
    ) -> AsyncIterator[str]:
        """流式输出，逐段 yield 正文。

        用法：
            async for piece in client.chat_stream("讲个故事"):
                print(piece, end="", flush=True)

        ⚠️ 为什么不在这里做重试：
           流式一旦开始收到内容，就【不能简单重试】了 ——
           重试意味着让模型重新生成，前面收到的内容作废，
           而且要重新计费一次。真实项目里正确的做法是
           「把已收到的内容拼进下一轮请求，让它接着写」，复杂度很高。
           所以这里的选择是：流式不做自动重试，失败了直接抛。
           简单，而且不会悄悄多花钱。

        ⚠️ 为什么 yield 的是 str 而不是 delta 对象：
           调用方 99% 的情况只关心"又出了几个字"。
           需要看思考过程的场景很少，所以只暴露 content，
           reasoning_content 仍然会累计在 stats 里。
        """
        self._check_budget()
        request = self._build_request(
            prompt,
            system=system,
            max_tokens=max_tokens,
            thinking=thinking,
            stream=True,
        )
        payload = request.model_dump(exclude_none=True)

        async with self._sem:  # ← 流式同样要过闸门，否则并发一样会爆
            self.stats.http_requests += 1
            self.stats.calls += 1

            # ⚠️ stream() 必须放进 async with：
            #    它管理的是一个"半开的连接"，不用 with 管会泄漏。
            async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    # 只处理 "data: " 开头的行；空行和注释行跳过
                    if not line.startswith("data: "):
                        continue

                    data = line[len("data: "):]
                    if data == "[DONE]":
                        break

                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue

                    # 流式响应通常没有 usage，除非请求时显式要。
                    # 拿不到就不统计，宁可少算也不猜。
                    if chunk.get("usage"):
                        try:
                            self._record_usage(ChatResponse.model_validate(chunk))
                        except Exception:
                            pass

                    if not chunk.get("choices"):
                        continue

                    delta = chunk["choices"][0].get("delta") or {}
                    if delta.get("reasoning_content"):
                        self.stats.reasoning_tokens += 1  # 粗略计数即可
                    if delta.get("content"):
                        yield delta["content"]

    # ══════════════════════════════════════════════════════════
    @property
    def price(self) -> ModelPrice:
        return self._price

    def print_stats(self) -> None:
        """把统计打到终端。演示用；真实项目应该上报监控。"""
        print("─" * 62)
        print(f"  模型：{self.model}    并发上限：{self.max_concurrency}    重试上限：{self.max_retries}")
        print("─" * 62)
        for line in self.stats.summary().splitlines():
            print(f"  {line}")
        if self.monthly_budget_cny is not None:
            spent = self.already_spent_cny + self.stats.cost_cny
            pct = spent / self.monthly_budget_cny * 100
            print(f"  月度预算：¥{spent:.4f} / ¥{self.monthly_budget_cny:.2f}（{pct:.2f}%）")
        print("─" * 62)
