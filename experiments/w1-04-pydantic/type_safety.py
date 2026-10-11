"""
W1 Day 3：类型标注 + Pydantic v2 —— 把类型检查搬到运行时

━━━ 想搞清楚什么 ━━━

Python 的类型标注（`def f(x: int) -> str`）**运行时完全不检查**。
它只是给人和 IDE 看的注释。写错了，程序照样跑，
一路漏到很深处，才以你完全没想到的方式炸掉。

Pydantic 补上了这一块：把类型标注变成**运行时真的会执行**的校验，
并且顺带给你：默认值、范围约束、自定义规则、自动转换、结构化报错。

这是后面 llmkit/client.py 的地基 —— 请求参数、响应结构、配置读取，
全都交给它管。

━━━ 五个演示 ━━━

    ① 类型标注只是注释        add('3', '4') 居然能跑
    ② 裸 dict 的代价          错误要等一次网络往返才暴露
    ③ Pydantic 在入口拦住     报错精确到字段
    ④ 自动转换                方便，但要知道它的边界
    ⑤ 读 .env                 配置变成强类型对象

运行：
    python type_safety.py
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录下的 .env（本文件位于 experiments/w1-04-pydantic/ 里）
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def section(title: str) -> None:
    print()
    print("=" * 62)
    print(title)
    print("=" * 62)


# ============================================================
# ① 类型标注在运行时「不存在」
# ============================================================

def add(x: int, y: int) -> int:
    """签名上写了：要两个 int，返回 int。"""
    return x + y


def demo_1_annotations() -> None:
    section("① 类型标注只是「注释」，运行时根本不检查")

    print(f"    add(3, 4)      = {add(3, 4)!r}")
    print(f"    add('3', '4')  = {add('3', '4')!r}      ← 字符串拼接，没报错")
    print(f"    add([1], [2])  = {add([1], [2])!r}      ← 列表相加，也没报错")
    print()
    print("    Python 不会因为你写错类型就拦住你。错误会一路漏下去，")
    print("    在某段你根本没想到的代码里，以很奇怪的方式炸掉。")
    print()
    print("    → IDE 和 mypy 能帮你，但它们都是「静态」的，管不到运行时。")


# ============================================================
# ② 裸 dict：错误只能等后端告诉你
# ============================================================

def send_naive(cfg: dict) -> dict:
    """模拟一次真实的 API 调用：只有服务端才会做校验。

    你唯一能做的，就是等一个 400 回来。
    """
    if not cfg.get("messages"):
        return {"error": "400 messages is required"}
    if not (0.0 <= cfg.get("temperature", 0.7) <= 2.0):
        return {"error": "400 temperature must be in [0, 2]"}
    return {"ok": True, "model": cfg.get("model")}


def demo_2_naive_dict() -> None:
    section("② 裸 dict：错误要等一次网络往返才暴露")

    bad = {"model": "deepseek-chat", "messages": [], "temperature": 3.5}
    print(f"    传进去的配置: {bad}")
    print(f"    后端返回:     {send_naive(bad)}")
    print()
    print("    注意 —— 请求【已经发出去了】。真实场景里这意味着：")
    print("      · 一次网络往返的时间（几百毫秒，甚至超时）")
    print("      · 可能一次计费")
    print("      · 一个你本可以提前一秒就知道的错误")


# ============================================================
# ③ Pydantic：在构造对象的那一刻就拦住
# ============================================================

class Message(BaseModel):
    """对话中的一条消息。"""

    role: Literal["system", "user", "assistant"]
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content 不能是空白字符串")
        return v


class ChatRequest(BaseModel):
    """一次 LLM 对话请求的完整参数。

    这些约束全部写在「声明」里 —— 不用手写一堆 if/else 校验。
    """

    model: str = Field(min_length=1, description="模型名")
    messages: list[Message] = Field(min_length=1, description="对话历史，至少一条")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="采样温度")
    max_tokens: int | None = Field(default=None, gt=0, description="最大生成 token 数")
    stream: bool = False


def show_errors(e: ValidationError) -> None:
    """把 Pydantic 的报错打印成能一眼看懂的样子。"""
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(根)"
        print(f"        × {loc:<12} {err['msg']}")


def demo_3_pydantic() -> None:
    section("③ Pydantic：在构造对象的那一刻就拦住")

    print("    [a] 正常构造")
    req = ChatRequest(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "你好"}],
        temperature=0.5,
    )
    print(f"        {req}")
    print()

    print("    [b] messages 为空 + temperature 超范围（一次报两个错）")
    try:
        ChatRequest(model="deepseek-chat", messages=[], temperature=3.5)
    except ValidationError as e:
        show_errors(e)
    print()

    print("    [c] role 拼错 —— Literal 只认 system / user / assistant")
    try:
        ChatRequest(model="x", messages=[{"role": "assistent", "content": "hi"}])
    except ValidationError as e:
        show_errors(e)
    print()

    print("    [d] 自定义规则：content 是空白字符串")
    try:
        ChatRequest(model="x", messages=[{"role": "user", "content": "   "}])
    except ValidationError as e:
        show_errors(e)
    print()

    print("    [e] 校验通过之后，一行就能转成可以直接发出去的 JSON")
    req = ChatRequest(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "你好"}],
        temperature=0.5,
        max_tokens=256,
    )
    print(f"        model_dump_json() → {req.model_dump_json()}")
    print(f"        model_dump()      → {req.model_dump()}")


# ============================================================
# ④ 自动转换：方便，但要清楚它的边界
# ============================================================

def demo_4_coercion() -> None:
    section("④ 自动转换：方便，但要知道它的边界")

    req = ChatRequest.model_validate({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": "0.3",     # 注意：这里是字符串
        "max_tokens": "1024",     # 这里也是字符串
    })
    print(f"    temperature = {req.temperature!r}   类型: {type(req.temperature).__name__}")
    print(f"    max_tokens  = {req.max_tokens!r}   类型: {type(req.max_tokens).__name__}")
    print(f"    messages[0] = {req.messages[0]!r}")
    print("                  ↑ 嵌套的 dict 自动变成了 Message 对象")
    print()
    print("    这种「猜」在处理 JSON 时很方便（JSON 里数字和字符串常常混着来），")
    print("    但也意味着 '0.3' 和 0.3 在你眼里变得一样了。")
    print()
    print("    想禁止猜，就开 strict 模式：")
    try:
        ChatRequest.model_validate(
            {
                "model": "x",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": "0.3",
            },
            strict=True,
        )
    except ValidationError as e:
        show_errors(e)


# ============================================================
# ⑤ pydantic-settings：把 .env 读成强类型对象
# ============================================================

class Settings(BaseSettings):
    """项目配置。

    字段名用小写，会自动匹配 .env 里的大写环境变量：
        deepseek_api_key  ←  DEEPSEEK_API_KEY
    """

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",           # .env 里有多余字段也不报错
        case_sensitive=False,
    )

    # 三家 provider（均提供 OpenAI 兼容接口）
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    # 应用配置
    default_model: str = "glm-4.7-flash"
    monthly_budget_cny: float = 100.0
    log_level: str = "INFO"


def mask(secret: str) -> str:
    """只显示长度和极少的前缀，绝不让密钥进日志。

    真实项目里，「日志把 key 打出来」是最常见的翻车方式之一 ——
    一张截图、一次 CI 日志外泄，key 就没了。
    所以显示到「能分辨用的是哪个 key」为止，就够了。
    """
    if not secret:
        return "(未设置)"
    return f"{secret[:3]}…  共 {len(secret)} 字符"


def demo_5_settings() -> None:
    section("⑤ pydantic-settings：把 .env 读成强类型对象")

    print(f"    读的配置文件: {ENV_FILE}")
    print()

    s = Settings()
    print(f"    deepseek_api_key   = {mask(s.deepseek_api_key)}")
    print(f"    zhipu_api_key      = {mask(s.zhipu_api_key)}")
    print(f"    deepseek_base_url  = {s.deepseek_base_url}")
    print(f"    default_model      = {s.default_model!r}")
    print(f"    monthly_budget_cny = {s.monthly_budget_cny}   "
          f"类型: {type(s.monthly_budget_cny).__name__}")
    print()
    print("    注意 monthly_budget_cny：.env 里写的是字符串 '100'，")
    print("    到这里已经是真正的 float。类型转换、默认值、缺失处理，一次搞定。")
    print()
    print("    ⚠  .env 里是真实密钥，绝不能提交到 git（已经写在 .gitignore 里了）")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    demo_1_annotations()
    demo_2_naive_dict()
    demo_3_pydantic()
    demo_4_coercion()
    demo_5_settings()

    section("小结")
    print("    ① 类型标注 = 给人和 IDE 看的注释，运行时不管")
    print("    ② Pydantic  = 把标注变成运行时真的会执行的校验")
    print("    ③ 越早拦住错误，代价越小：构造时 < 发请求后 < 半夜线上")
    print("    ④ 声明式的约束，比手写一长串 if/else 更少出错、报错更清楚")
    print("    ⑤ 这套东西就是 llmkit/client.py 的地基")
