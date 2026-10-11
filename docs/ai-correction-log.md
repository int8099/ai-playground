# AI 纠错日志

> 每天 1 条：**AI 给错的地方 + 我如何判断它错了 + 正确做法**。
>
> 为什么记这个：面试时「你能识别 AI 输出的错误吗」这个问题，只有这份日志能自证。
> 目标：积累 100+ 条。

---

## 模板

```
### YYYY-MM-DD

- 场景：
- AI 给出的（错误）内容：
- 我如何发现有错：
- 正确做法：
- 涉及知识点：
```

---

## 记录

<!-- 从下面开始按日期追加，最新的放最上面 -->

### 2026-10-11（第 6 条：我自己设计的对照实验一次改了两个变量）

- 场景：写 `scripts/llmkit_demo.py` 的「静默失败防护」演示
- 我给出的（错误）内容：设计成「同样的 `max_tokens=32`，开着思考会截断，
  关掉思考就能成功」—— 想用这个对比说明思考 token 挤占正文预算。
- 我如何发现有错：实跑时**场景 B 也报截断了**。原因是我同时动了两个变量：
  ① thinking 开关；② 答案所需长度（原问题「请详细说明什么是 HTTP 协议」
  本来就不止 32 个 token）。所以"关掉思考就成功"这个预期根本不成立。
- 正确做法：
  - 固定问题为短问题（「用不超过 30 个字说明什么是 HTTP 404」）+
    固定 `max_tokens=64`，**只改 thinking 一个变量**；
  - 改完实测：开思考 → 截断；关思考 → 输出 10 token 成功。结论这才立住。
  - 另外把第三幕的「放行截断」场景也改了 —— 原来 `max_tokens=16`
    配上短问题恰好不截断，演示不出效果，改成问一个注定写不完的问题。
- 涉及知识点：
  - **对照实验一次只改一个变量**。这条在数学建模里也成立 ——
    两个变量同时动，你无法归因，得出的"规律"可能是假的。
  - 写实验时先跑一遍验证假设，不要凭"觉得应该会"就写进结论。
    （这条已经第 N 次救我了，见 2026-10-10 第 2 条。）

### 2026-10-11（第 5 条：模型名写错不报错，被静默替换）

- 场景：Day 4 要给 `.env` 配 `DEFAULT_MODEL` 并写真实调用代码
- 我此前给出的（错误）内容：告诉用户「旧模型下线后，迁移目标是
  `deepseek-v4-flash`，价格不变」，并据此把 `.env` 和 `.env.example`
  都改成了 `deepseek-v4-flash`
- 我如何发现有错：
  1. 先跑一个**免费的** `GET /models` 端点核对，服务端实际只列出
     `['deepseek-flash', 'deepseek-v4-pro']` —— 名字对不上；
  2. 拿 `deepseek-v4-flash` 发真实请求验证：**返回 200，不报错**，
     但响应体的 `model` 字段变成了 `deepseek-flash`；
  3. 查官方文档确认：`deepseek-v4-flash` 属于 legacy name，
     「仍被接受，但对应模型已退役，请求由 V4.1-Flash 服务并按 Flash 价格计费」。
- 正确做法：
  - 正确名字是 **`deepseek-flash`**（没有 `v4`）；已修正 `.env` / `.env.example`
    / `docs/budget.md`；
  - 写进 `llmkit`：`client.verify_models()` 在启动时调一次 `GET /models`
    核对，对不上直接抛 `ModelMismatchError`；
  - 顺带发现：**完全瞎写的模型名反而会老实报 400**，并列出可用名字 ——
    所以「差一点点」的旧名字才是最危险的那类。
- 涉及知识点：
  - **「不报错」不等于「做对了」。** 这是本日志反复出现的模式（见
    2026-10-10 第 1 条：编造的镜像地址）。
  - 模型名这类"外部事实"不要凭记忆或旧笔记写，
    能问服务端就问服务端 —— 而且这类端点通常是免费的。
  - 危险的不是报错，是**静默降级**：它会让你的对比实验得出错误结论
    （两个名字打的是同一个模型，你会以为"两个模型表现完全一样"）。

### 2026-10-11（第 3 条：PyCharm 误装标准库同名包）

- 场景：在 PyCharm 里打开 `w1-01` 实验，文件顶部 `import asyncio` 被标红为「未解析的引用」
- AI / IDE 给出的（错误）方案：PyCharm 提示「Package asyncio not found」，一键「Install package asyncio」即可修复
- 我如何发现有错：
  1. `asyncio` 是 **CPython 标准库**，从 Python 3.4 起就自带，**永远不需要 pip 安装**；
  2. 但 PyCharm 真把它装上了 —— `pyproject.toml` 被自动改写、`uv.lock` 多出一条记录；
  3. 查 PyPI：`asyncio 4.0.0` 的 sdist 只有 5371 B，装完 `.venv/Lib/site-packages/` 里**只有 `asyncio-4.0.0.dist-info`，没有 `asyncio/` 目录** —— 是个空壳僵尸包，靠「占个名字」骗下载量。
- 正确做法：
  - 卸载假包：`uv pip uninstall asyncio`（实测输出 `Uninstalled - asyncio==4.0.0`）；
  - 把 `pyproject.toml` 的 `dependencies` 清空、移除 lock 里的污染条目；
  - 标红的真因是**解释器配置**（当时指向的 SDK 不对），修解释器即可，不该动依赖。
