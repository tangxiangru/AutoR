# AutoR 中文使用教程

> 面向第一次使用 AutoR 的用户。
>
> 目标不是“把命令跑起来”而已，而是让你尽快掌握：如何安装、如何正确使用、如何在人类审批环节把结果从 toy 拉到真正可用，最后做出高质量的 PDF 研究产物。

## 1. 先用一句话理解 AutoR

AutoR 不是一个“把论文一键生成出来”的黑盒，也不是一个只会写几段研究文字的聊天 demo。

它更准确的定位是：

- 一个 **human-centered** 的 research harness
- 一个建立在底层 coding agent 之上的 **research loop**
- 一个把研究过程落盘为可检查、可恢复、可重做的 **run**

最重要的原则只有一句：

**AI 负责执行，人类负责方向。**

所以你在使用 AutoR 时，最关键的动作不是“回车启动”，而是：

- 在每个 stage 结束时认真审阅
- 当结果过于 toy、缺实验、缺证据、缺文件时明确要求重做
- 在真正达到可接受质量之前不要轻易 approve

如果你能把这条原则用好，AutoR 的上限会高很多。

---

## 2. AutoR 能做什么

AutoR 当前主线适合做这些事情：

- 从一个研究目标出发，按固定科研流程推进
- 在每个阶段调用底层执行器完成真实工作
- 把 prompt、日志、阶段总结、代码、数据、图、论文源文件、PDF 都落到 `runs/<run_id>/`
- 支持从已有 run 恢复
- 支持从某个特定 stage 重做
- 支持把更早的 stage 回滚，然后让后续阶段全部失效重跑
- 支持从已有项目仓库起步
- 支持从你过去的论文语料起步
- 支持按投稿 venue 组织 Stage 07 的写作输出
- 支持文献整理、citation verification、实验清单、artifact 索引、发布打包

底层执行器目前支持：

- `claude`
- `codex`

AutoR 负责的是更上层的 research loop，而不是重新发明一个新的代码 agent。

### 2.1 最近更新你需要知道

最近主线有几个对真实使用很重要的变化：

- `00_intake` 现在是专门的需求澄清阶段。第一轮会逐个问你澄清问题，每个问题可以选择模型给的选项、输入自定义回答，或者 skip；第二轮会展示更新后的 intake brief，不再把那 3 个问题当成普通 suggestion。
- 终端 UI 更适合真实录屏和长 run：输出框正文行会保持彩色边框，长行、长路径和中文宽字符会自动换行，Stage 0 和审批菜单支持上下键选择。
- Codex backend 已经改用当前 Codex CLI 的 `--sandbox workspace-write` 执行参数，不再触发 Codex CLI 内部旧 `--full-auto` 参数的 deprecated warning。注意这和 AutoR 自己的 `--full-auto` 审批模式不是一回事。
- 如果你用 Codex 跑远程 SSH / GPU 实验，可以显式设置 `--codex-sandbox danger-full-access`。默认仍然是更安全的 `workspace-write`，不要把 unrestricted 模式当成默认选择。
- `--full-auto` 仍然是 AutoR 的自动审批模式：它让一个严格 reviewer agent 替代人工等待，但不改变 9 个 stage 的主体流程。

---

## 3. 安装前需要准备什么

建议环境：

| 项目 | 是否必需 | 说明 |
| --- | --- | --- |
| Python 3.10+ | 必需 | AutoR 主程序入口是 `python main.py` |
| Git | 必需 | 用于获取仓库 |
| Node.js 18+ | 强烈建议 | `Claude Code` 官方要求 Node 18+；`Codex CLI` 也通过 npm 安装 |
| Claude Code 或 Codex CLI | 必需 | 真正执行研究任务时需要其中之一 |
| TeX 环境 | 可选但推荐 | Stage 07 更容易稳定产出可编译 PDF |
| `PyMuPDF` | 可选 | 如果你要用 `--paper-corpus` 读取 PDF 内容，推荐安装 |
| `google-genai` / `Pillow` / `PyYAML` | 可选 | 只有在使用 `--research-diagram` 时才需要 |

平台建议：

- macOS / Linux 最省事
- Windows 建议使用 WSL

---

## 4. 第一步：先安装底层执行器

AutoR 本身不是“先装 AutoR 再装 agent”，而是反过来：

1. 先装 `Codex` 或 `Claude Code`
2. 再让它们来帮助你安装和使用 AutoR

### 4.1 安装 Codex

根据 OpenAI 官方文档，Codex CLI 当前可以直接通过 npm 安装：

```bash
npm install -g @openai/codex
```

如果你的 npm 全局安装权限有问题，优先修正 Node / npm 环境本身，不要靠粗暴的 `sudo` 硬装。

常见认证方式有两种：

方式 A：登录

```bash
codex --login
```

方式 B：使用 API Key

```bash
export OPENAI_API_KEY="你的 OpenAI API Key"
```

检查是否安装成功：

```bash
codex --version
```

如果你已经有 ChatGPT 订阅，也可以直接走官方的登录流程。

### 4.2 安装 Claude Code

根据 Anthropic 官方文档，Claude Code 当前的标准安装方式是：

```bash
npm install -g @anthropic-ai/claude-code
```

如果遇到权限问题，优先修正 npm 权限配置；不建议直接使用 `sudo npm install -g`。

安装后建议先检查环境：

```bash
claude doctor
```

然后启动一次，完成登录或认证：

```bash
claude
```

Claude Code 官方支持多种认证来源，例如：

- Claude App / Claude.ai 账号
- Anthropic Console
- Amazon Bedrock
- Google Vertex AI

### 4.3 官方文档

如果你在安装执行器时遇到问题，优先看官方文档：

