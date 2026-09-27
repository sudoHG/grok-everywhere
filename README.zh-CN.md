# Grok Everywhere

[![CI](https://img.shields.io/github/actions/workflow/status/sudoHG/grok-everywhere/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/sudoHG/grok-everywhere/actions/workflows/ci.yml) [![Release](https://img.shields.io/github/v/release/sudoHG/grok-everywhere?style=flat-square&label=release)](https://github.com/sudoHG/grok-everywhere/releases/latest) [![Downloads](https://img.shields.io/github/downloads/sudoHG/grok-everywhere/total?style=flat-square&label=downloads)](https://github.com/sudoHG/grok-everywhere/releases) [![Stars](https://img.shields.io/github/stars/sudoHG/grok-everywhere?style=flat-square&label=stars)](https://github.com/sudoHG/grok-everywhere/stargazers) [![License](https://img.shields.io/github/license/sudoHG/grok-everywhere?style=flat-square)](LICENSE) [![README views](https://hits.sh/github.com/sudoHG/grok-everywhere.svg?style=flat-square&label=README%20views)](https://hits.sh/github.com/sudoHG/grok-everywhere/)

[English](README.md) | 简体中文

> 一个 Grok 订阅，多种像 API 一样可调用的能力。
> 把 X 搜索、生图、生视频、配音、转录等能力，直接接入你的 Claude Code、Codex、Cursor 主力 Agent 与日常工作流。

<p align="center"><img src="docs/demo.gif" width="720" alt="全新的 Claude Code 会话让 Grok 生成一段自己给 Claude 当实习生、端咖啡的视频，Grok 生成了它。"></p>
<p align="center"><sub>在 Claude Code 里说一句话，Grok 生成了这段视频。2026-09-27 真实运行。</sub></p>

---

## 为什么做这个项目？

我是在 Grok 4.5 刚出来的时候开通 SuperGrok Heavy 的。但到了 Grok 4.7，我越来越不愿意把编程任务交给它：速度慢，推理也不够可靠，于是取消了订阅。可不少人是直接买的年费；就算取消，订阅通常也要到本期结束才失效。难道剩下的这段订阅就这么闲着？

编程任务不想再交给它，但生图、生视频、配音、转录和 X 搜索这些能力，我还是用得上的。如果能把它们接到现在的主力工具里，剩下的订阅就还有用。

所以我做了 **Grok Everywhere**。它复用本机已有的 Grok 登录会话，让这些能力可以像 API 一样被调用。你在 Claude Code、Codex、Cursor 里交代需求，Agent 就能通过它去搜 X、生成图片或视频、合成语音、整理录音，再把结果拿回来继续用。

这也是我想把它开源的原因：如果你也买了 Grok，却已经不太愿意把主要工作交给它，可以试试这种用法。已经买下的订阅，除了打开聊天窗口，还有别的用途。

---

## 一个订阅，拿来当多种 API 用

**一个 Grok 订阅 ≈ X 搜索 API + 生图 API + 视频生成 API + 语音 API……**

通过 Grok Everywhere，原本要打开 Grok 才能用的这些能力，现在可以由你的 Codex或者Claude Code按需调用：

- **X 搜索 API**：查找最新讨论、指定账号的帖子，拿到原帖链接，继续做调研。
- **生图与修图 API**：生成配图、封面，修改已有图片，融合多张参考图。
- **视频生成与编辑 API**：文字或图片生成视频，设置首尾帧和关键帧，编辑、延长已有视频。
- **语音合成 API**：把文字做成配音，自选音色、语言和语速。
- **语音转录 API**：录音转逐字稿、区分说话人，再由 Agent 整理成会议纪要和待办。
- **Grok 模型 API**：问答、写作、网页搜索和图片理解，模型由你选择。

---

## 工作原理（极简版）

它的实现并不复杂：

1. 你先通过 Grok Build（Grok CLI）登录账号，登录会话保存在本机。
2. Grok Everywhere 读取这份会话，由 Python 脚本向对应接口发起请求。在订阅会话模式下，文本与搜索走 Grok CLI 代理通道，语音、图片和视频使用对应的 xAI 接口。
3. 结果返回给当前 Agent，文字、图片、音频和视频也会保存到本地，方便继续使用。

你不需要手动复制 Token，也不是把订阅兑换成一把新的 API Key。这里用的是已有登录会话；下面的上手步骤会明确选择这条路线。

---

## 典型使用场景

装好以后，可以直接在你正在使用的 Agent 里提需求：

- **社媒调研与内容撰写**：“帮我检索 X 上关于这个产品的最新讨论，附上原帖链接，总结大家最关心的几个问题，再给我的介绍文章配一张图。”
- **文章封面与配音**：“给刚写完的这篇文章生成一张封面，再把开头生成一段中文语音旁白。”
- **会议录音整理与提炼**：“转录这段产品讨论录音，按发言人区分逐字稿，并提炼出核心结论与待办事项列表。”
- **图片变短视频**：“把这张照片作为首帧，生成一段 6 秒的缓慢推进镜头。”

图片支持批量生成和多图编辑，语音可以换音色，视频支持首尾帧、关键帧、编辑和续写。通用文本问答与图片理解也保留着，默认使用 Grok 4.6；想用其他模型时可以自己选。

---

## 上手使用

### 1. 准备环境与登录

需要 **Python 3.9+**。Grok Everywhere 本身只用 Python 标准库，不用额外安装 Python 依赖。

如果还没装 Grok Build，先按它的[官方安装说明](https://github.com/xai-org/grok-build/blob/main/crates/codegen/xai-grok-pager/docs/user-guide/01-getting-started.md)安装。装好后运行下面的命令，在浏览器中登录你订阅 Grok 的账号：

```bash
grok login
```

下载并解压本项目源码，在包含 `grok-everywhere/` 文件夹的仓库根目录打开终端，检查登录会话：

```bash
python3 grok-everywhere/scripts/grok.py --auth session system auth-status
```

Windows 可将 `python3` 换成 `py -3`。返回的 `status` 中应有 `available: true`、`kind: "session"` 和 `expired: false`；这表示工具找到了有效登录会话，还不代表每项服务都有权限。提示会话过期时，重新运行 `grok login`。

这里特意加了 `--auth session`，避免电脑上已有的独立 API Key 被优先选中。如果 Grok 配置不在默认目录，可用 `GROK_HOME` 指定。

### 2. 接入你的 Agent（Skill 模式）

将源码包中的内层 `grok-everywhere/` 文件夹复制到你所用 Agent 的 Skill 目录：

- **Codex**：复制至 `~/.codex/skills/grok-everywhere/`
- **Claude Code**：复制至 `~/.claude/skills/grok-everywhere/`，参见[官方 Skills 说明](https://code.claude.com/docs/en/skills)。
- **Cursor**：复制至 `~/.cursor/skills/grok-everywhere/`，参见[官方 Skills 说明](https://prod.cursor.com/docs/skills)。

其他能读取 Skill 并执行命令的工具也可以接入。这里说的是本机运行方式；远程或云端 Agent 不会因此自动获得你电脑上的登录会话。

只安装内层的 `grok-everywhere/` 文件夹，不要将整个源码仓库当作 Skill。安装后新开一次对话，确认 Agent 能找到 Grok Everywhere。

### 3. 先试一次生图

在 Agent 里告诉它：

> 使用 Grok Everywhere，通过我的 Grok 登录会话生成一张漂在蓝色水面上的白色纸船图片。调用时使用 `--auth session`。

也可以在源码仓库根目录直接运行：

```bash
python3 grok-everywhere/scripts/grok.py --auth session image generate "漂在蓝色水面上的白色纸船" --output paper-boat.jpg
```

成功后会得到图片文件，返回结果中的 `artifacts` 会列出产物路径。生图是一次真实调用，会消耗可用额度或产生费用；如果只想检查参数，在模块名前加 `--dry-run` 即可，不会提交生成。

---

## 更多命令

平时让 Agent 按需调用即可，不必记住下面这些参数。想直接在终端运行时，再展开查看。

<details>
<summary>展开命令速查：搜索、语音、图片、视频与文本</summary>

> 以下命令均在仓库根目录下执行示例；如果已进入 `grok-everywhere/` 目录，可直接写 `python3 scripts/grok.py ...`。

### 文本问答与图片理解 (`text`)

默认文本模型为 `grok-4.6`（内置自动联网搜索，可用 `--no-search` 关闭；如需 `grok-4.7` 可通过 `--model grok-4.7` 显式指定）：
```bash
# 基础推理与分析
python3 grok-everywhere/scripts/grok.py --auth session text "帮我把这段说明写得更清楚"

# 结合本地图片或 URL 理解
python3 grok-everywhere/scripts/grok.py --auth session text "描述这张图片中的主体和颜色" --image ./photo.png
```

### X 搜索与网页检索 (`search`)

直接获取 X 平台即时动态或全网公开网页搜索，支持 `quick` / `balanced` / `deep` 深度预设：
```bash
# 检索 X 实时讨论（快速模式）
python3 grok-everywhere/scripts/grok.py --auth session search x "最近 24 小时 AI 领域有哪些重要发布？" --depth quick

# 定向检索指定账号与时间范围
python3 grok-everywhere/scripts/grok.py --auth session search x "产品更新总结" \
  --allow xai,OpenAI --from-date 2026-07-01 --to-date 2026-07-31

# 限定官方域名的 Web 搜索
python3 grok-everywhere/scripts/grok.py --auth session search web "最新 Python 稳定版本特性" --allow-domain python.org
```

### 语音合成与会议纪要 (`audio`)

包含文本转语音（TTS）、录音转写（STT）与会议纪要提炼：
```bash
# 查看可用音色列表
python3 grok-everywhere/scripts/grok.py --auth session system voices

# 语音合成（TTS，支持 eve 等多种预设音色）
python3 grok-everywhere/scripts/grok.py --auth session audio tts "大家下午好，今天我们来同步一下项目进展。" \
  --voice eve --language zh --output output.mp3

# 录音转写与说话人区分（STT 2.0）
python3 grok-everywhere/scripts/grok.py --auth session audio transcribe meeting.m4a --diarize --output transcript.md

# 一键生成会议纪要（自动完成转写并提炼决策与待办）
python3 grok-everywhere/scripts/grok.py --auth session audio minutes meeting.m4a --output minutes.md
```

### 图像生成与编辑 (`image`)

基于 `grok-imagine-image-2.0`，支持比例调整与最多 5 张参考图合成：
```bash
# 文本生图
python3 grok-everywhere/scripts/grok.py --auth session image generate "暴风雨中的一艘折纸船，电影级光影" \
  --aspect-ratio 16:9 --resolution 2k --output cover.jpg

# 图像编辑与参考图融合
python3 grok-everywhere/scripts/grok.py --auth session image edit product.png "将产品放置在雨夜街道的橱窗前" \
  --reference-image background.jpg --aspect-ratio 16:9 --output result.jpg
```

### 视频生成、编辑与断点恢复 (`video`)

文生视频与图生视频基于 `grok-imagine-video-1.5`，视频编辑与续写基于 `grok-imagine-video` (classic)：
```bash
# 图生视频（建议宽高比与原图保持一致）
python3 grok-everywhere/scripts/grok.py --auth session video generate "纸船顺着水流自然漂流" \
  --image boat.jpg --duration 6 --aspect-ratio 16:9 --output boat.mp4

# 使用首尾帧与关键帧约束画面
python3 grok-everywhere/scripts/grok.py --auth session video generate "镜头从特写慢慢拉远到全景" \
  --image start.jpg --last-frame end.jpg --keyframe 3.0=mid.jpg --duration 8

# 视频编辑与视频续写（基于 classic 模型）
python3 grok-everywhere/scripts/grok.py --auth session video edit source.mp4 "将场景切换为雨夜霓虹风格"
python3 grok-everywhere/scripts/grok.py --auth session video extend source.mp4 "主角缓步走出画面" --duration 4

# 异步任务查询与断点恢复下载（耗时任务超时无需重复提交扣费）
# 将 REQUEST_ID 替换为先前返回的实际任务 ID
python3 grok-everywhere/scripts/grok.py --auth session video get REQUEST_ID
python3 grok-everywhere/scripts/grok.py --auth session video resume REQUEST_ID --max-wait 600
```

</details>

---

## 本地缓存与隐私安全

- **本地缓存目录**：可用 `--cache-dir` 指定，其次是环境变量 `GROK_EVERYWHERE_CACHE`。默认按系统环境选取 Windows 的 `%LOCALAPPDATA%\grok-everywhere`、已设置的 `$XDG_CACHE_HOME/grok-everywhere`，或 `~/.cache/grok-everywhere`。指定 `--output` 的产物会保存到指定位置。
- **防重复扣费保护**：脚本不会对失败的付费 POST 请求盲目自动重试。视频生成等异步任务会保留 `request_id`，可通过 `video resume` 重新轮询下载结果。
- **隐私保护**：输入文字和媒体会交给 xAI 处理。本地记录会脱敏凭证字段，但提示词、逐字稿、原始响应和生成文件不自动匿名化，不要把运行缓存直接公开。

---

## 边界与已知限制

- **能力范围**：本项目专注于 REST 工作流，当前不包含 WebSocket 实时语音对讲（Realtime Voice）、流式 STT/TTS、自定义音色克隆创建、电话/SIP 接入以及会话 Token 自动刷新。
- **调用性质**：读取本地会话是便捷的兼容调用方式，不代表官方 API 承诺，也不等同于无限量额度或全平台账号保证；X 搜索能力聚焦于检索与分析，不包含发推或账号管理操作。
- **实测范围**：当前 0.2.0 版本在 macOS / Codex 环境下，通过 session 路线完成了 25 项代表性流程调用及 40 项离线测试。2026-09-27 又在 macOS 上用全新的无头 Claude Code 会话，通过 session 路线完整跑通了一次 `video generate`（6 秒、1080p），页首演示就是这次运行。调用成功不等于内容质量全部通过，搜索、转录和媒体生成结果仍需检查。除这一次调用外，Claude Code、Cursor、Windows/Linux 和独立 API Key 路线尚未完成同轮实测。
- **额度与费用**：本轮确认的是这套调用方式可用，没有核对账号账单，不能据此保证订阅覆盖全部消耗；接口没有返回费用也不代表免费。

---

## 开源协议与免责声明

本项目采用 [MIT License](LICENSE) 开源。
本项目为独立的开源社区项目，与 xAI / Grok 及 Anthropic 均无官方隶属或商业背书关系。
