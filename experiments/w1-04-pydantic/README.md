# W1-04：类型标注 + Pydantic v2

> 本文件已填好全部答案。

## 想搞清楚什么

Python 的类型标注（`def f(x: int) -> str`）**运行时完全不检查**。它只是给人和 IDE 看的注释。

写错了，程序照样跑 —— 一路漏到很深处，才以你完全没想到的方式炸掉。

Pydantic 补上了这一块：把类型标注变成**运行时真的会执行**的校验，并顺带给你默认值、范围约束、自定义规则、自动转换、结构化报错。

这是后面 `llmkit/client.py` 的地基 —— 请求参数、响应结构、配置读取，全都交给它管。

## 怎么跑

依赖已经装进项目的 `.venv` 了（由 uv 管理），PyCharm 指向这个 `.venv` 就能直接跑。

**PyCharm**：目录树里右键 `type_safety.py` → `Run 'type_safety'`

**命令行**：

```bash
cd experiments/w1-04-pydantic
python type_safety.py
```

如果换台机器重来，先装依赖：

```bash
uv add --project D:/code/ai-playground pydantic pydantic-settings
```

## 五个演示，各说明什么

### ① 类型标注只是「注释」

```python
def add(x: int, y: int) -> int:
    return x + y

add("3", "4")    # → '34'  没报错！
add([1], [2])    # → [1, 2]  也没报错！
```

**Python 不会因为你写错类型就拦住你。** 标注的价值在「给人看」和「给 IDE / mypy 看」，两者都是**静态**的，管不到运行时。

### ② 裸 dict：错误要等一次网络往返才暴露

```python
bad = {"model": "deepseek-chat", "messages": [], "temperature": 3.5}
send_naive(bad)   # → 请求已经发出去了，才等到一个 400
```

代价：一次网络往返、可能一次计费、一段本可以省掉的等待。

### ③ Pydantic：构造对象的那一刻就拦住

```python
ChatRequest(model="deepseek-chat", messages=[], temperature=3.5)
```

一秒都不用等，立刻报出两个错，而且**精确到字段**：

```
× messages     List should have at least 1 item after validation, not 0
× temperature  Input should be less than or equal to 2
```

role 拼错时更明显 —— `Literal` 会告诉你合法值有哪些：

```
× messages.0.role  Input should be 'system', 'user' or 'assistant'
```

这就是「声明式校验」比「手写 if/else」强的地方：**约束写在字段定义旁边，报错自动带上路径和原因。**

### ④ 自动转换：方便，但要知道边界

```python
ChatRequest.model_validate({
    "temperature": "0.3",     # 字符串
    "max_tokens": "1024",     # 字符串
    ...
})
# → temperature = 0.3 (float)，max_tokens = 1024 (int)
```

嵌套的 dict 也会自动变成 `Message` 对象。

处理 JSON 时这很方便（JSON 里数字和字符串常常混着来），但代价是 `'0.3'` 和 `0.3` 在你眼里变一样了。想禁止这种「猜」：

```python
ChatRequest.model_validate(data, strict=True)   # 字符串 '0.3' 会被拒绝
```

### ⑤ pydantic-settings：把 .env 读成强类型对象

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    deepseek_api_key: str = ""
    monthly_budget_cny: float = 100.0
```

字段名小写，自动匹配 `.env` 里的大写环境变量（`deepseek_api_key` ← `DEEPSEEK_API_KEY`，大小写不敏感）。

`.env` 里写的是字符串 `'100'`，到这里已经是真正的 `float`。**类型转换、默认值、缺失处理，一次搞定。**

## Pydantic v2 速查表

| 需求 | 写法 |
| --- | --- |
| 定义模型 | `class X(BaseModel):` |
| 必填字段 | `name: str` |
| 带默认值 | `temperature: float = 0.7` |
| 数值范围 | `Field(ge=0.0, le=2.0)` |
| 长度 / 非空 | `Field(min_length=1)`（对 str 是长度，对 list 是元素数） |
| 枚举式取值 | `role: Literal["system", "user", "assistant"]` |
| 可空 | `max_tokens: int \| None = None` |
| 自定义校验 | `@field_validator("content")` + `@classmethod` |
| 从 dict 构造 | `X.model_validate(d)` |
| 转 dict | `x.model_dump()` |
| 转 JSON | `x.model_dump_json()` |
| 严格模式 | `X.model_validate(d, strict=True)` |
| 嵌套模型 | 直接写类型就行，传入的 dict 会自动转换 |

## 错误的四个层次

做这个实验时想清楚一件事：**错误越早暴露越便宜。**

| 在哪拦住 | 什么时候发现 | 代价 |
| --- | --- | --- |
| IDE / mypy（静态） | 写代码时 | 0 |
| **Pydantic（运行时）** | **构造对象时** | **微秒级** |
| 服务端校验 | 发请求之后 | 几百毫秒 + 可能计费 |
| 线上炸 | 半夜 | 最贵 |

Pydantic 的位置很关键：它是**最后一个不花钱的关卡**。

## 踩的坑

> **坑一：别把密钥打进日志。**
> 我第一版 `mask()` 写的是显示头 6 位 + 尾 4 位，跑出来是 `sk-e91...1f22`。
> 看起来挺谨慎，其实已经泄露了 10 个字符 —— 一张截图、一次 CI 日志外泄就够出事。
>
> 改成只显示前 3 位 + 总长度（`sk-…  共 35 字符`）：既能分辨「用的是哪个 key」，又几乎不泄露信息。
>
> **教训**：日志里脱敏，标准是「能区分身份」，不是「看起来打码了」。

> **坑二（外部变更）：`.env` 里的 `DEFAULT_MODEL=deepseek-chat` 已经失效。**
> DeepSeek 官方在 **2026-07-24 15:59 UTC** 永久下线了 `deepseek-chat` 和 `deepseek-reasoner` 两个别名，
> 调用会直接报错，没有宽限期、没有软跳转。
>
> 官方给出的迁移目标（**价格不变**）：
> ```
> deepseek-chat      → deepseek-v4-flash（非思考模式）
> deepseek-reasoner  → deepseek-v4-flash（思考模式，是请求参数不是换模型）
> ```
> 注意**不要**顺手改成 `deepseek-v4-pro` —— 那是另一个更贵的档位（约 3.1 倍），不是迁移目标。
>
> base_url 和请求格式都没变，只需要改 model 名。
>
> **教训**：模型名是外部依赖，会过期。写代码时把「模型名」放进配置里（我们就是这么做的），
> 换的时候改一行 `.env` 就行，不用到处找硬编码。

## 自查清单

- [x] 说得出「类型标注」和「运行时校验」的区别
- [x] 知道 `add("3", "4")` 为什么不报错
- [x] 会用 `Field(ge=..., le=..., min_length=...)` 声明约束
- [x] 会用 `@field_validator` 写自定义规则
- [x] 知道 `model_validate` / `model_dump` / `model_dump_json` 各自干什么
- [x] 知道 strict 模式是干什么的，什么时候该开
- [x] 会用 pydantic-settings 读 `.env`，并知道 `.env` 绝不能提交
- [x] 知道「错误越早暴露越便宜」的四个层次
