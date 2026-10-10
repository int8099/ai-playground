# W0 完成报告：环境配置说明与工作日志

> 时间：2026-10-09 ~ 2026-10-10（原定一周，实际 2 天完成）
> 验收结果：体检 **18 项通过 / 0 项失败**
> 本文档回答两个问题：**① 这两天做了什么；② 每项配置为什么这么配。**

---

## 一、先看全景：这套环境长什么样

```
┌─────────────────────────────────────────────────────────────┐
│  Windows 11                                                  │
│  ├─ NVIDIA 驱动 592.01（支持 CUDA 13.1）  ← 唯一的驱动        │
│  ├─ 代理工具（TUN + fake-ip 模式）                            │
│  │                                                           │
│  ├─ WSL 虚拟磁盘                                             │
│  │  C:\Users\8099\AppData\Local\wsl\{02dd...}\ext4.vhdx      │
│  │  └─ Ubuntu 26.04.1 LTS                                    │
│  │     ├─ /dev/dxg ─────────────► 透传到 Windows 驱动的 GPU   │
│  │     ├─ ~/.venvs/torch   Python 3.14.4 + torch 2.11.0+cu128│
│  │     ├─ /usr/local/bin/ollama   0.40.2                     │
│  │     └─ ~/.ollama/models        qwen3:4b                   │
│  │                                                           │
│  └─ D:\code\ai-playground  ← 项目仓库（WSL 里挂在 /mnt/d）    │
└─────────────────────────────────────────────────────────────┘
```

**关键点：GPU 只有一个驱动，装在 Windows 侧。WSL 里的 CUDA 是"借用"它的。**

---

## 二、核心配置逐项说明：为什么这么配

### 2.1 为什么用 WSL2，而不是 Windows 原生 Python

| 原因 | 说明 |
|---|---|
| 生态 | AI 工具链（vLLM、flash-attn、部分向量库）以 Linux 为第一公民。Windows 上要么没 wheel，要么要现场编译 |
| 真实性 | 面试问的是 **Linux 服务器操作**。在 WSL 里练，命令、路径、权限模型都是真的 |
| 可迁移 | 以后租 GPU 云主机（多是 Ubuntu），你的脚本能直接用 |

**代价**：多一层文件系统边界（`/mnt/d` 访问 Windows 盘很慢，约十倍），所以项目代码放 D 盘、运行环境放 WSL 内部。

### 2.2 为什么用 WSL2 而不是 Docker

Docker Desktop 在 Windows 上**底层也是 WSL2**，只是多包了一层。学习阶段：
- Docker 还有 GPU 直通（`nvidia-container-toolkit`）的额外配置成本
- 直接用 WSL2 少一层，出问题好排查

**Docker 留到 W3 学**（那时学容器化部署，目的不同）。现在不引入，是为了减少变量。

### 2.3 GPU 透传：为什么 WSL 里**不能**装 NVIDIA 驱动

这是最容易搞错、后果最严重的一点。

```
WSL 里的 CUDA 调用链路：

torch → libcuda.so → /dev/dxg → Windows NVIDIA 驱动 → 物理 GPU
         ↑
     /usr/lib/wsl/lib/libcuda.so 是个"转发桩"，不是真驱动
```

- **`/dev/dxg`** 是 Windows 的 GPU 半虚拟化设备节点。它存在 = 透传生效。
- **WSL 内的 `nvidia-smi`** 是微软提供的转发程序，显示的是 Windows 侧驱动信息（Driver Version 592.01）和它自己的工具版本（590.62）——**两者不同是正常的**。

⚠️ **反面教材**：去 NVIDIA 官网下 `.run` 文件在 WSL 里装 Linux 驱动，会覆盖 `/usr/lib/wsl/lib`，**GPU 直接失效**。永远只在 Windows 侧更新驱动。

### 2.4 为什么必须 `cu128`（而不能随便装个 torch）

RTX 5060 是 **Blackwell 架构，计算能力 `sm_120`**。

CUDA 的 kernel 是**按计算能力预编译**的。旧版 wheel 里没有 `sm_120` 的 kernel，跑起来就报：

```
no kernel image is available for execution on the device
```

实测：cu128 索引下有 `torch-2.11.0+cu128-cp314-cp314-manylinux_2_28_x86_64.whl`，可用。

> **可复用的方法论**：装 torch 前先查索引支持的 Python 标签和架构：
> `curl -s https://download.pytorch.org/whl/cu128/torch/ | grep -oE 'cp3[0-9]+' | sort -u`