- Codex CLI: <https://help.openai.com/en/articles/11096431>
- Codex 登录: <https://help.openai.com/en/articles/11381614>
- Claude Code 安装: <https://docs.anthropic.com/en/docs/claude-code/setup>

---

## 5. 第二步：让 Codex 或 Claude Code 帮你安装 AutoR

这是最推荐的上手方式。

你先进入一个你想存放 AutoR 的父目录，然后启动你熟悉的执行器：

```bash
codex
```

或者：

```bash
claude
```

随后直接把下面这段话发给它：

```text
请在当前目录安装 AutoR：
1. clone https://github.com/AutoX-AI-Labs/AutoR.git
2. 进入仓库，阅读 README 和 python main.py --help
3. 如有必要，创建 Python 虚拟环境
4. 安装当前仓库运行所需的最小依赖
5. 运行一次 smoke test：python main.py --fake-operator --goal "UI smoke test"
6. 最后告诉我正式运行的最小命令
不要修改主逻辑，不要做无关重构。
```

这样做的好处是：

- 你不用先理解整个仓库
- 它会自己检查当前环境是否缺工具
- 它能顺手帮你把最小运行链路打通

### 5.1 手动安装作为备选

如果你更喜欢手动操作，也可以直接：

```bash
git clone https://github.com/AutoX-AI-Labs/AutoR.git
cd AutoR
python main.py --help
```

当前主线的核心运行路径并不是“先 `pip install -r requirements.txt` 再运行”的模式，而是仓库 clone 下来后直接通过 `python main.py` 启动。

如果你要开启可选增强能力，再按需安装：

```bash
pip install pymupdf
pip install google-genai pillow pyyaml
```

其中：

- `pymupdf` 用于 `--paper-corpus` 的 PDF 文本提取
- `google-genai pillow pyyaml` 用于 `--research-diagram`

---

## 6. 第三步：大多数用户先直接运行 `python main.py`

对绝大多数真实用户来说，最推荐的日常用法不是一开始就写很长的参数，而是：

```bash
python main.py
```

然后在终端交互里逐步输入目标、资源和反馈。

这是因为 AutoR 本来就是一个 terminal-first、human-in-the-loop 的系统。实际使用时，很多关键控制都发生在：

- 你怎么描述研究目标
- 你是否补充已有资源
- 你怎么审每个 stage
- 你在审批菜单里怎么要求它返工

所以如果你是第一次上手，或者你更偏向真实人工协作，而不是脚本化批处理，**优先直接运行 `python main.py`**。

### 6.1 交互式启动到底会发生什么

当你直接运行：

```bash
python main.py
```

AutoR 会在终端里：

- 让你直接输入研究目标
- 支持多行输入
- 在进入 intake 前询问你是否有现成资源要导入

这个模式非常适合第一次上手，因为你不需要先背参数。

一个容易忽略但很有用的细节是：

- 资源不一定非得通过 `--resources` 传入
- 在交互模式里，你也可以逐个输入文件或目录路径
- 还可以给每个资源附一行简短说明

这对初学者尤其友好。

### 6.2 什么时候再切到参数模式

当你已经熟悉流程，或者你想：

- 固定 backend / model / venue
- 复现实验
- 做批量运行
- 在脚本里调用

这时再使用显式参数更合适。

也就是说：

- 对人类日常使用，交互模式通常更自然
- 对复现和自动化，参数模式更方便

### 6.3 可选：先跑一个 smoke test

如果你想先验证本地链路，而不消耗真实 agent 配额，可以跑：

```bash
python main.py --fake-operator --goal "UI smoke test"
```

你应该能看到：

- 启动 banner
- stage 面板
- 结构化的终端输出
- 每个 stage 结束后的审批菜单
- `runs/<run_id>/` 下生成一整套运行目录

但是要注意：

**`--fake-operator` 只能用于烟测和演示，不能证明真实科研能力。**

它的作用只是：

- 看 CLI 能不能跑通
- 看目录结构和 UI 是否正常
- 看审批 loop 是否正常

不要把 smoke test 的结果当成真实研究结果。

### 6.4 可选：在浏览器里使用 AutoR Studio

如果你更希望在浏览器里审批 stage、查看论文、观察运行进度，而不是始终盯着终端，也可以使用 **AutoR Studio**。

启动方式：

```bash
python studio.py
```

然后在浏览器打开：

```text
http://127.0.0.1:8000/studio/
```

Studio 更适合这些场景：

- 你想在浏览器里审 stage，而不是看终端面板
- 你想更直观地 approve 或给反馈
- 你想把论文 PDF、LaTeX 源文件和 build log 放在一个界面里看
- 你想在长 run 中查看版本历史和 session trace
- 你想录一个比纯终端更清晰的演示

最重要的一点是：

**Studio 不是另一套工作流。**

它和终端模式共用同一套 run 目录、stage summary、manifest 和 artifacts，也就是说：

- terminal 模式和 Studio 只是同一个系统的两种界面
- 浏览器 UI 不会生成另一套隐藏格式
- 你在 Studio 里看到的内容，原则上也都应该能在 `runs/<run_id>/` 里找到

当前限制：

- Studio 目前还是 **Claude-backed**
- 终端主流程支持 `claude` 和 `codex`
- 所以如果你现在必须用 Codex，请继续使用 `python main.py`

一个简单的使用原则：

- 想要最直接、最可脚本化、backend 更灵活的工作流，就用 `python main.py`
- 想要更直观的审批、review 和演示体验，就用 `python studio.py`

---

## 7. 第四步：需要固定配置时，再用显式参数启动

### 7.1 最小正式命令

