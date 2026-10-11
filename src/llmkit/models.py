"""
llmkit.models —— 数据模型层
================================================================

这一层只干一件事：把「大模型 API 的请求和响应」用类型写清楚。

为什么值得单独一层：
    Day 3 学过「错误的四个层次」——IDE/mypy → Pydantic → 服务端 → 线上。
    这一层就是第二个层次：让格式错误在【本地、微秒级】就被拦住，
    而不是发出去几百毫秒、付了钱之后才发现。

    具体到这里，它能拦住这几类真实事故：
        · 忘了写 role                     → 构造时直接报错
        · role 写成了 "User"（大小写）     → 构造时直接报错
        · temperature 传了 5.0             → 构造时直接报错
        · messages 传了空列表              → 构造时直接报错
        · 把 dict 直接当对象用、拼错字段名  → IDE 就标红
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ══════════════════════════════════════════════════════════════
# 常量：从官方文档抄下来的，不是猜的
# ══════════════════════════════════════════════════════════════
# 对话角色。用 Literal 而不是 str —— 这样写错一个字母 IDE 就报错。
# 来源：OpenAI Chat Completions 兼容格式
Role = Literal["system", "user", "assistant"]

# finish_reason 的取值。其中 "length" 必须在业务里当成【异常】处理，
# 因为它意味着回答被截断了，但 HTTP 状态码还是 200 —— 典型的静默失败。
FinishReason = Literal["stop", "length", "content_filter", "tool_calls", "insufficient_system_resource"]

# 思考模式的开关。DeepSeek V4 默认开启，思考 token 也计费。
ThinkingType = Literal["enabled", "disabled"]

# 思考强度。官方映射表（来源：api-docs.deepseek.com/guides/thinking_mode）：
#     low → low    medium → high    high → high    xhigh → high    max → max
# 注意 medium / xhigh 都会被吞成 high —— 只有 low 和 max 真正有效。
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]


# ══════════════════════════════════════════════════════════════
# 请求侧
# ══════════════════════════════════════════════════════════════
class Message(BaseModel):
    """一条对话消息。

    ⚠️ content 允许为空字符串 —— 这不是偷懒，是有原因的：
       推理模型在思考模式下的响应里，assistant 消息的 content
       可能【真的是空的】（预算全被 reasoning_content 吃光）。
       如果这里强制非空，我们就没法解析这种响应了。
       真正的非空校验放在 ChatRequest 里做。
    """

    role: Role
    content: str = ""

    # 下面两个字段只会出现在【响应】里，请求时不用填。
    # 放在同一个模型里是为了让「响应 → 消息 → 下一轮请求」的复用更顺。
    reasoning_content: str | None = None
    name: str | None = None


class ThinkingConfig(BaseModel):
    """思考模式开关。对应请求体里的 "thinking" 字段。"""

    type: ThinkingType = "disabled"


class ChatRequest(BaseModel):
    """发往 /chat/completions 的请求体。

    字段名必须和服务端约定完全一致 —— 这就是「OpenAI 兼容」的全部秘密，
    没有别的魔法。改了名字服务端就不认识。
    """

    model: str = Field(min_length=1, description="模型名，必须和服务端 /models 列出的完全一致")

    messages: list[Message] = Field(min_length=1, description="对话历史，至少一条")

    max_tokens: int | None = Field(
        default=None,
        gt=0,
        description="生成上限。⚠️ 开思考时至少要给正文预期的 3 倍，否则正文可能一个字都出不来",
    )

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="采样温度。⚠️ 思考模式下此参数【无效且不报错】",
    )

    stream: bool = False

    thinking: ThinkingConfig | None = Field(
        default=None,
        description="思考模式开关。不传 = 服务端默认（DeepSeek V4 是 enabled）",
    )

    reasoning_effort: ReasoningEffort | None = Field(
        default=None,
        description="思考强度。只有 low 和 max 真正有效，medium/xhigh 会被映射成 high",
    )


# ══════════════════════════════════════════════════════════════
# 响应侧
# ══════════════════════════════════════════════════════════════
class Usage(BaseModel):
    """token 用量。这是账单的唯一依据，所以每个字段都留着。

    ⚠️ reasoning_tokens 单独拎出来，是因为它经常占输出的大头
       （实验 04 实测：97%），不看这个数就不知道自己钱花在哪。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # 这两个是嵌套的 dict，服务端可能不返回、也可能加新字段。
    # 用 dict[str, Any] 而不是精确定义，是为了【今晚的服务端加字段时程序不会崩】。
    completion_tokens_details: dict[str, Any] | None = None
    prompt_tokens_details: dict[str, Any] | None = None

    @property
    def reasoning_tokens(self) -> int:
        """思考消耗的 token（没有就是 0）。"""
        details = self.completion_tokens_details or {}
        try:
            return int(details.get("reasoning_tokens", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def cached_tokens(self) -> int:
        """命中缓存的输入 token（缓存价通常只有原价的 1/50）。"""
        details = self.prompt_tokens_details or {}
        try:
            return int(details.get("cached_tokens", 0) or 0)
        except (TypeError, ValueError):
            return 0


class Choice(BaseModel):
    """一个候选结果。

    .message 是「非流式」和「流式收尾」用的；
    .delta 是「流式中间包」用的。两者不会同时有值。
    """

    index: int = 0
    message: Message | None = None
    delta: dict[str, Any] | None = None
    finish_reason: str | None = None


class ChatResponse(BaseModel):
    """整个响应体。"""

    id: str | None = None
    model: str | None = None
    choices: list[Choice] = Field(min_length=1)
    usage: Usage | None = None
    system_fingerprint: str | None = None

    # ── 三个便利属性：把「层层取值」变成一次属性访问 ──
    # 没有这一层的话，调用方到处写
    #     resp["choices"][0]["message"]["content"]
    # 一旦结构变了，要改 N 个地方。

    @property
    def content(self) -> str:
        """正文。可能是空字符串 —— 这是合法状态，见 Message 的说明。"""
        if not self.choices:
            return ""
        msg = self.choices[0].message
        return (msg.content if msg else "") or ""

    @property
    def reasoning_content(self) -> str:
        """思考过程。"""
        if not self.choices:
            return ""
        msg = self.choices[0].message
        return (msg.reasoning_content if msg else "") or ""

    @property
    def finish_reason(self) -> str | None:
        return self.choices[0].finish_reason if self.choices else None

    @property
    def is_truncated(self) -> bool:
        """回答是不是被 max_tokens 截断了。

        ⚠️ 这个方法存在的意义：把「静默失败」变成「可检测的失败」。
           HTTP 200 + finish_reason=length 就是典型的静默失败 ——
           状态码一切正常，但内容是不完整的。
        """
        return self.finish_reason == "length"


# ══════════════════════════════════════════════════════════════
# 模型价格表
# ══════════════════════════════════════════════════════════════
class ModelPrice(BaseModel):
    """单价，单位：元 / 百万 token。"""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0

    def cost(self, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
        """算一次调用的钱（元）。

        缓存命中的部分按缓存价算，未命中的按原价 ——
        这是两家的通用计费方式，所以这里显式区分。
        """
        billable_input = max(prompt_tokens - cached_tokens, 0)
        return (
            billable_input * self.input_per_million
            + cached_tokens * self.cached_input_per_million
            + completion_tokens * self.output_per_million
        ) / 1_000_000


# ⚠️ 单价是【量级参考】，会变。真实扣费一律以控制台账单为准。
# 核实日期 2026-10-11，来源：docs/budget.md
PRICES: dict[str, ModelPrice] = {
    "deepseek-flash": ModelPrice(
        input_per_million=1.1,
        output_per_million=4.3,
        cached_input_per_million=0.02,
    ),
    "deepseek-v4-pro": ModelPrice(
        input_per_million=4.8,
        output_per_million=14.3,
        cached_input_per_million=0.16,
    ),
}

# 未知模型时用的保守价 —— 宁可高估，也别让预算统计失真。
FALLBACK_PRICE = ModelPrice(input_per_million=5.0, output_per_million=15.0)


def price_of(model: str) -> ModelPrice:
    """查单价。查不到就用保守的兜底价。"""
    return PRICES.get(model, FALLBACK_PRICE)