### 2.5 为什么**不装** CUDA Toolkit

`pip install torch` 的 wheel **自带 CUDA runtime**（cudart、cuBLAS、cuDNN 等）——那 2.5 GB 的体积主要就是这个。

完整 CUDA Toolkit（约 3 GB+）只在你要用 `nvcc` **编译自定义 kernel** 时才需要。学习阶段用不上。

### 2.6 为什么用 venv 隔离，而不是全局 pip

Python 项目依赖经常打架（A 项目要 `numpy<2`，B 项目要 `numpy>=2`）。venv 让每个项目有独立的 `site-packages`。

用 **uv** 而不是 `pip` + `venv` 的原因：装包快一个数量级，且能锁定版本生成可复现环境。

本项目环境位置：`~/.venvs/torch`（在 WSL 内，不在 `/mnt/d`——避免跨文件系统 IO）。

### 2.7 为什么全程走国内镜像

| 用途 | 源 | 实测 |
|---|---|---|
| apt 系统包 | `mirrors.tuna.tsinghua.edu.cn` | 0.13 s |
| pip / Python 包 | `pypi.tuna.tsinghua.edu.cn` | 4.3 s |
| torch wheel | `mirror.sjtu.edu.cn/pytorch-wheels` | **0.15 s** |
| GitHub 资源 | `ghproxy.net` | 206 OK |
| 模型（备选） | `modelscope.cn` | 0.32 s |

**注意**：清华站会拒绝非浏览器 User-Agent（curl 默认 UA 会被拒），排查时别误判成"网络不通"。

### 2.8 为什么 Ollama 装到 `/usr/local`

FHS 规范的约定：`/usr/local` 是给**手工安装的、不归发行版包管理器管的软件**用的。

- 主程序 `/usr/local/bin/ollama`
- 运行库（含 CUDA，约 5 GB）`/usr/local/lib/ollama/`
- 模型 `~/.ollama/models/`（以普通用户运行时的默认位置）

> 若改用 systemd 服务（以 `ollama` 用户运行），模型会落到 `/usr/share/ollama/.ollama/models`。
> 本项目没用 systemd（WSL 默认不启用），所以模型在你的 home 下，好管理。

### 2.9 为什么 API Key 放 `.env` 而不是写进代码

**因为 git 历史是删不掉的。** 密钥一旦提交，即使后续 commit 删除，它仍留在历史里，`git log -p` 就能翻出来。公开仓库上被爬取的速度是以秒计的。

本项目的三层防护：

| 文件 | 是否提交 | 作用 |
|---|---|---|
| `.env` | ❌ 被 `.gitignore` 忽略 | 真实密钥 |
| `.env.example` | ✅ 提交 | 模板，教别人要填哪些变量 |
| 代码中 | — | 只读 `os.environ`，绝不硬编码 |

**验证方法**（体检脚本已内置）：
```bash
git check-ignore -v .env        # 应命中 .gitignore 规则
git ls-files | grep -c '^\.env$' # 应为 0
```

### 2.10 为什么要加 `.gitattributes`

Windows 的 git 默认 `core.autocrlf=true`，会在 checkout 时把文本文件转成 **CRLF** 换行。

**后果**：`.sh` 脚本变成 CRLF 后，在 Linux/WSL 里执行会报 `\r: command not found` 或 `bad interpreter` —— **脚本直接废掉**。

**如果不加这个文件**：你重装系统后重新 clone 仓库，`scripts/` 下的脚本全部不可执行，而且报错信息极具迷惑性。

所以显式声明：
```
*.sh   text eol=lf     # shell 脚本必须 LF
*.py   text eol=lf
*.gguf binary          # 二进制禁止转换
```

> **顺带一个坑**：在 Windows Git Bash 里**不能**用 `git show f | grep -c $'\r'` 判断换行符 —— MSYS 管道会做文本模式翻译，把 LF 文件误报成"每行都有 CR"。
> 权威做法：`git ls-files --eol`（看 `i/` `w/` `attr/` 三列）。

### 2.11 代理策略：为什么有的操作必须开、有的必须关

本机代理是 **TUN + fake-ip 模式**，它会**劫持 WSL 的全部 DNS 查询**（实测连 `8.8.8.8` 都返回 `198.18.x.x` 假 IP）。