如果你用 Claude：

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --goal "Study whether retrieval-augmented chain-of-thought improves factual QA under a fixed token budget, and produce a submission-style PDF."
```

如果你用 Codex：

```bash
python main.py \
  --operator codex \
  --model default \
  --goal "Study whether retrieval-augmented chain-of-thought improves factual QA under a fixed token budget, and produce a submission-style PDF."
```

如果你的 Codex-backed run 需要通过 SSH 提交远程 GPU 任务，例如你已经手动验证过 `ssh gpu-server "hostname && nvidia-smi"` 可以正常执行，可以这样显式放开 Codex sandbox：

```bash
python main.py \
  --operator codex \
  --codex-sandbox danger-full-access \
  --goal "Run the planned experiments on the remote GPU server and produce a submission-style PDF."
```

这个选项会给 Codex 后端不受 sandbox 限制的本地和远程执行能力。只在你信任当前任务、确认 SSH 命令安全、并且确实需要远程执行时使用。

补充两条很有用的默认行为：

- 新建 run 时，如果你不写 `--operator`，默认使用 `claude`
- 新建 run 时，如果你不写 `--model`，Claude 默认是 `sonnet`，Codex 默认是 `default`
- 恢复旧 run 时，AutoR 默认会保留这个 run 原来的 backend、model 和 venue；只有你显式指定新值时才会覆盖

如果你想启用“全自动审批模式”，也就是不再等待你手动点 1~6，而是接入一个严格的模拟人类 reviewer agent，可以这样跑：

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --full-auto \
  --goal "..."
```

如果你希望“执行 agent”和“审批 reviewer”分开，也可以单独指定 reviewer 的 backend：

```bash
python main.py \
  --operator codex \
  --model default \
  --full-auto \
  --review-operator claude \
  --review-model opus \
  --goal "..."
```

这里要明确两点：

- `--full-auto` **不会改变主体科研流程**，只是把原来等待人工审批的地方，替换成一个严格的 reviewer agent
- 真正重要、要出高质量成果的研究，仍然推荐默认的人类审批模式；`--full-auto` 更适合夜间 unattended run、批量 dry run、流程压测或长任务巡航

### 7.2 推荐同时指定投稿 venue

如果你已经知道目标风格，建议一开始就指定：

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --venue neurips_2025 \
  --goal "..."
```

或者：

```bash
python main.py \
  --operator codex \
  --model default \
  --venue jmlr \
  --goal "..."
```

当前常见 venue profile 例如：

- `neurips_2025`
- `neurips_2026`
- `iclr_2026`
- `icml_2026`
- `cvpr_2026`
- `acl_2026`
- `aaai_2026`
- `ieee_journal`
- `ieee_conference`
- `nature`
- `nature_communications`
- `jmlr`

完整列表见 [../templates/registry.yaml](../templates/registry.yaml)。

注意：

- `--venue` 不指定时，默认是 `neurips_2025`
- AutoR 会按这个 venue profile 组织写作和打包
- 这不等于仓库内置了该 venue 的全部官方投稿规则

### 7.3 强烈建议带上资源一起跑

如果你手头已经有论文、Bib、数据、代码、笔记，不要空手开跑。

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --venue neurips_2025 \
  --goal "Evaluate whether small MoE routing changes improve training stability without increasing parameter count." \
  --resources papers/key_paper_1.pdf papers/key_paper_2.pdf refs.bib data/baseline.csv notes/ideas.md
```

`--resources` 适合放：

- PDF 论文
- `.bib` / `.bibtex`
- 数据文件
- 代码目录
- 实验笔记
- 你已经整理过的相关材料

这是提升质量最快的方法之一。

补充一点：

**`--resources` 不只支持单个文件，也支持目录。**

所以如果你已经有一个小型代码仓库、一个数据目录，或者一整包阅读材料，可以直接整体喂进去，不必手工拆散。

### 7.4 如果你需要教 AutoR 某种“技能”，应该怎么做

实际使用里，经常会遇到这种情况：

- 你们实验室有自己的 GPU 提交方式，比如 `rjob`
- 你们有固定的数据预处理脚本
- 你们有内部 benchmark 运行规范
- 你们有固定的论文组织方式、结果落盘路径、命名规范

这时候最重要的一条原则是：

**不要只口头说一句“请学会这个技能”。要把它变成可执行的 playbook。**

最有效的做法是把这类技能整理成一组资源，再交给 AutoR：

- 一份说明文档，例如 `rjob_guide.md`
- 一个或多个命令模板或脚本，例如 `submit_rjob.sh`
- 一个成功过的示例配置
- 环境说明，例如 conda 环境、模块加载方式、数据路径、输出路径
- 一份真实成功日志或结果样例

也就是说，你真正要教给 AutoR 的不是一句话，而是一套：

- 规则
- 示例
- 模板
- 成功案例

### 7.5 这类技能应该在什么时候喂给 AutoR

最推荐的方式有三种：

1. 直接用交互式启动 `python main.py`，在资源导入环节把这些文件或目录加进去
2. 用 `--resources` 把 playbook 目录直接传进去
3. 如果这是一个长期稳定的项目规范，就把它放进项目仓库里，再用 `--project-root`

如果这套规范你会反复使用，最稳妥的办法通常是维护一个长期目录，例如：

```text
lab_playbooks/
  rjob/
  slurm/
  data_prep/
  eval_rules/
```

之后每次运行时，把其中相关目录作为资源带进去。

### 7.6 光给资源还不够，还要把硬约束写进目标

如果某些要求是必须遵守的，不要只寄希望于 AutoR 自己推断。

要把它们明确写进目标或反馈里。

例如：

```text
Use the provided rjob workflow for all non-trivial training and evaluation.
Local runs are only allowed for smoke tests under 5 minutes.
All real experiments must be submitted through rjob to GPU nodes.
Save job scripts, job IDs, logs, and machine-readable results into the run workspace.
```

