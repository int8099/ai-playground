"""llmkit —— 自研 LLM 工具包。

从零实现多模型统一调用、结构化输出、工具调用、重试降级与成本统计。
不依赖 LangChain，目的是理解协议细节，而不是调包。

────────────────────────────────────────────────────────────
当前进度：W1 完成「客户端内核」
────────────────────────────────────────────────────────────

已实现（W1）：
    · 异步 HTTP 调用（httpx，连接池复用 + 四段超时）
    · 并发控制（asyncio.Semaphore 闸门）
    · 失败重试（指数退避 + full jitter，含 429 的 Retry-After 支持）
    · 错误分类（可重试 / 不可重试，见 client.is_retryable）
    · 类型校验（Pydantic v2，请求与响应双向）
    · 流式输出（SSE）
    · 成本统计 + 月度预算硬上限
    · 启动时模型名校验（防「静默替换」）

规划中（W2 及以后）：
    · 装饰器实现重试（把现在写死在 client 里的重试抽出来，复用）
    · 测试（pytest + respx 打桩，不烧真钱）
    · 多厂商适配（DeepSeek / 百炼 / 智谱统一接口）

────────────────────────────────────────────────────────────
快速上手
────────────────────────────────────────────────────────────

    import asyncio
    from llmkit import LLMClient

    async def main():
        async with LLMClient() as client:
            await client.verify_models()               # 启动自检，免费
            print(await client.chat_text("你好"))

            answers = await client.chat_many(["问题一", "问题二"])
            for a in answers:
                print(a.content)

            async for piece in client.chat_stream("讲个短故事"):
                print(piece, end="", flush=True)

            client.print_stats()

    asyncio.run(main())
"""

from .client import (
    NON_RETRYABLE_STATUS,
    RETRYABLE_STATUS,
    BudgetExceededError,
    ClientStats,
    LLMClient,
    LLMKitError,
    ModelMismatchError,
    RetryExhaustedError,
    TruncatedResponseError,
    is_retryable,
)
from .models import (
    PRICES,
    ChatRequest,
    ChatResponse,
    Choice,
    FinishReason,
    Message,
    ModelPrice,
    ReasoningEffort,
    Role,
    ThinkingConfig,
    ThinkingType,
    Usage,
    price_of,
)

__version__ = "0.1.0"

__all__ = [
    # 核心
    "LLMClient",
    "ClientStats",
    # 模型
    "Message",
    "ChatRequest",
    "ChatResponse",
    "Choice",
    "Usage",
    "ThinkingConfig",
    "ModelPrice",
    "PRICES",
    "price_of",
    # 类型别名
    "Role",
    "FinishReason",
    "ThinkingType",
    "ReasoningEffort",
    # 异常
    "LLMKitError",
    "ModelMismatchError",
    "TruncatedResponseError",
    "BudgetExceededError",
    "RetryExhaustedError",
    # 错误分类
    "is_retryable",
    "RETRYABLE_STATUS",
    "NON_RETRYABLE_STATUS",
]
