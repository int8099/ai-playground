# 环境搭建踩坑记录

> 记录一切「装了半天才搞通」的东西。目的：重装系统时不重复踩坑。

## 机器信息

- 系统：Windows
- GPU：RTX 5060 Laptop 8GB（Blackwell 架构）
- CPU：AMD R9 8940H
- WSL 发行版：Ubuntu 26.04.1 LTS / Python 3.14.4，用户名 `ubuntuer`
- WSL 虚拟磁盘位置：
  `C:\Users\8099\AppData\Local\wsl\{02dd5456-b2f9-4fa8-96f9-78f8c64d4300}\ext4.vhdx`
  （装 Ollama 前约 9.0 GB）

### 各组件安装位置（速查）

| 内容 | 位置 |
|---|---|
| zstd（解压工具） | `/usr/bin/zstd`（apt 包） |
| Ollama 主程序 | `/usr/local/bin/ollama` |
| Ollama 运行库（含 CUDA，约 5 GB） | `/usr/local/lib/ollama/` |
| Ollama 安装包缓存（1.34 GB） | `~/.cache/ollama-dl/`（装完可删） |
| Ollama 模型 | `~/.ollama/models/` |
| Ollama 服务日志 | `~/.ollama/serve.log` |
| Python 库（numpy 等） | `~/.venvs/torch/lib/python3.14/site-packages/` |

> ⚠️ 以上**全部在 WSL 虚拟磁盘内**（即上面那个 `ext4.vhdx`）。
> 两个后果：
> 1. **vhdx 只涨不缩** —— 在 WSL 里删文件，C 盘占用不会自动释放，需要手动压缩。
> 2. **卸载/重装 WSL 发行版 = 这些全部消失**（所以配置脚本都进了 git 仓库）。
>
> 想把模型挪出 C 盘的话，可以设 `OLLAMA_MODELS=/mnt/d/ollama-models`。

### 代理开关策略（实测结论）

本机代理是 **TUN + fake-ip 模式**，会劫持 WSL 的全部 DNS 查询（实测连 8.8.8.8 都返回 198.18.x.x）。
不同场景对代理的依赖完全不同：

| 场景 | 需要代理？ | 说明 |
|---|---|---|
| **本地推理 `ollama run`** | ❌ 不需要 | 纯本地 GPU 计算，不联网、不心跳 |
| `ollama pull` 拉模型 | ⚠️ 看情况 | 见下方两条路 |
| `git push` / GitHub | ⚠️ **看情况** | **2026-10-11 实测：SSH 直连 push 成功**（`5813a28..b4ae377`）。但 2026-10-09 曾实测 `github.com` 直连超时。<br>两者不矛盾 —— **SSH 走 22 端口，不经过 HTTP 代理**，受代理开关影响的方式和 HTTPS 完全不同。所以别再用「GitHub 要不要开代理」这种一刀切的说法，先测一下当前网络 |
| 国内镜像（清华 / 上交大 / ModelScope） | ❌ 不需要 | 代理开关都飞快 |

> 💡 测 SSH 通不通（不产生任何副作用）：
> ```bash
> GIT_SSH_COMMAND="ssh -o ConnectTimeout=8" git ls-remote --heads origin
> ```
> 能列出分支就说明通。比直接 `git push` 卡住半天再怀疑人生快得多。

**拉模型的两条路（二选一）：**

1. **关代理直连**（更干净，无需安全降级）
   - 关代理后 DNS 返回 R2 的真实公网 IP（实测 `172.64.66.1` / `172.64.190.1`），
     Ollama 的非公网地址检查自动通过。
   - 切换后需 `wsl --shutdown` 重启以清 DNS 缓存。
   - 前提：Cloudflare R2 在国内可直连（测法：`curl -sI .../r2.cloudflarestorage.com/` 得 400 即通）。

2. **开代理 + `--insecure`**（已验证可行）
   - 代价：该次拉取不校验 TLS 证书（Ollama 仍校验 blob 的 SHA256）。
   - 仅本地可信代理场景可接受，别养成习惯。

> 排查技巧：Ollama 有 SSRF 防护会拒绝非公网地址，但 **curl 没有**。
> 所以怀疑网络问题时，用 curl 测一遍就能区分「网络不通」还是「安全检查拦截」。