这类写法很有效，因为它同时明确了：

- 什么必须做
- 什么不能做
- 真正合格的产物应该是什么

### 7.7 在哪些 stage 检查“它有没有真的学会”

这类技能最适合在下面几个阶段强制检查：

- `00_intake`：它是否真正理解了这套规范和约束
- `03_study_design`：实验计划里有没有把这套执行方式写清楚
- `04_implementation`：有没有真正写出可复用的脚本、配置和运行方法
- `05_experimentation`：有没有真的按规范执行，而不是偷偷本地糊弄一下

以 `rjob` 为例，到了 `Stage 04/05`，你应该至少看到：

- 可复用的提交脚本
- 真实 job 配置
- job ID 或提交记录
- 运行日志
- 机器可读结果文件

如果没有这些，通常就不应该 approve。

### 7.8 一个很实用的返工反馈模板

如果你发现 AutoR 没有按你教的集群规范来做，可以直接用这种反馈：

```text
Do not continue with local-only experiments.
Use the provided rjob workflow to submit real GPU jobs.
Create reusable submission scripts and save the submit command, job config, job IDs, logs, and machine-readable results under workspace/code and workspace/results.
Local execution is only for smoke tests.
```

### 7.9 不要怎么教

下面这些做法通常不够好：

- 只说一句“请学会 rjob”
- 只贴一个命令，没有上下文
- 只告诉它“用 GPU”，但不说怎么提交、结果放哪、怎样算成功
- 不在审批里检查它是否真的遵守了规范

一句话总结：

**如果你希望 AutoR 学会某种技能，就把它包装成可执行资源，并在关键 stage 用人工审批强制它真的按这套资源做事。**

---

## 8. AutoR 会怎么运行

典型流程是：

0. `00_intake`（可选）
1. `01_literature_survey`
2. `02_hypothesis_generation`
3. `03_study_design`
4. `04_implementation`
5. `05_experimentation`
6. `06_analysis`
7. `07_writing`
8. `08_dissemination`

也就是说，实际是 **1 个 intake + 8 个正式研究阶段 = 9 个 stage**。

| Stage | 这一阶段做什么 | 你应该重点检查什么 |
| --- | --- | --- |
| `00_intake` | 在正式研究前对齐目标、资源、约束、评估方向和投稿风格。 | 逐个回答澄清问题，补充硬约束，确认题目足够窄、足够可执行。 |
| `01_literature_survey` | 整理相关工作、任务背景、benchmark、baseline 和已有缺口。 | 不要接受浅层论文列表，要看是否有结构化文献文件、对比和证据账本。 |
| `02_hypothesis_generation` | 把方向收敛为可检验的主假设、次级假设和临时 paper claim。 | 确认它不是继续 brainstorm，而是真的锁定了可实验、可否证的主线。 |
| `03_study_design` | 把假设变成可执行实验设计。 | 检查数据集、指标、baseline、ablation、预算、随机种子、失败判据和数据产物。 |
| `04_implementation` | 写真实代码、配置、数据准备脚本和 sanity check。 | 不要 approve 只有 skeleton 的实现；要看到可运行脚本、命令、配置和日志。 |
| `05_experimentation` | 按设计运行实验并保存机器可读结果。 | 区分 smoke test 和正式实验；要有 baseline、重复运行、结果文件和失败记录。 |
| `06_analysis` | 分析结果、画图、做误差分析和机制解释。 | 不要只复述最好指标；要看图表、失败案例、消融解释和结论边界。 |
| `07_writing` | 生成 venue-aware 的论文源文件、Bib、可编译 PDF 和引用校验。 | 检查每个核心 claim 是否能追溯到实验、图表或文献，不要只看 PDF 是否漂亮。 |
| `08_dissemination` | 补齐 review、release、readiness、复现和对外交付材料。 | 确认这个 run 能被别人检查、复现、展示，而不是只停在论文。 |

每个 stage 的逻辑都一样：

1. AutoR 生成 prompt
2. 底层执行器开始做事
3. 结果实时显示在终端里
4. stage 结束后生成结构化 stage summary
5. 你决定是 refine 还是 approve

从 `01_literature_survey` 到 `08_dissemination`，审批菜单固定有 6 个动作：

1. 使用建议 1 继续改
2. 使用建议 2 继续改
3. 使用建议 3 继续改
4. 输入你自己的反馈继续改
5. 批准并进入下一阶段
6. 中止

`00_intake` 是特例：

- 第一轮不会让你直接选“使用 suggestion 1/2/3”，而是把 3 条内容当成澄清问题逐个问你
- 每个问题都可以选择选项、输入自定义回答，或者 skip
- 问完后还可以输入额外自定义建议
- 第二轮会重新生成 intake brief，然后只让你选择“自定义反馈 / 继续 / 退出”

最常用的是：

- `4`：你自己写反馈
- `5`：当你确认这个 stage 真的足够好时再批准

同一个 stage 内继续 refine 时，AutoR 会尽量沿用同一个会话，而不是每次从零开始重跑。这一点很重要，因为它更适合增量修补。

补充一个非常实用的交互能力：

在 stage 审批里，如果你选择 `4` 输入自定义反馈，还可以直接输入控制命令：

- `/skip`：跳过当前 stage，直接继续后面的 stage
- `/back 03`：回到更早的 stage，例如 Stage 03
- `/back 01_literature_survey`：也支持完整 stage slug

这意味着：

- 默认仍然是顺序推进
- 但如果你确认当前 stage 先不做、或者需要回到更早阶段重来，不用硬退出整个 run

注意：

- `/back` 是回到更早阶段，不是跳到更晚阶段
- 如果当前 stage 已经连续失败到超过重试上限，AutoR 也会弹出恢复菜单，让你直接选择“跳过当前阶段”或“回到更早阶段”