| 场景 | 需要代理？ | 原因 |
|---|---|---|
| 本地推理 `ollama run` | ❌ 不需要 | 纯本地 GPU 计算，不联网 |
| `ollama pull` 拉模型 | ⚠️ 见下 | CDN 域名被解析成假 IP |
| `git push` / GitHub | ✅ 必须 | 实测直连超时 |
| 国内镜像 | ❌ 不需要 | 开关都飞快 |

**拉模型的矛盾**：模型文件存在 Cloudflare R2，代理把域名解析成 `198.18.0.37`（保留地址段），而 Ollama 有**防 SSRF 的「拒绝连接非公网地址」检查**，于是报：

```
Error: redirect target not allowed: ... resolves to non-public 198.18.0.37
```

两条路：
1. **关代理直连**（更干净）：DNS 返回真实 Cloudflare IP（`172.64.66.1`），检查自动通过
2. **开代理 + `ollama pull --insecure`**（已采用）：跳过该检查，代价是本次拉取不校验 TLS 证书（仍校验 blob 的 SHA256）

> **排查技巧**：Ollama 有 SSRF 防护，**curl 没有**。同一 URL 用 curl 测一下，就能区分「网络不通」还是「安全检查拦截」。

---

## 三、工作日志：这两天实际做了什么

### 2026-10-09（第一天）

| 时间 | 事项 | 结果 |
|---|---|---|
| 20:11 | 创建 `ai-playground` 仓库并推送 | ✅ commit `52e122b` |
| 20:14 | 生成 `.env` 并验证被 git 忽略 | ✅ 三重验证通过 |
| 20:24 | W0 环境体检：确认 3 家 API Key 已填 | ✅ |
| 20:24 | 实测 GPU：RTX 5060 / 驱动 592.01 / CUDA 13.1 | ✅ 无驱动过旧风险 |
| 20:24 | 发现 WSL 未安装 | ⏳ 需安装 |
| 20:44 | `wsl --install -d Ubuntu` 失败（`raw.githubusercontent.com` 握手失败） | ❌ |
| 20:44 | 探测连通性，`gh-proxy.com` / `cloud-images.ubuntu.com` 可达 | ✅ 备选方案 |
| 21:00 | 用户自行通过 Store 路径装好 Ubuntu（用户名 `ubuntuer`） | ✅ |
| 21:04 | **WSL GPU 透传验收通过**：`/dev/dxg` 存在、`nvidia-smi` 出图 | ✅ **关键关卡** |
| 21:06 | 诊断网络：DNS 返回 `198.18.x.x` → 定位为代理 fake-ip | ✅ 根因 |
| 21:12 | 核实 cu128 索引含 `cp314`（支持 Python 3.14） | ✅ 无需装独立解释器 |
| 21:26 | **GPU 验收通过**：torch 2.11.0+cu128 / `capability (12,0)` | ✅ |
| 21:27 | 产出 `docs/budget.md`（API 预算表） | ✅ |
| 21:32 | 全部提交推送（`632106d`、`72f60f5`） | ✅ |

### 2026-10-10（第二天）

| 时间 | 事项 | 结果 |
|---|---|---|
| 12:15 | 发现 `ollama.com/install.sh` 会 307 跳 GitHub → 官方一键安装必失败 | ✅ 关键发现 |
| 12:15 | 抓取官方 `install.sh` 读源码，确认资源名已改为 `.tar.zst`，需 `zstd` | ✅ |
| 12:15 | 测出 `ghproxy.net` 可用（206 Partial Content） | ✅ |
| 12:18 | 脚本第 2 步误判：`/tmp` 是 tmpfs（3.9G）→ 修正下载目录 | ✅ |
| 12:19 | 修正为 `$HOME/.cache/ollama-dl`，空间检查拆成两项 | ✅ |
| 12:27 | `ollama pull` 报 `redirect target not allowed ... 198.18.0.37` | ❌ |
| 12:29 | 定位根因：代理 fake-ip + Ollama SSRF 防护冲突 | ✅ |
| 12:29 | 找到解法 `--insecure`，脚本加自动降级 | ✅ |
| 12:31 | 实测 R2 经代理返回 400（网络本就通）+ DoH 查得真实 IP | ✅ 证据 |
| 12:34 | 用户误在 WSL 内执行 `wsl --shutdown` → 澄清跨系统命令 | ✅ |
| 12:42 | **`ollama ps` 显示 `100% GPU`** → 本地推理验收通过 | ✅ **W0 完成** |
| 12:44 | 发现 CRLF 隐患 → 新增 `.gitattributes` | ✅ 提前拆除 |
| 12:45 | 体检脚本运行：18 通过 / 0 失败 | ✅ |
| 12:47 | 修复体检脚本 `ollama ps` 列解析 bug | ✅ |

