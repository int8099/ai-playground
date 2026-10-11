# ai-playground

> AI Agent 开发学习工程 —— 从 LLM 调用到多工具 Agent 的完整实践记录。

这是我的 AI Agent 开发学习仓库，记录从「会用 LLM API」到「能独立交付 Agent 应用」的全部代码、笔记与踩坑记录。

所有项目遵循一个原则：**能跑、能演示、能讲清技术选型。**

---

## 学习路线

| 阶段 | 周期 | 内容 | 产出 |
|---|---|---|---|
| 阶段 1 | W1–W5 | 工程底座 + LLM 应用基础 | P1 多模型服务网关 |
| 阶段 2 | W6–W11 | RAG 检索增强 | P2 知识库 RAG 平台 |
| 阶段 3 | W12–W18 | Agent 核心 + LangGraph | P3 工具调用 Agent |
| 阶段 4 | W19–W24 | MCP + 可观测 + 部署 | P3 工程化版本 |
| 阶段 5 | W25–W29 | 安全加固 + AI 测试 Agent | P4 AI 测试 Agent |
| 阶段 6 | W30–W35 | 面试冲刺 | 作品集 + 简历 |

---

## 目录结构

```
ai-playground/
├── README.md                 本文件
├── .gitignore                Python 项目忽略规则
├── .env.example              环境变量模板（复制为 .env 后填 Key）
├── docs/                     笔记与记录
│   ├── w0-completion-report.md  W0 完成报告（配置说明 + 工作日志）
│   ├── wsl-setup.md          WSL2 + PyTorch cu128 搭建 Runbook
│   ├── env-notes.md          环境搭建踩坑记录
│   ├── budget.md             API 成本预算与用量台账
│   └── ai-correction-log.md  AI 纠错日志（每天 1 条）
├── src/
│   └── llmkit/               自研 LLM 工具包（W1 起）
│       ├── models.py         请求/响应模型 + 价格表（Pydantic v2）
│       └── client.py         异步客户端：并发闸门 / 重试 / 流式 / 成本统计
├── projects/                 四个递进式实战项目
│   ├── p1-llm-gateway/       多模型服务网关
│   ├── p2-rag-platform/      知识库 RAG 平台
│   ├── p3-agent/             工具调用 Agent + 多 Agent 编排
│   └── p4-ai-test-agent/     AI 测试 Agent
├── experiments/              小实验：一次一个目录，各自独立可跑
│   ├── w1-01-sync-vs-async/  同步 vs 异步、并发 vs 并行、I/O vs CPU
│   ├── w1-02-semaphore/      并发闸门 Semaphore
│   ├── w1-03-retry/          指数退避 + 抖动（含规模扫描）
│   ├── w1-04-pydantic/       类型标注 + Pydantic v2
│   └── w1-05-httpx/          httpx 打真实 API / 超时与错误分类 / 流式 / 思考开关
├── notebooks/                实验脚本与数据分析
├── tests/                    测试用例
└── scripts/                  压测、评测、部署等脚本
    └── llmkit_demo.py        llmkit 端到端演示（兼冒烟测试）
```

---

## 环境要求