还有一个很值得注意的细节：

每个 stage summary 里不只有结果说明，还会包含一个 `Decision Ledger`。

你可以把它理解为“当前 run 的阶段性决策账本”，里面通常会沉淀：

- 哪些关键判断已经锁定
- 还有哪些开放问题
- 当前阶段为什么这样取舍

这些信息会随着 handoff 一起影响后续阶段，所以它不是装饰性文字，而是研究方向保持稳定的重要机制。

---

## 9. 最重要的使用原则：第一轮结果通常会偏 toy

这是新手最容易犯错的地方。

很多人第一次用 AutoR，会看到模型已经：

- 写出了一份 stage summary
- 生成了一些文件
- 甚至已经有了 PDF

于是就误以为“可以过了”。

这通常是错的。

你必须默认这样去看：

**第一轮产物往往只是一个可继续推进的草稿，不是最终质量。**

特别是下面这些情况，基本都不该直接 approve：

- 只写了文字总结，没有真实数据文件
- 只做了 smoke test，没有做正式实验
- 只画了图，没有机器可读结果
- 只写了 PDF，但 claim 没有真实证据支撑
- 只引用了几篇常见论文，没有真正做 survey
- 只给出“计划怎么做”，没有真正把文件写出来

你应该把自己当成研究负责人，而不是旁观者。

AutoR 的强项不是“第一轮就完美”，而是：

- AI 先把执行工作大规模做掉
- 人在关键关口纠偏
- 通过 1~3 轮高质量反馈，把结果逼到真实可用

一句实用的话：

**不要审批“看起来像做过了”的 stage，只审批“已经对下一阶段有真实价值”的 stage。**

---

## 10. 每个 stage 应该怎么审

下面这张表非常重要。

如果你不知道某一阶段该不该打回去，就照这张表看。

| Stage | 至少应该看到什么 | 典型 toy 信号 | 你可以怎么反馈 |
| --- | --- | --- | --- |
| `00_intake` | 目标、约束、资源、评估方向被说清楚 | 只是把你的原话重复了一遍 | “把问题收窄成一个可验证的主问题，并明确成功标准、失败标准和已有资源。” |
| `01_literature_survey` | 关键相关工作、任务背景、数据集/benchmark、差异点、整理后的文献文件 | 只列了少量常识论文；没有真正比较方法 | “扩充 survey，不要只列标题。请整理任务设置、核心方法、评测方式、优缺点，并写入 literature 目录。” |
| `02_hypothesis_generation` | 明确、可检验、可实验的主假设和次级假设 | 只是 brainstorm 了很多想法，没有收敛成一个核心 claim | “不要再发散。锁定 1 个主 claim 和少量可测假设，并说明为什么值得做。” |
| `03_study_design` | 数据集、指标、baseline、ablation、实验矩阵、预算、失败判据 | 只有概念设计；没有可执行实验计划 | “当前设计仍然太 toy。请明确 baseline、指标、数据切分、消融项、统计方式和停止条件。” |
| `04_implementation` | 真实代码、配置、数据准备、 sanity check | 只有代码骨架、伪代码或空脚本 | “不要停留在 skeleton。请把最小可运行实验链路真正跑通，并把关键脚本、配置、日志写出来。” |
| `05_experimentation` | 机器可读结果文件、基线比较、重复运行、失败记录 | 只跑了样例；只在极小子集上试了一次 | “当前实验只是 smoke test。请补齐正式实验、基线对比、重复次数和结果文件，不要只给一张 demo 图。” |
| `06_analysis` | 真实图表、误差分析、失败案例、消融解释、机制性结论 | 只是在复述最好的数值 | “分析不要只做结果复述。请解释为什么有效、在哪些设置失效、哪些因素最关键，并补齐图和表。” |
| `07_writing` | 默认产出 `report/report.md`：每个图片引用都能解析、每个结论都带数字（`--output-format latex` 则要求 LaTeX、Bib、可编译 PDF） | 稿件有形无实：有图注没有图、只有形容词没有测量值、引用虚 | “不要只写出 paper shape。请保证每个核心 claim 都有实验或文献支撑，并完成 citation verification。” |
| `08_dissemination` | review 材料、release/package、摘要性对外交付物 | 只停在论文，不管发布和检查 | “请补齐 release/review 材料，让这个 run 可以被别人检查、复现、展示。” |

一个非常实用的经验是：

**最终 PDF 的质量，大部分不是在 Stage 07 决定的，而是在 Stage 03~06 决定的。**

前面几个阶段如果放水，最后只会得到一个排版正常但内容空的 PDF。

---

## 11. 审批菜单到底该怎么用

### 11.1 什么时候用 `1/2/3`

当 AutoR 自己给出的 refinement suggestion 已经很接近你的判断时，用 `1/2/3` 很省事。

适合场景：

- 它已经识别出缺 baseline
- 它已经识别出缺图
- 它已经识别出 survey 太薄

### 11.2 什么时候用 `4`

这是最有价值的按钮。

当你发现问题比较具体，或者你想强制改变方向时，优先用 `4`。

例如：

- “当前实验只验证了能跑通，没有正式对比。请补齐 baseline A/B/C，并输出 machine-readable results。”
- “不要再扩展题目。把范围收窄到单一主 claim，并围绕这个 claim 设计完整实验。”
- “当前 PDF 虽然编译成功，但结果支撑不足。先回到实验和分析，补齐证据再写。”

### 11.3 什么时候用 `5`

只有在这个 stage 同时满足下面三点时，才建议 approve：

- 方向是对的
- 关键缺口已经补齐
- 对下一阶段已经有真实价值

不是“看起来差不多了”，而是“已经足够让下一阶段建立在坚实基础上”。