---

## 四、验收标准与实测结果

**W0 的验收标准（每条都可复现）：**

```bash
bash scripts/w0-verify.sh
```

| 检查项 | 预期 | 实测 |
|---|---|---|
| WSL2 内核 | 含 `microsoft-standard-WSL2` | `6.18.40.1-microsoft-standard-WSL2` ✅ |
| GPU 直通节点 | `/dev/dxg` 存在 | 存在 ✅ |
| WSL 内 GPU | `nvidia-smi` 出图 | RTX 5060 / 592.01 / 8151 MiB ✅ |
| torch | 2.11+ / cu128 | `2.11.0+cu128` / runtime CUDA 12.8 ✅ |
| CUDA 可用 | `is_available() == True` | True ✅ |
| **计算能力** | **(12, 0)** | **(12, 0)** ✅ |
| 常用库 | numpy / matplotlib / jupyter | 全部已装 ✅ |
| Ollama | 服务在跑 | 0.40.2 ✅ |
| 本地推理 | **`100% GPU`** | `qwen3:4b` / 3.2 GB / **100% GPU** ✅ |
| 密钥 | 3 家齐全且不被提交 | 已确认 ✅ |
| 磁盘 | 充足 | 942 GB 可用 ✅ |

---

## 五、产出文件清单

| 文件 | 作用 |
|---|---|
| `README.md` | 学习路线、目录结构、进度追踪 |
| `.gitignore` | 忽略规则（**含密钥保护**） |
| `.gitattributes` | **强制脚本 LF 换行**，防 CRLF 污染 |
| `.env.example` | 环境变量模板（可提交） |
| `.env` | 真实密钥（**不提交**） |
| `docs/w0-completion-report.md` | 本文档 |
| `docs/wsl-setup.md` | 环境搭建 Runbook（含 8 条报错对照表） |
| `docs/env-notes.md` | 踩坑记录 + 组件位置地图 + 代理策略 |
| `docs/budget.md` | API 成本预算与月度台账 |
| `docs/ai-correction-log.md` | AI 纠错日志（已有 3 条） |
| `scripts/w0-setup.sh` | 一键装 Python 环境（幂等） |
| `scripts/w0-ollama.sh` | 绕过 GitHub 装 Ollama + 拉模型 |
| `scripts/w0-verify.sh` | **一键环境体检** |
| `src/llmkit/` | 自研 LLM 工具包（W1 开始填充） |

**git 提交记录**：
```
73896f5 fix(w0-verify): 修复 ollama ps 的 PROCESSOR 列解析
025d2db chore: 新增 .gitattributes 强制脚本使用 LF 换行
2d389e9 feat(W0): 完成 W0 环境搭建，新增体检脚本与 Ollama 安装脚本
72f60f5 docs(README): 拆分 W0 进度为子项
632106d docs: W0 环境搭建 Runbook、踩坑记录、API 预算台账
52e122b chore: 初始化 ai-playground 仓库骨架
```

---

## 六、已知限制与后续注意

| 项 | 说明 | 何时处理 |
|---|---|---|
| Ollama 不自动启动 | 用 `nohup` 后台起的，WSL 重启后要重起 | 需要时启用 systemd |
| vhdx 只涨不缩 | WSL 内删文件不归还 C 盘空间，需手动压缩 | C 盘紧张时 |
| Qwen3 上下文默认 4096 | 偏小，长文本任务需调大 | W4 做 Prompt 时 |
| Qwen3 默认开思考模式 | 会输出 `Thinking...`，结构化任务需关 | W4/W5 |
| 常用库未版本锁定 | 目前只装了没锁版本 | W2 做工程化时 |
| `--insecure` 拉模型 | 本次拉取不校验 TLS | 可在代理加 `fake-ip-filter` 根治 |

---

## 七、一句话总结

> **W0 的本质是做一件事：让 GPU 能在 Linux 环境下被 Python 和 Ollama 用起来。**
>
> 为此要打通的链路是：Windows 驱动 → WSL2 虚拟化 → `/dev/dxg` → CUDA runtime → PyTorch / Ollama。
> 这条链上任何一环错配（驱动太旧、CUDA 版本不对、装错驱动位置），GPU 就用不了，而且报错信息往往指向错误的方向。
>
> 现在这条链路是**可验证的**（`scripts/w0-verify.sh`）、**可重建的**（`scripts/w0-setup.sh` + 文档）、**可解释的**（本文档）。