---

## 待记录项

### 1. WSL2

- 安装命令：管理员 PowerShell 执行 `wsl --install -d Ubuntu`
- 遇到的问题：
  - `wsl --install -d Ubuntu` 报 `WSL_E_CANNOT_CONNECT`（它要去 `raw.githubusercontent.com` 拉分发列表，该域名 SSL 握手失败）。
  - 首次创建 Unix 用户时填了纯数字用户名 `099` —— Linux 不允许纯数字开头的用户名。
  - 进入 WSL 后提示「检测到 localhost 代理配置，但未镜像到 WSL」。
- 解决办法：
  - 改走 Microsoft Store 路径安装 Ubuntu。（离线备选：`https://cloud-images.ubuntu.com/wsl/releases/24.04/current/` 下的 `ubuntu-noble-wsl-amd64-wsl.rootfs.tar.gz`，实测可达。）
  - 用户名改为字母开头：`ubuntuer`。
  - 代理警告可忽略：`env | grep -i proxy` 为空，WSL 内没有代理变量。日后若需要 WSL 直连 Windows 代理，再建 `~/.wslconfig` 写 `networkingMode=mirrored` + `autoProxy=true`。
- 实测环境（已验收）：
  - 内核 `6.18.40.1-microsoft-standard-WSL2`
  - `/dev/dxg` 存在（GPU 直通节点）
  - WSL 内 `nvidia-smi` 正常列出 `RTX 5060`，Driver Version 592.01 / CUDA 13.1

### 2. CUDA 12.8 + PyTorch 2.7/cu128

> Blackwell 架构**必须** CUDA 12.8+ / PyTorch 2.7+。装旧版会报
> `no kernel image is available for execution on the device`

- 验证命令：`python -c "import torch; print(torch.cuda.is_available(), torch.version.cuda)"`
- 安装前置事实（已核实）：
  - Windows 侧驱动 **592.01**，支持 CUDA 13.1 → 远高于 Blackwell 要求的 570+
  - WSL 内 `nvidia-smi` 显示 `Driver Version 592.01`（借 Windows 驱动）+ `NVIDIA-SMI 590.62`（WSL 侧工具版本），两者不同属正常
  - **结论：WSL 内不需要单独安装 CUDA Toolkit。** pip 的 torch wheel 自带 CUDA runtime
- 安装方式：
  - 主：`uv pip install torch --index-url https://download.pytorch.org/whl/cu128`
  - 国内慢时备选：`--index-url https://mirror.sjtu.edu.cn/pytorch-wheels/cu128`
- 遇到的问题：
- 解决办法：

### 3. Ollama + Qwen3

- 安装命令：
- Qwen3-4B（Q4 约 2.5GB）实测：
- Qwen3-8B（Q4 约 5.5GB）实测：
- 遇到的问题：

### 4. API 平台

- DeepSeek：`https://platform.deepseek.com` —— Key 存入 `.env` 的 `DEEPSEEK_API_KEY`
- 通义百炼：`https://bailian.console.aliyun.com` —— Key 存入 `.env` 的 `DASHSCOPE_API_KEY`
- 智谱 GLM：`https://open.bigmodel.cn` —— Key 存入 `.env` 的 `ZHIPU_API_KEY`
- 安全约定：Key 只走项目根 `.env`（已确认被 `.gitignore` 忽略），不硬编码、不提交；换机器需重建 `.env`

### 5. ⚠️ uv 的 venv launcher 被 Windows 应用控制策略拦截（2026-10-11 实锤）

**这是本项目最坑的一条，重装系统后必然重现，务必先看这段。**

**现象**（同一个 `.venv`，三种写法三种错法，但根因同一个）：

| 执行方式 | 报错 |
|---|---|
| Git Bash `./.venv/Scripts/python.exe --version` | `Permission denied` |
| PowerShell `.venv\Scripts\python.exe --version` | `程序"python.exe"无法运行: 应用程序控制策略已阻止此文件。` + `NativeCommandFailed` |
| `uv run` / `uv pip install` | `Failed to spawn: ... 应用程序控制策略已阻止此文件 (os error 4551)` |

**排查方法：别猜，直接量文件大小。** 逐一测试四种 Python：