### 11.4 什么时候用 `6`

当你发现：

- 目标本身错了
- 环境明显不对
- 你不想继续这个 run

就直接中止，不要勉强推进。

---

## 12. 常用命令速查

| 场景 | 命令 |
| --- | --- |
| 最简单的交互式启动 | `python main.py` |
| 新建一个 run | `python main.py --goal "你的研究目标"` |
| 指定 Claude 作为执行层 | `python main.py --operator claude --model sonnet --goal "..."` |
| 指定 Codex 作为执行层 | `python main.py --operator codex --model default --goal "..."` |
| 允许 Codex 通过 SSH 跑远程 GPU | `python main.py --operator codex --codex-sandbox danger-full-access --goal "..."` |
| 指定投稿 venue | `python main.py --venue neurips_2025 --goal "..."` |
| 同时带资源启动 | `python main.py --goal "..." --resources paper.pdf refs.bib data.csv notes.md` |
| 把大体积 run 放到其他磁盘 | `python main.py --runs-dir /path/to/runs --goal "..."` |
| 跳过 intake | `python main.py --skip-intake --goal "..."` |
| 跑烟测 | `python main.py --fake-operator --goal "Smoke test"` |
| 恢复最近一次 run | `python main.py --resume-run latest` |
| 恢复指定 run | `python main.py --resume-run 20260415_120000` |
| 从某个 stage 重做 | `python main.py --resume-run latest --redo-stage 05` |
| 从某个 stage 回滚 | `python main.py --resume-run latest --rollback-stage 03` |
| 扫描已有项目并推荐切入 stage | `python main.py --goal "..." --project-root /path/to/project` |
| 从你的过往论文语料构建研究者画像 | `python main.py --goal "..." --paper-corpus /path/to/papers` |
| 生成研究方法图并插入论文 | `python main.py --goal "..." --research-diagram` |
| 调大单个 stage 超时上限 | `python main.py --goal "..." --stage-timeout 28800` |

### 12.1 `--redo-stage` 和 `--rollback-stage` 的区别

`--redo-stage`：

- 从指定 stage 重新开始做
- 更适合“这个阶段做得不好，但前面阶段没有根本性错误”

例如：

```bash
python main.py --resume-run latest --redo-stage 05
```

意思是：

- 前面阶段保留
- 从 Stage 05 重新实验

`--rollback-stage`：

- 把指定 stage 以及其后的阶段都标记为需要重做
- 更适合“更早的假设、设计或方向变了”

例如：

```bash
python main.py --resume-run latest --rollback-stage 03
```

意思是：

- Stage 03 以及后面的内容都应该视为失效
- 从 Stage 03 重新往后推进

如果你修改了研究问题、主假设、baseline 设计、数据设置，通常应该用 rollback，而不是简单 redo。

### 12.2 stage 标识其实不只一种写法

很多人以为只能写 `03`。

实际上，AutoR 当前接受这些写法：

- `03`
- `3`
- `03_study_design`

所以这些命令都成立：

```bash
python main.py --resume-run latest --redo-stage 03
python main.py --resume-run latest --redo-stage 3
python main.py --resume-run latest --redo-stage 03_study_design
```

如果你经常恢复 run，这个细节很省事。

### 12.3 `--runs-dir` 很适合重实验或大文件场景

默认情况下，run 都写在仓库下的 `runs/`。

但如果你要：

- 跑很多实验
- 生成较大的中间结果
- 把 run 放到更大的磁盘
- 把仓库代码和运行产物分开

那就很适合显式指定：

```bash
python main.py --runs-dir /mnt/large-disk/autor-runs --goal "..."
```

这不会改变主流程，只是把 run 存储位置换掉。

---

## 13. 这些技巧最能拉高最终质量

### 技巧 1：目标一定要窄

差的目标：

```text
研究一下多智能体
```

好的目标：

```text
研究在固定参数预算下，增加专家数是否能提升 MoE-LoRA 的泛化能力，并产出一份可投稿风格的 PDF。
```

你的目标最好至少包含：

- 研究问题
- 任务或场景
- 约束条件
- 你想要的最终产物

### 技巧 2：尽量带资源开跑

以下资源越早给，质量越高：

- 关键论文 PDF
- 现成的 `.bib`
- baseline 结果表
- 数据样本
- 你自己的想法笔记
- 已有代码仓库

空白开局不是不行，但更容易让第一轮偏 toy。

### 技巧 3：第一轮不要心软

如果第一轮产物出现下面任何一个问题，就不要 approve：

- 没有真实实验
- 没有真实数据文件
- 没有 figure
- 没有 PDF
- PDF 只是形式完成，没有证据支撑
- 只是“计划下一步做什么”

你放水一次，后面往往要多补三次。

### 技巧 4：反馈要具体，不要说“再完善一下”

差的反馈：

```text
写得更好一点
```

好的反馈：

```text
当前实验仍然过于 toy。请至少补齐两个强 baseline、一组关键 ablation、机器可读结果文件，以及对失败案例的记录。不要只给 summary。
```

### 技巧 5：Stage 03、04、05 是质量核心

如果这三步没有守住，Stage 07 再漂亮也只是空壳。

你在这三步要特别强硬地检查：

- 实验设计是否可执行
- 代码是否真的跑起来
- 结果是否真的落盘

### 技巧 6：尽早确定 `--venue`

如果你知道最后想走会议稿还是期刊稿，建议开局就指定。

这样 Stage 07 不会临时换写作风格，结构更稳。

### 技巧 6.5：新手一般不要急着 `--skip-intake`

如果你的题目还不够清楚，或者资源还没整理好，建议保留 intake。

`--skip-intake` 更适合下面这种情况：