- 涉及知识点：
  - **标准库黑名单**（永不安装）：`asyncio` / `json` / `os` / `sys` / `time` / `pathlib` / `typing` / `re` / `math` / `logging` / `collections` / `subprocess` / `socket` / `queue` / `random` / `dataclasses` / `enum` / `functools` / `itertools` / `unittest` / `sqlite3` / `csv` / `hashlib` / `uuid` / `abc` / `contextlib` / `copy` / `datetime` / `decimal` / `fractions` / `glob` / `inspect` / `io` / `pickle` / `pprint` / `shutil` / `signal` / `statistics` / `string` / `tempfile` / `threading` / `traceback` / `urllib` / `warnings`。
  - PyPI 上存在大量与标准库同名的**抢注空壳包**，IDE 的「一键安装」会把人送进去 —— **IDE 的建议也要核验**。
  - 判据：装之前先看「这个模块是不是 `python -c "import X; print(X.__file__)"` 已经能定位到标准库路径」。

### 2026-10-11（第 4 条：uv 默认 venv launcher 无签名被拦）

- 场景：`.venv` 建好后任何方式都跑不起来，三个入口三种报错
- AI 给出的（错误）内容：初次诊断归因为「权限问题 / 杀软 / PowerShell 执行策略」，开的药方是
  `Set-ExecutionPolicy Bypass`、改 NTFS 权限、加杀软白名单 —— **全部无效**
- 我如何发现有错：
  - 报错原文的关键词是 **「应用程序控制策略已阻止此文件」**，不是「拒绝访问」也不是「执行策略」——
    前者是 **WDAC / Smart App Control 级别的二进制拦截**，跟 PowerShell 执行策略（管 `.ps1` 脚本）是两回事；
  - 且 `uv` 也报同一个错（`os error 4551`），而 uv 不走 PowerShell —— 说明跟 shell 无关；
  - **决定性一步：对比文件大小。** 用手工 `python -m venv` 建的 venv，`Scripts/python.exe` 是 **255,200 B**；
    项目里的 `.venv` 只有 **46,592 B**。差 5 倍，说明**两个 launcher 根本不是同一个程序**。
- 正确做法：
  - 根因：uv 为它自己下载的 **standalone Python** 建 venv 时，用**自制 launcher（46 KB，无数字签名）**；
    CPython 官方的 venvlauncher 是 **255 KB 且有签名**。Windows 应用控制策略只放行有签名的，于是拦掉前者。
  - 修复：`uv venv --python "D:/Python312/python.exe" .venv` —— 显式指定**系统** Python，
    uv 就改用它自己下载的那份官方 launcher（实测新 `python.exe` = 255,200 B，一次通过）。
  - **预防**：本项目以后所有 `uv venv` 都必须带 `--python "D:/Python312/python.exe"`。
- 涉及知识点：
  - venv 里的 `python.exe` 是 **launcher（转发器）**，不是解释器本体；
  - Windows **应用控制策略 / Smart App Control** 按**数字签名**放行可执行文件，与「权限」「杀软」「执行策略」是三套独立机制；
  - `os error 4551` = Windows 阻止了该文件执行；
  - 排查可执行文件类问题的高效手段：**先量大小、先看签名**，别从权限猜起。

### 2026-10-10

- 场景：安装 Ollama 后拉取模型，想找国内加速方案
- AI 给出的（错误）内容：搜索到的技术博客称可设 `set OLLAMA_REGISTRY=https://mirrors.aliyun.com/ollama` 来加速模型下载
- 我如何发现有错：实测 `curl -sI https://mirrors.aliyun.com/ollama/` 返回 **404** —— 该镜像根本不存在；且翻 Ollama 文档确认它**不提供**自定义 registry 的环境变量
- 正确做法：国内拉模型的可行路线只有两条 —— ① 从 **ModelScope** 下 GGUF 再用 `ollama create` 本地导入；② 保持官方 registry，用代理解决 CDN 可达性
- 涉及知识点：CSDN 等技术社区存在大量 AI 生成的编造式内容，**必须用 curl / 文档实证核验**，不能照抄

### 2026-10-10（第 2 条）

- 场景：写 WSL 环境搭建脚本，检查磁盘空间
- AI 给出的（错误）内容：脚本把 1.34 GB 安装包下载到 `/tmp`，并用 `df /tmp` 判断空间是否充足
- 我如何发现有错：一跑就报「/tmp 空间不足 6GB」，但 `df -h /` 明明显示 947 GB 空闲 —— 说明判断对象选错了
- 正确做法：**WSL 的 `/tmp` 是 tmpfs（内存盘，仅 3~4 GB）**，大文件必须放 `$HOME` 等真实磁盘路径；容量检查要针对**实际写入目标**的文件系统
- 涉及知识点：tmpfs 与真实文件系统的区别；`df -h /` vs `df -h /tmp`；往 tmpfs 写大文件会吃掉系统内存

### 2026-10-09

- 场景：环境搭建 —— 确认本地 GPU 是否可用
- AI 给出的（错误）内容：建议直接 `pip install torch` 安装最新版即可
- 我如何发现有错：查 PyTorch 官网安装选择器，发现默认源不带 CUDA 版本标记，装完 `torch.cuda.is_available()` 返回 False
- 正确做法：必须用 `--index-url https://download.pytorch.org/whl/cu128` 指定 CUDA 版本
- 涉及知识点：PyTorch 与 CUDA 版本绑定；Blackwell 需 cu128+