| 测试项 | `python.exe` 大小 | 结果 |
|---|---|---|
| uv 下载的 standalone base Python | — | ✅ 能跑 |
| 系统 Python `D:\Python312\python.exe` | — | ✅ `Python 3.13.14` |
| 系统 Python `-m venv` 建的 venv | **255,200 B** | ✅ 能跑 |
| uv + **系统** Python 建的 venv | **255,200 B** | ✅ 能跑 |
| **项目 `.venv`（uv + standalone）** | **46,592 B** | ❌ **被拦** |

**根因**：

- venv 里的 `Scripts/python.exe` **不是真 Python**，只是一个「launcher（启动器）」小可执行文件，
  它负责找到真正的 `python.exe` 然后把命令行参数原样转发过去。
- **CPython 官方的 venvlauncher = 255,200 B，有数字签名** → 通过 Windows 应用控制策略。
- **uv 在 standalone Python 上会用自己的自制 launcher ≈ 46,592 B，没有签名** → 被拦。

> 结论一句话：**「能跑」和「不能跑」的判据就是这个文件的大小/签名，不是路径、不是权限、不是杀软。**

**修复命令**（已实测通过）：

```bash
# 1. 先把坏 venv 改名留底（不要直接删，万一要对比）
mv .venv .venv.bak-uv

# 2. 关键：--python 显式指向【系统】Python，绕过 uv 的 standalone
uv venv --python "D:/Python312/python.exe" .venv

# 3. 验证 launcher 大小（应为 255,200 B 左右，且不再是 46K）
ls -la .venv/Scripts/python.exe

# 4. 重装依赖
uv pip install --python ".venv/Scripts/python.exe" pydantic pydantic-settings

# 5. 验收
.venv/Scripts/python.exe --version          # 应输出 Python 3.13.x
```

**验收实测**：`Python 3.13.14` + `pydantic 2.14.0` + `pydantic-settings` 全部正常导入。

**预防（重要）**：

> 以后**所有**这个项目新建 venv，都必须带 `--python "D:/Python312/python.exe"`。
> `uv venv` 不加这个参数时，默认会用 uv 自己下载的 standalone Python → 必然踩同一个坑。
> 这不是「这次运气不好」，是**默认行为就错**，所以必须写死进肌肉记忆。

**如果要彻底不受 Windows 策略影响**：把开发环境整体搬到 WSL 里（项目已在 WSL 侧跑通）。
代价是 PyCharm 的 WSL 解释器**只有专业版提供**（社区版没有），需要申请 JetBrains 学生授权。
W12–W18 调试 Agent 时会需要，到那时再处理不迟。

### 6. Python 的 HTTP 客户端会偷偷读环境变量里的代理（2026-10-11 实测）

**背景**：本机的环境变量里有 WorkBuddy 注入的代理：

```
HTTP_PROXY  = http://127.0.0.1:63343
HTTPS_PROXY = http://127.0.0.1:63343
```

**httpx 默认 `trust_env=True`**，会自动读取这两个变量并在请求时使用代理。
`requests` 也是同样的行为。

**它带来的两个影响（都实测过）**：

**① 失败的异常类型会变**

同一个 URL（一个不存在的域名 `.invalid`），同一段代码：

| 环境 | 抛出的异常 | 耗时 |
|---|---|---|
| 无代理（`trust_env=False`） | `ConnectError`（DNS 查不到） | 0.2 s |
| 有代理（默认 `trust_env=True`） | `ProxyError`（代理返回 502 Bad Gateway） | 0.6 s |

> **后果**：如果你的 `except` 只列了本地见过的具体异常类型，
> 换一台机器（或多两个环境变量）就会漏接。
> **写 `except httpx.RequestError` 兜底** —— 它是所有网络层异常的父类。

**② 国内 API 走代理会变慢**

| 目标 | 走代理 | 关代理直连 |
|---|---|---|
| `api.deepseek.com` | 约 0.6 s | **约 0.3 s** |

DeepSeek 是国内服务，**不需要代理**。如果代理规则没把它排除，反而绕远路。

**怎么处理**：

```python
# 需要绕开代理时（比如测 DNS 失败、或调国内 API）
httpx.AsyncClient(trust_env=False)

# 只想让部分域名不走代理，配 NO_PROXY 环境变量
NO_PROXY=api.deepseek.com,bailian.console.aliyun.com
```