- **Python** 3.11+（用 [uv](https://docs.astral.sh/uv/) 管理依赖与虚拟环境）
- **Docker** + Docker Compose（Redis / pgvector / 服务编排）
- **WSL2 + CUDA 12.8**（本地跑开源模型，Blackwell 显卡必须 CUDA 12.8+）
- **API Key** 至少 2 家：DeepSeek / 通义百炼 / 智谱 GLM

> 注意：本项目**绝不提交任何密钥**。所有 Key 走环境变量，`.env` 已在 `.gitignore` 中。

---

## 快速开始

```bash
# 1. 克隆
git clone git@github.com:<your-username>/ai-playground.git
cd ai-playground

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 3. 建虚拟环境（⚠️ 必须带 --python，原因见下方「应用程序控制策略」小节）
uv venv --python "D:/Python312/python.exe" .venv

# 4. 安装依赖
uv sync

# 5. 跑测试
uv run pytest
```

> **Windows 用户注意**：第 3 步的 `--python` 参数不能省。
> `uv venv` 不带参数时默认用 uv 自下载的 standalone Python，生成的 launcher 无签名，
> 会被 Windows 应用控制策略拦掉，导致环境完全跑不起来。详见下文。

---

## 在 PyCharm 里运行

日常开发直接在 PyCharm 里跑，不需要敲命令行。

### 一次性：把解释器指向项目的 .venv

1. `File → Open`，选**项目根目录**（`D:\code\ai-playground`，不是某个实验子目录）
2. `Ctrl+Alt+S` → `Project: ai-playground` → `Python Interpreter`
3. `Add Interpreter` → `Add Local Interpreter...`
4. 左侧选 `Virtualenv Environment` → `Existing`
5. Interpreter 路径填：

   ```
   D:\code\ai-playground\.venv\Scripts\python.exe
   ```

6. `OK` → `OK`

配好后右下角会显示 `Python 3.13 (.venv)`。**四个实验共用这一个环境。**

> 如果列表里还挂着红色的失效条目，点 `Show All...` 把它删掉。
>
> 注意：基础解释器目录叫 `D:\Python312`，但里面装的其实是 **Python 3.13.14** —— 目录名有误导性，
> 判断版本一律看 `python.exe --version` 的输出，不要看文件夹名。

### ⚠️ 如果 PyCharm 报「应用程序控制策略已阻止此文件」

这是本机的一个**已知环境坑**，不是你的操作问题，重装系统后会重现。

**症状**：解释器配好后一运行就报

```
程序"python.exe"无法运行: 应用程序控制策略已阻止此文件。
```

**原因**：venv 里的 `Scripts\python.exe` 只是个转发用的 launcher。
如果 venv 是 `uv venv` 不带参数建的，uv 会用它自己的 standalone Python，
生成的 launcher 只有 **46 KB 且无数字签名**，被 Windows 应用控制策略拦掉；
官方的 venvlauncher 是 **255 KB 且有签名**，能通过。

**一分钟自检**（在 PyCharm 的 Terminal 里）：

```bash
ls -la .venv/Scripts/python.exe
```

- 输出 **255200** 左右 → 正常
- 输出 **46592** 左右 → 中招了，按下两条重来

```bash
mv .venv .venv.bak-uv
uv venv --python "D:/Python312/python.exe" .venv
uv pip install --python ".venv/Scripts/python.exe" pydantic pydantic-settings
```

然后回 PyCharm 重新指解释器（照上面「一次性」那五步走一遍）。

> **规矩**：本项目以后**所有** `uv venv` 都必须带 `--python "D:/Python312/python.exe"`。
> 不带参数必然踩坑 —— 这是默认行为问题，不是运气问题。
>
> 完整分析见 `docs/env-notes.md` 第 5 节。

### 跑某个实验

在左侧目录树里点到脚本 → **右键 → Run 'xxx'**（或 `Ctrl+Shift+F10`）。输出在下方 Run 面板。

比如 `experiments/w1-04-pydantic/type_safety.py`，右键 Run 即可。

### 加新依赖

```bash
uv add --project D:\code\ai-playground <包名>
```

装进 `.venv` 后，PyCharm 会自动识别（可能要等几秒重新索引）。

### 关于工作目录

所有实验脚本都用 `Path(__file__)` 定位文件，**不依赖「当前工作目录」**。

所以不管 PyCharm 从哪个目录启动脚本（默认是项目根），都能正常跑。这也是刻意的设计 —— 避免「命令行能跑、IDE 里跑不了」这类问题。

---

## 进度追踪

- [x] **W0** 环境与仓库就绪（2026-10-09 ~ 10-10）　**18 项体检全通过**
  - [x] 仓库骨架 + SSH 推送
  - [x] 三家 API 账号 + 密钥（`.env`，已确认被 git 忽略）
  - [x] WSL2 + Ubuntu 26.04.1
  - [x] GPU 直通 + PyTorch 2.11.0+cu128（已验证 `capability == (12, 0)`）
  - [x] API 成本预算表 → `docs/budget.md`
  - [x] Ollama + Qwen3-4B 本地推理（已验证 `100% GPU`）
  - [x] 常用库（numpy / matplotlib / jupyter）
  - 体检脚本：`bash scripts/w0-verify.sh`
- [ ] **W1–W2** Python 工程能力（asyncio / Pydantic / 装饰器 / 测试）
  - [x] W1 Day 1　同步 vs 异步、并发 vs 并行、I/O vs CPU → `experiments/w1-01-sync-vs-async/`
  - [x] W1 Day 2　并发闸门 Semaphore + 指数退避重试 → `experiments/w1-02-semaphore/`、`w1-03-retry/`
  - [x] W1 Day 3　类型标注 + Pydantic v2 → `experiments/w1-04-pydantic/`
  - [x] W1 Day 4　httpx 打真实 API：超时 / 错误分类 / 流式 / 思考开关 → `experiments/w1-05-httpx/`
  - [x] **W1 交付物　`src/llmkit/`（client + models）已跑通真实 API** ✅
    - 端到端演示：`python scripts/llmkit_demo.py`
  - [ ] W2 待做：把重试抽成**装饰器**（现在写死在 client 里）、`pytest + respx` 打桩测试（不烧真钱）、多厂商适配
- [ ] **W3** 服务化能力（Git / Docker / FastAPI）
- [ ] **W4** LLM 应用能力（token 成本 / 结构化输出 / Prompt）
- [ ] **W5** 工具调用能力（Function Calling / 缓存 / 限流）→ **P1 v1.0**
- [ ] **W6–W11** RAG 检索增强 → **P2 v1.0**
- [ ] **W12–W18** Agent 核心 + LangGraph → **P3 v1.0**
- [ ] **W19–W24** MCP + 可观测 + 部署
- [ ] **W25–W29** 安全加固 + AI 测试 Agent → **P4 v1.0**
- [ ] **W30–W35** 面试冲刺

---

## 记录约定

1. **AI 纠错日志**：每天记录 1 条「AI 给错的地方 + 我如何判断 + 正确做法」，见 `docs/ai-correction-log.md`
2. **对比数据**：任何优化都要配一张表（效果 / 延迟 / 成本），没有数据的优化不算完成
3. **每周复盘**：能跑的增量 + 演示录屏 + 一篇复盘

---

## 许可

MIT
