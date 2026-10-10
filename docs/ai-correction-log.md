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
