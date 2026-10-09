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
│   ├── wsl-setup.md          WSL2 + PyTorch cu128 搭建 Runbook
│   ├── env-notes.md          环境搭建踩坑记录
│   ├── budget.md             API 成本预算与用量台账
│   └── ai-correction-log.md  AI 纠错日志（每天 1 条）
├── src/
│   └── llmkit/               自研 LLM 工具包（W1–W2 起）
├── projects/                 四个递进式实战项目
│   ├── p1-llm-gateway/       多模型服务网关
│   ├── p2-rag-platform/      知识库 RAG 平台
│   ├── p3-agent/             工具调用 Agent + 多 Agent 编排
│   └── p4-ai-test-agent/     AI 测试 Agent
├── notebooks/                实验脚本与数据分析
├── tests/                    测试用例
└── scripts/                  压测、评测、部署等脚本
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

# 3. 安装依赖（使用 uv）
uv sync

# 4. 跑测试
uv run pytest
```

---

## 进度追踪

- [ ] **W0** 环境与仓库就绪
  - [x] 仓库骨架 + SSH 推送
  - [x] 三家 API 账号 + 密钥（`.env`，已确认被 git 忽略）
  - [x] WSL2 + Ubuntu 26.04.1
  - [x] GPU 直通 + PyTorch 2.11.0+cu128（已验证 `capability == (12, 0)`）
  - [x] API 成本预算表 → `docs/budget.md`
  - [ ] 常用库（numpy / matplotlib / jupyter）
  - [ ] Ollama + Qwen3-4B 本地推理验证
- [ ] **W1–W2** Python 工程能力（asyncio / Pydantic / 装饰器 / 测试）
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
