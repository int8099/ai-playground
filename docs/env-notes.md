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
| `git push` / GitHub | ✅ 必须 | 实测 `github.com` 直连超时 |
| 国内镜像（清华 / 上交大 / ModelScope） | ❌ 不需要 | 代理开关都飞快 |

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