- 目标已经非常明确
- 你已经准备好了资源
- 你很清楚自己希望从正式研究阶段直接开始

### 技巧 7：用 `--redo-stage` 做局部返工

如果只是某一阶段质量不好，不需要重开整个 run。

例如写作太弱，但前面实验没问题：

```bash
python main.py --resume-run latest --redo-stage 07
```

### 技巧 8：用 `--rollback-stage` 处理“方向变了”

如果你改了主假设、实验设计、数据设置，不要偷懒。

直接回滚到真正受影响的 stage，后面全部重做。

### 技巧 9：已有项目别从零开始

如果你已经有一个项目仓库：

```bash
python main.py \
  --goal "Turn this project into a stronger research package." \
  --project-root /path/to/your/project
```

AutoR 会扫描已有项目状态，并推荐一个更合理的切入 stage。

### 技巧 10：已有论文积累也别浪费

如果你之前已经写过不少相关论文：

```bash
python main.py \
  --goal "Build a new paper in the style and topic continuity of my prior work." \
  --paper-corpus /path/to/your/papers
```

推荐先装：

```bash
pip install pymupdf
```

这样 PDF 文本提取会更完整。

### 技巧 11：长实验记得调超时

默认单个 stage 的超时是 4 小时。

如果你知道 Stage 05 很重，可以提前调大：

```bash
python main.py --goal "..." --stage-timeout 28800
```

### 技巧 12：`--research-diagram` 是增强项，不是必需项

如果你想在 Stage 07 后自动生成一个方法图并插入论文，可以开启：

```bash
python main.py --goal "..." --research-diagram
```

推荐先装：

```bash
pip install google-genai pillow pyyaml
```

然后设置：

- `GOOGLE_API_KEY`
- 或 `GEMINI_API_KEY`
- 或 `configs/diagram_config.yaml`

这会锦上添花，但不是研究质量本身的来源。

还有一个实务上很重要的点：

**就算方法图生成失败，也不会让整个 run 直接报废。**

所以你可以把它当成增强项，而不是把整个研究流程绑死在它上面。

### 技巧 13：会看调试文件，排障效率会高很多

当你怀疑“为什么这个 stage 老出问题”“为什么恢复后行为不对”“为什么写作阶段没引用到前面的结果”时，不要只盯着终端输出。

这些文件非常有用：

- `run_manifest.json`：看每个 stage 当前是 pending、running、approved、stale 还是 dirty
- `prompt_cache/`：看这个 stage 当时到底拿到了什么 prompt
- `operator_state/`：看 session、attempt 和记忆恢复状态
- `handoff/`：看前面阶段给后面阶段传了什么压缩交接信息
- `logs_raw.jsonl`：看最原始的 agent 流式输出

这几个文件能显著降低“我不知道系统到底在干什么”的感觉。

### 技巧 14：关注结构化产物，不要只看 PDF

下面这些文件很容易被忽略，但它们对判断 run 质量非常重要：

- `workspace/literature/sources.json`
- `workspace/literature/claims.json`
- `workspace/notes/hypothesis_manifest.json`
- `workspace/results/experiment_manifest.json`
- `workspace/artifacts/citation_verification.json`

可以简单理解为：

- `sources.json` / `claims.json`：文献和 claim 的结构化证据账本
- `hypothesis_manifest.json`：Stage 02 收敛出来的 typed hypothesis
- `experiment_manifest.json`：Stage 05 以后供分析和写作消费的机器可读实验清单
- `citation_verification.json`：Stage 07 对引用和 claim 覆盖情况的结构化检查

如果这些文件缺失、很空、或者明显和 PDF 内容不一致，通常说明这个 run 还不够扎实。

---

## 14. 可直接复制的高质量反馈模板

下面这些话你可以直接在审批菜单选 `4` 时粘贴进去。

### 14.1 觉得 survey 太薄

```text
当前文献综述仍然太薄，不要只列常见工作。请扩充到真正能支撑选题判断的程度，明确任务设置、关键 baseline、主要差异点、常见评测方式和现有缺口，并把整理结果写入 literature 目录。
```

### 14.2 觉得假设不够聚焦

```text
不要继续发散多个想法。请收敛到一个最值得验证的主 claim，并把其他想法降级为备选或消融。这个 stage 的目标是形成一个可实验、可否证、可写成论文主线的假设。
```

### 14.3 觉得实验设计太 toy

```text
当前 study design 仍然过于 toy。请明确数据集、指标、baseline、ablation、训练预算、随机种子、失败判据和结果记录格式。不要只写概念计划，要形成可直接执行的实验矩阵。
```

### 14.4 觉得实现只是骨架

```text
当前实现还停留在代码骨架层面。请把最小可运行链路真正跑通，包括数据准备、核心脚本、配置文件和 sanity check，并把关键脚本路径和运行方式写清楚。
```

### 14.5 觉得实验只是 smoke test

```text
当前实验结果不足以支撑论文主张，看起来更像 smoke test。请补齐正式实验、基线对比、关键 ablation、重复运行和机器可读结果文件，不要只给文字总结或单张图。
```

### 14.6 觉得分析只是在复述结果

```text
当前分析仍然停留在复述数值层面。请增加误差分析、失败案例、机制解释和关键图表，说明为什么方法有效、在哪些条件下失效，以及这些结论如何影响论文主线。
```

### 14.7 觉得 PDF 只是“像论文”

```text
当前 PDF 虽然已经成形，但证据仍然不足。请确保每个核心 claim 都能追溯到真实实验、图表或文献依据，并完成 citation verification。不要只做 paper-shaped output。
```

---

## 15. 想最快做出高质量 PDF，推荐这样做

如果你的目标很明确：**尽快做出一份最强版本的 PDF**，推荐使用下面这条路线。