> ⚠️ 排查网络问题时**先确认代理状态**再往下查。
> 否则你会花半小时调 DNS，而问题其实是代理在中间改写了结果。

**顺带一个免费的好东西**：`GET {base_url}/models` 这个端点
**不消耗 token**，可以拿来确认「key 是否有效 + base_url 是否正确 +
服务端到底支持哪些模型名」。调通链路、写回归测试时优先用它。

### 7. PyCharm 里配了多个解释器时，会「指错」到系统 Python（2026-10-11 实锤）

**现象**：报 `No module named 'httpx'`，但包明明已经装好了。

**根因**：这个项目在 PyCharm 里存在**两个名字都像对的**解释器，实际指向完全不同：

| PyCharm 里的名字 | 实际指向 | httpx | 性质 |
|---|---|---|---|
| `uv (ai-playground)` | `D:\code\ai-playground\.venv\Scripts\python.exe` | ✅ | 项目虚拟环境，对的 |
| **`Python 3.13 (ai-playground)`** | **`D:\Python312\python.exe`** | ❌ | **系统 Python，错的** |

而且配置**分裂**了 —— 两部分各用各的：

| 配置文件 | 字段 | 当时的值 |
|---|---|---|
| `.idea/misc.xml`（项目级） | `ProjectRootManager/@project-jdk-name` | `uv (ai-playground)` ✅ |
| **`.idea/ai-playground.iml`（模块级）** | `orderEntry/@jdkName` | **`Python 3.13 (ai-playground)`** ❌ |

PyCharm 的运行配置默认是 `IS_MODULE_SDK=true`（跟随**模块** SDK），
所以实际跑在**系统 Python** 上。

> 🔴 **最坑的是名字**：`Python 3.13 (ai-playground)` 这个名字里明明写着
> `ai-playground`，指向的却是系统 Python。光看名字完全看不出来。

**为什么「之前一直没事，今天才炸」**：
系统 Python `D:\Python312` 里**恰好装过 pydantic / pydantic-settings / python-dotenv**
（还有 Flask、SQLAlchemy 等旧学习痕迹），但**没有 httpx**。
所以 Day 1–3 的实验都能跑，直到 Day 4 用到 httpx 才暴露。

**诊断方法（关键）**：读 PyCharm 的全局解释器表，看每个名字到底指向哪里。

```
C:\Users\<用户名>\AppData\Roaming\JetBrains\PyCharm<版本>\options\jdk.table.xml
```

每个 `<jdk>` 块里有 `<name value="...">`（PyCharm 里显示的名字）和
`<homePath value="...">`（真实路径）。**这两个才是唯一的真相**，不要靠名字判断。

**修复步骤**（GUI，点一下就好）：
- 最快：PyCharm **右下角状态栏** → 点解释器名 → 选 `uv (ai-playground)`
- 或：`Ctrl+Alt+S` → `Project: ai-playground` → `Python Interpreter` → 下拉切换
- 改完 `.idea/ai-playground.iml` 会立刻被更新，`jdkName` 变成 `uv (ai-playground)`

**⚠️ 为什么不能在 PyCharm 外面直接改 `.idea` 文件**：

> PyCharm 运行时用的是**内存里的配置**，并且退出时会把内存里的旧配置
> **写回文件**，覆盖掉外部修改。
> 所以这类配置问题只在 PyCharm 界面里改，或者先**完全退出** PyCharm 再改文件。

**自检工具**：`python scripts/check_env.py`
纯标准库写的，**用错解释器也能跑起来**并给出诊断 —— 会打印当前解释器路径、
判定是否项目 `.venv`、五个关键依赖的版本，不对时直接给出修复路径。

**顺带两个遗留**：

1. `misc.xml` 里还有个 `Black` 组件的 `sdkName` 指着那个错误解释器。
   只影响 Black 格式化，不影响运行。若把错误解释器删了，记得顺手改这里。
2. **建议删掉那个误导的解释器**：`Settings → Python Interpreter → Show All...`
   → 选中 `Python 3.13 (ai-playground)` → 删除。它名字里带 `ai-playground`
   但指向系统 Python，留着以后必然再踩。
