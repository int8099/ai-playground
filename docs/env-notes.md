# 环境搭建踩坑记录

> 记录一切「装了半天才搞通」的东西。目的：重装系统时不重复踩坑。

## 机器信息

- 系统：Windows
- GPU：RTX 5060 Laptop 8GB（Blackwell 架构）
- CPU：AMD R9 8940H

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