### 第一步：把目标收窄到一个清楚的问题

不要从大而空的题目开始。

### 第二步：一开始就给资源

至少给：

- 3~10 篇关键 PDF
- 一份 `.bib`（如果有）
- 任何已有 baseline 结果
- 你的实验想法笔记

### 第三步：开局就指定 venue

例如：

```bash
python main.py \
  --operator claude \
  --model sonnet \
  --venue neurips_2025 \
  --goal "..."
```

### 第四步：在 Stage 03~06 非常严格

这是最关键的部分。

你需要不断确认：

- 不是只有文本
- 不是只有想法
- 不是只有 demo
- 而是真的有代码、数据、结果、图

### 第五步：Stage 07 只接受“可验证的稿件”

不要被“已经有 PDF”这件事骗过去。

好的 Stage 07 至少应当同时具备：

- LaTeX 源文件
- Bib
- 编译成功的 PDF
- citation verification 输出
- 关键 claim 对应的实验和图表

### 第六步：如果前面某一步不对，果断 redo 或 rollback

不要试图在 Stage 07 把前面所有问题补回来，那通常补不回来。

### 第七步：用 Stage 08 补齐对外交付

这样你最终拿到的不是一份孤立 PDF，而是一套更完整的研究产物。

---

## 16. 结果都在哪里看

每次运行都会生成：

```text
runs/<run_id>/
```

其中最常用的路径是：

| 路径 | 作用 |
| --- | --- |
| `runs/<run_id>/user_input.txt` | 你的原始研究目标 |
| `runs/<run_id>/memory.md` | 已批准阶段的跨阶段记忆 |
| `runs/<run_id>/run_config.json` | 当前 run 绑定的 backend、model、venue 等基础配置 |
| `runs/<run_id>/run_manifest.json` | 每个 stage 的状态机信息，恢复、重做、回滚时很有价值 |
| `runs/<run_id>/artifact_index.json` | 对 data/results/figures 的 run 级结构化索引 |
| `runs/<run_id>/stages/` | 每个 stage 的正式总结 |
| `runs/<run_id>/handoff/` | 每个已批准 stage 给后续阶段的压缩交接信息 |
| `runs/<run_id>/prompt_cache/` | 每次 stage attempt 和 repair 的 prompt 缓存 |
| `runs/<run_id>/operator_state/` | 会话、attempt、恢复状态等本地执行状态 |
| `runs/<run_id>/logs.txt` | 文本日志 |
| `runs/<run_id>/logs_raw.jsonl` | 原始流式事件日志 |
| `runs/<run_id>/workspace/literature/` | 文献整理结果 |
| `runs/<run_id>/workspace/code/` | 代码 |
| `runs/<run_id>/workspace/data/` | 数据 |
| `runs/<run_id>/workspace/results/` | 机器可读结果 |
| `runs/<run_id>/workspace/results/experiment_manifest.json` | 标准化实验清单，后续分析和写作都会用到 |
| `runs/<run_id>/workspace/figures/` | 图 |
| `runs/<run_id>/workspace/writing/` | 论文源文件 |
| `runs/<run_id>/workspace/artifacts/` | PDF 和打包产物 |
| `runs/<run_id>/workspace/artifacts/citation_verification.json` | 写作阶段的引用与 claim 覆盖校验结果 |
| `runs/<run_id>/workspace/notes/hypothesis_manifest.json` | 假设阶段提炼出的结构化假设清单 |
| `runs/<run_id>/workspace/reviews/` | review / release 材料 |

如果你想找最终 PDF，优先看：

- `workspace/artifacts/`
- `workspace/writing/`

---

## 17. 常见问题

### 17.1 可以只用中文目标吗？

可以。

你完全可以直接写中文目标和中文反馈。只要目标清楚，AutoR 一样能工作。

### 17.2 新手一定要看源码吗？

不需要。

你完全可以只按本教程操作，把 AutoR 当成一个终端研究系统来用。

### 17.3 为什么第一轮结果常常不够强？

因为真实研究任务本来就不适合靠单轮生成完成。

AutoR 的设计本来就假设：

- 第一轮先形成基础版本
- 人类在审批点施加强监督
- 通过少量高质量反馈把结果逼到真实可用

### 17.4 看到 PDF 就代表任务完成了吗？

不代表。

PDF 只是结果的一部分。

如果没有真实实验、真实图表、真实结果文件、真实引用支撑，PDF 可能只是“像论文”。

### 17.5 我应该更常用 redo 还是 rollback？

经验上：

- 局部质量不够，用 `redo`
- 更早方向变了，用 `rollback`

### 17.6 我能中途换底层执行器吗？

可以。

AutoR 当前支持 `claude` 和 `codex`。恢复 run 时默认会保留之前的 backend，但你也可以显式指定新的 backend。

实务上，如果你要换 backend，最好同时明确从哪个 stage 继续，最稳妥的做法通常是配合 `--redo-stage` 使用。

### 17.7 我想快速掌握整个项目，还需要看什么？

建议按这个顺序：

1. 先看 [../README.md](../README.md)
2. 再跑一次 smoke test
3. 再开一个带 `--resources` 的真实 run
4. 最后再去看 `runs/<run_id>/` 里的真实产物结构

---

## 18. 最后的建议

如果你只记住一件事，请记住这句：

**AutoR 不是替你做决定的，它是替你做执行。**

真正能把最终结果质量拉高的人，仍然是你。

你最该做的不是“让它自己跑完”，而是：

- 把问题定义清楚
- 在关键 stage 不放水
- 用具体反馈逼它补齐证据、实验和写作
- 在需要时果断 redo 或 rollback

这样你才能真正把 AutoR 用成一个高杠杆的科研系统，而不是一个看起来很忙的论文生成器。
