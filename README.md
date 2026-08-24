# 维多利亚3 年度报纸 Mod —《世界纪闻》

在《维多利亚3》中，伴生程序直接读取游戏自动存档，把玩家国家的**经济 / 战争 /
外交**数据交给 DeepSeek LLM 生成一份**可切换四种风格**的报纸（Markdown），统一
保存在本仓库的 `output\` 目录下（下称 `<项目目录>\output`）。

```
┌────────────────────┐   自动存档     ┌──────────────────┐
│ 游戏端 mod（旗帜标记）│ ────────────▶ │  autosave.v3     │
│ 给玩家国家打标记     │               │  (save games)    │
└────────────────────┘               └────────┬─────────┘
                                              │ Rakaly 熔化
                                 ┌────────────▼─────────┐
                                 │ Python 伴生程序       │
                                 │ 解析→打包Prompt→调用  │
                                 │ DeepSeek API         │
                                 └────────────┬─────────┘
                                              ▼
                            <项目目录>/output/<国名>/报纸/报纸_1837.md
```

> 旧版「V3 Journal 报纸Mod」（debug_log 路线，`journal.py watch/once`）已废弃，
> 不再随仓库发布；正式使用请走**存档直读路线**（`journal_save.py`）。

---

## 文件清单

下文用 `<项目目录>` 表示本仓库所在的文件夹（例如 `D:\Journal`），不写死盘符。

| 路径 | 说明 |
| --- | --- |
| `<项目目录>\mod\v3journal_player_flag\` | **游戏 mod（旗帜标记）**：开局给玩家国家打 `v3journal_player` 标记，供存档直读 100% 识别玩家（`descriptor.mod` + `common/on_actions`，随仓库发布） |
| `<项目目录>\journal_save.py` | **Python 伴生程序（存档直读主入口）**：`watch`/`continue` 监控存档，`newspaper`/`magazine` 按年份生成 |
| `<项目目录>\journal.py` | **渲染库**：分板块生成报纸；另提供 `regen` / `test-llm` / `config` 命令 |
| `<项目目录>\magazine.py` | **杂志生成程序**（复用 journal.py 的 API 调用，按政体定制基调） |
| `<项目目录>\htmlview.py` | **阅读页生成器**：把报纸/杂志 Markdown 汇总为单页 `index.html`（可切换报纸/杂志与年份），并提供存量迁移命令 `rebuild` |
| `<项目目录>\saveparse.py` | 存档信封解析工具（读取 .v3 元数据与 gamestate，检测格式） |
| `<项目目录>\config.json` | 配置文件（由 `config.example.json` 复制而来；含你的 DeepSeek Key，**勿上传**） |
| `<项目目录>\config.example.json` | 配置模板（所有参数已填好，仅 API Key 留空） |
| `<项目目录>\requirements.txt` | Python 依赖（requests） |
| `<项目目录>\README.md` | 本文档 |
| `<项目目录>\启动监控.bat` | **一键启动（新档）**：双击运行 `journal_save.py watch` |
| `<项目目录>\启动续传.bat` | **一键启动（旧档）**：双击运行 `journal_save.py continue` |
| `<项目目录>\output\<国名>\报纸\报纸_<年份>.md` | 生成的报纸（每个存档开局一个文件夹，自动产生） |
| `<项目目录>\output\<国名>\杂志\杂志_<年份>.md` | 生成的杂志（与报纸分文件夹，每年一份） |
| `<项目目录>\output\<国名>\index.html` | 会话阅读页：一个页面内切换报纸/杂志版式与年份，双击直接用浏览器阅读 |
| `<项目目录>\output\<国名>\data\raw_<年份>.json` | 每年导出的原始数据（随报纸同放于该会话文件夹，用于 regen 重试） |
| `<项目目录>\output\<国名>\data\pops_<年份>.json` | 每年玩家州 POP 指纹（跨年比对升职/迁移） |
| `<项目目录>\output\<国名>\data\magazine_<年份>.json` | 每年杂志专属数据（战役/移民/改信样本） |

> 注意：GitHub 仓库**不包含**以下内容（已在 `.gitignore` 中排除），使用前需自行准备：
> - `config.json`（含你的 DeepSeek API Key，切勿上传；仓库提供 `config.example.json` 模板，复制改名即可）
> - `tools\`（rakaly 等二进制工具，下载方式见下文「工具与环境准备」）
> - `output\`（各测试集/存档开局文件夹，含 `<国名>\报纸\报纸_*.md`、`<国名>\杂志\杂志_*.md` 与 `<国名>\data\raw_*.json`，由程序自动生成）
> - `docs\`（开发用内部文档，不随仓库发布）

> 每次开始一个新存档并运行 `watch`/`continue`，都会在 **`output\` 内新建一个以国名命名的
> 文件夹**（如 `output\法兰西`）；若同名文件夹已存在（再次用同一国家开新档），自动在名字后
> 加数字（`法兰西2`、`法兰西3`……）。`watch`/`continue` 的续传逻辑不变。

---

## 工具与环境准备

克隆仓库后，还需要准备三样东西（仓库里都没有）：

1. **下载 Rakaly**：到 [rakaly/cli Releases](https://github.com/rakaly/cli/releases)
   下载 Windows 版（如 `rakaly-cli-windows-*.zip`，内含 `rakaly.exe`），解压后把
   **`rakaly.exe`** 放到 **`<项目目录>\tools\rakaly.exe`**（`tools` 目录需自行创建）。
   `journal_save.py` 会从这里调用它来熔化 `.v3` 存档。
2. **安装 Python 依赖**：
   ```bat
   python -m pip install -r requirements.txt
   ```
3. **创建配置文件**：仓库已提供 `config.example.json`（所有参数已填好，仅 API Key 留空），
   复制为 `config.json` 后填入你的 Key：
   ```bat
   copy config.example.json config.json
   ```
   然后编辑 `config.json`，把 `"deepseek_api_key": ""` 改成 `"deepseek_api_key": "sk-你的密钥"`。
   字段说明（所有目录设定与功能开关都集中在 `config.json`）：
   - **目录**：`game_dir` 填游戏安装根目录（如 `F:/Game/steamapps/common/Victoria 3`，
     **存档直读必需**）；`v3_user_dir` / `save_dir` / `game_log_path` / `workshop_dir`
     留空时自动探测默认值；`tools_dir` / `log_dir` / `journal_dir` 留空时分别使用仓库内的
     `tools\` / `logs\` / `output\`。
   - **功能开关**：`newspaper_enabled` / `magazine_enabled` 控制自动管线中的报纸/杂志生成；
     `style_system` 切换文风系统（`legacy` / `dynamic`）；`crime_outcome_engine` 控制刑事
     案例结局引擎；`parallel_generation_enabled` 控制 watch 时报纸/杂志是否并行生成；
     `prompt_log_enabled` 控制是否把请求原文写入 `logs\prompts.log`；`llm_thinking_disabled`
     控制是否发送 `thinking: disabled` 关闭模型思考模式。
   - `deepseek_model` 可选 `deepseek-chat`（默认）或 `deepseek-reasoner`（推理模式，更慢）；
     `newspaper_style` 取 1~4 切换报纸风格（见下文「报纸风格」）。

准备完成后，运行 `python journal_save.py check` 可自检存档、rakaly 是否就绪。

---

## 第一步：安装游戏 mod（玩家旗帜标记）

1. 把仓库 `mod\v3journal_player_flag` 整个文件夹**手动复制**到
   `Documents\Paradox Interactive\Victoria 3\mod\` 下。
   （mod 采用"松文件"格式，文件夹内已含 `descriptor.mod`，无需再补其他文件。）
2. 启动 Paradox Launcher，在 **Playsets（合集）** 中勾选 **V3Journal 玩家标记**。
   （如果列表里没出现：Launcher 界面左下角 → **Mods** 标签页，确认能看到该 mod；再回到 playset 启用。）
3. 用该 playset **启动游戏**，开始或载入一个存档。

> 该 mod 的作用：开局给玩家选择的国家打上 `v3journal_player` 标记，伴生程序读取
> 存档时据此**100% 识别玩家国家**。若不安装，程序会回退到"本地化国名匹配"，
> 部分动态国家（如内战国 D00~D99）可能识别不准。游戏版本 1.13.x 已支持
> （`supported_version: 1.13.*`）。

## 第二步：配置 DeepSeek API Key

1. 到 [platform.deepseek.com](https://platform.deepseek.com) 注册并申请 API Key（形如 `sk-xxxxxxxx`）。
2. 编辑 `<项目目录>\config.json`（由 `config.example.json` 复制而来，见上文「工具与环境准备」），把 Key 填入 `deepseek_api_key`：

```json
{ "deepseek_api_key": "sk-你的密钥" }
```

3. 可选：`deepseek_model` 可改为 `deepseek-chat`（默认）或 `deepseek-reasoner`（推理模式，更慢）。

## 第三步：运行伴生程序

```bat
cd /d <项目目录>
python -m pip install -r requirements.txt   :: 首次运行, 安装依赖
python journal_save.py check                 :: 自检存档与 rakaly 是否就绪
python journal.py test-llm                   :: 测试 API 连通性
python journal_save.py watch                 :: 持续监控自动存档(建议常驻后台)
```

`journal_save.py watch` 会监控最新存档，检测到新年度即调用 DeepSeek 生成当期报纸并写入
`<项目目录>\output\<国名>\报纸\报纸_<年份>.md`；同一快照还会生成当期杂志
`<项目目录>\output\<国名>\杂志\杂志_<年份>.md`。每次写入后自动刷新该会话的
`index.html` 阅读页。`config.json` 的 `newspaper_enabled` / `magazine_enabled` 可分别关闭
自动管线中的报纸 / 杂志生成（手动 `newspaper <年份>` / `magazine <年份>` 命令不受开关限制）。
熔化与解析只做一次，两份输出共享同一快照与本地化缓存。

**一键启动**：日常使用无需手动敲命令，直接双击根目录的
`启动监控.bat`（新档）或 `启动续传.bat`（旧档）即可；窗口关闭前会暂停并提示按键。

> 首次运行会以玩家国名在 `output\` 内新建文件夹；同一国家再次开新档则生成 `国名2`。
> （`journal.py` 现主要作为渲染库被 `journal_save.py` 复用，其 `watch`/`once` 为旧的
> debug_log 路线，仅作保留。）

### 全部命令

| 命令 | 作用 |
| --- | --- |
| `python journal_save.py check` | 自检：存档是否就绪、rakaly 是否就位 |
| `python journal_save.py melt` | 熔化最新存档到 `tools\melt.json` 缓存（开发用） |
| `python journal_save.py watch` | 持续监控自动存档，新年度自动生成报纸+杂志（建议常驻后台） |
| `python journal_save.py continue` | 续传：沿用该国家最新文件夹，缺当年产物先补生成，再进入监控 |
| `python journal_save.py newspaper <年份>` | 用当前存档补生成某年报纸 |
| `python journal_save.py magazine <年份>` | 用当前存档补生成某年杂志（每年报纸与杂志为两个独立文件） |
| `python htmlview.py rebuild [国家名]` | 为已有会话迁移旧版目录结构（报纸/杂志分文件夹）并生成 `index.html` 阅读页；不传国家名则处理全部会话（跳过 `Archive`） |
| `python journal.py regen <年份> [--player 国家名]` | 用已保存的原始数据重新生成某年报纸；`--player` 可在旧数据缺玩家名时补填并按国名决定文件夹，例如 `regen 1836 --player 法兰西`（会在全部分档文件夹中查找该年份数据） |
| `python journal.py test-llm` | 测试 DeepSeek API 连通性 |
| `python journal.py config` | 打印当前生效的配置（隐藏密钥） |

---

## 交给 LLM 的数据内容

存档直读路线从 `.v3` 存档中提取精确数据（GDP、生活水平、识字率、商品价格等），
部分无法精确读取的指标（如民族宗教占比）以档位形式给出，足够 LLM 把握形势：

- **经济**：GDP、人口、平均生活水平（SoL）的**精确数值**（并标注是否**低于民众预期**）、恶名
- **法律**：**本年度新施行/废除的法律**明细（逐年对比可侦测法律变化）；另附现行**言论自由**法律状态以增风味
- **商品价格**：关键商品相对基准价的涨跌（含本年度最贵与最便宜商品的统计）
- **战争**：**去年（上一历年）发生的战争记录**——玩家参战或列强参战，仅列主要参加者
  （玩家 / 列强 / 外交博弈的主要方，舍去英国一长串附庸等非主要参加者），含对阵双方、
  起止/和约日期、死伤、耗资、是否已结束；**不含今年是否处于交战状态的信息**
- **外交**：**宿敌名单**（来自 pacts 的 rivalry）、本国条约关系（同盟/防御条约/禁运等）、**附庸国名单**
- **内政**：政体（君主制/共和国/神权制等）、**首都/都城名**（存档直读直接取首都 state 的城市 hub 名，如京都；取不到则回退州名，再不行提示模型按国名常识补填）、统治者姓名、**当前执政利益集团**（组阁集团及其政治力量 clout 占比）、主要利益集团力量格局、恶名
- **民族与宗教**：**前三大民族**（按人口占比排序）及**主要宗教**的占比档位（过半 / 可观 / 有一定占比），提示词中宗教取前三
- **职业构成**：**主要 pop 职业**（农民/劳工/贵族/资本家等 15 种）的占比档位，提示词中取前三
- **移民动向**：本年度成为移民目的地的动向（来自存档 POP 指纹跨年比对）
- **民生说明**：提示词附带 SoL 数字档位说明（0~30：5以下赤贫 / 10温饱 / 15小康 / 20富足），模型能据此理解生活水平数字
- **历年对比**：伴生程序会自动把此前几年的原始数据一并交给模型，生成历年发展对照表（含第一大族/第一大教列，默认前 10 年 + 当年 = 11 行，首行保留最早可得年份），让报纸能评述发展轨迹与民族宗教构成变迁

---

## 报纸风格与生成方式

**分板块生成**：程序把报纸拆成若干板块，**每次请求只生成一个板块**，最后组合成完整报纸——
这样每个板块只看到它相关的数据，避免一次性长文导致模型漏掉某类数据（例如战争伤亡）：

1. **抬头**（一次请求）：由国名、都城、政体、年份决定报名与抬头；抬头中的「国名」为
   **正式国名**（国名+政体 合并，如 大清+专制帝国→大清帝国、法兰西+第三共和国→法兰西第三共和国，
   美利坚合众国等已以「国」结尾者豁免），政体字段不再单独出现
   （都城若为州名则改用通用都城名）
2. 随后逐板块生成：**头版** → **战事专电**（仅去年战争）→ **外交风云** → **经济要闻** →
   **政界动态**（含法律变化）→ **民族宗教与社会** → **民生访谈** → **邻里富户** →
   **失业民生**（仅当随机州失业率>5%时发送）→ **本报评论**（结合历年对照）→ **广告与启示**

### 四种风格切换

编辑 `config.json` 的 `newspaper_style`（1~4）即可切换报纸风格，数据内容不变：

| 值 | 风格 | 报名体例示例 | 代表性栏目 |
| --- | --- | --- | --- |
| 1 | 大公报（20世纪初） | 《罗马公报》《巴黎回声报》 | 头版、战事专电、外交风云、本报评论 |
| 2 | 人民日报（20世纪） | 《巴黎日报》《京都早报》 | 今日要闻、军事报道、时政要闻、社论 |
| 3 | 新华网（新华社风格） | 《巴黎新华报》《京都新华电讯》 | 要闻、军事新闻、时政新闻、新华时评 |
| 4 | 泰晤士报（中文） | 《罗马泰晤士报》《巴黎泰晤士报》 | 头版要闻、战地报道、政坛纪事、社评 |

四种风格使用完全相同的数据（GDP、人口、战争、外交、政体等），只更换报名规则、文风与
栏目名；每种风格的栏目名均不相同。改完数字后，用
`python journal_save.py newspaper <年份>` 或 `python journal.py regen <年份>`
即可用新风格重写同一年份。

风格要求：

- **半文半白**文风：以白话为主体、晓畅明白，又保留文言的凝练庄重（梁启超、鲁迅及民国初年
  《申报》《大公报》的笔法）。
- **报名动态生成**：报名由【都城/首都】名直接派生，如《罗马公报》《巴黎回声报》
  《江户政闻录》，可结合【政体】微调（如《巴黎共和公报》），并随时代变迁而调整。
- **抬头必须点名国家**：显著写明报名、正式国名（国名+政体 合并）、首都与年份（政体并入国名后
  不再单列，如《北京官报》下「国名：大清帝国｜都城：北京｜年份：1836」）。
- 每个板块**只基于该板块的给定事实合理演绎，不编造具体数字或国家名**。

> 生成速度说明：一份报纸约需 **10~11 次 API 请求**（1 次抬头 + 9~10 个板块，
> 失业民生视失业率而定）。程序默认在请求中加入 `"thinking": {"type": "disabled"}`
> 关闭思考模式以加快生成，可用 `config.json` 的 `llm_thinking_disabled` 开关控制。

### 新旧两套文风系统（style_system）

所有文风提示词（4 种报纸风格、8 类政体杂志基调、言论自由文案）已统一迁移到 **`style.py`**，
并在 `config.json` 提供 `style_system` 开关：

| 值 | 说明 |
| --- | --- |
| `legacy`（默认） | 旧系统：`newspaper_style` 取 1~4 固定风格，行为与旧版完全一致 |
| `dynamic` | 新系统：依据存档中**已解锁的社会科技**（Rationalism 政治分支、时代加权）+ **政体** +
  **Distribution of Power 投票权法律**，自动解析 1~5 档文风 |

新系统原则：Rationalism 以下（民主→平权→人权/社会主义→政治动员…）解锁的科技越少越保守，
越多越现代。五档：**1 守成（邸报/官报体）→ 2 改良（半文半白公报）→ 3 现代（白话大报）→
4 进步（通稿+深度报道）→ 5 先锋（思潮周刊）**。

政体/投票权修正：

- 进步政体（各共和国）加档，神权/酋邦压档；
- 投票权加权：普选/无政府 +2、普查投票 +1、地产投票 −1、专制 −2 等；
- 硬性封顶：酋邦封顶 3 档；地产投票的神权制封顶 3 档；专制君主制封顶 3 档；
  **普选制的君主立宪国可上「先锋」档**。

新系统依赖存档解析新增的 `tech_keys`（已研发科技原始 key）与 `dop_law`（当前投票权法律）字段，
它们随 `data/raw_*.json` 持久化，`regen` 同样可用。切换后重新生成即可：
`python journal_save.py newspaper <年份>` / `python journal_save.py magazine <年份>`。

> 数据说明（存档直读路线）：
> - **首都名**：直接解析首都 state 的城市 hub 名（如德川幕府 → 京都），取不到时回退州名，
>   不再让模型凭空猜测。
> - **统治者名 / 前三大文化名**：从存档人物与文化定义直接读取（`common/character_templates`、
>   `common/cultures` 等游戏数据，路径由 `config.json` 的 `game_dir` 派生）。

---

## 故障排查

| 症状 | 处理 |
| --- | --- |
| `journal_save.py check` 提示找不到存档 | 确认 `config.json` 的 `save_dir` 正确（默认自动探测 `Documents\...\Victoria 3\save games\`），并已用该 playset 启动过游戏 |
| `journal_save.py check` 提示 rakaly 未就绪 | 把 `rakaly.exe` 放到 `<项目目录>\tools\`（路径可由 `config.json` 的 `tools_dir` 调整） |
| 存档识别不到玩家国家 | 确认已在 Launcher 启用 **V3Journal 玩家标记** mod；未启用时程序回退"本地化国名匹配"，部分动态国家（内战国 D00~D99）可能不准 |
| `test-llm` 失败 | 检查网络、Key 是否正确、`deepseek_base_url` 是否为 `https://api.deepseek.com/chat/completions` |
| 重复生成/想重试某年 | 用 `regen <年份>`；`watch` 默认跳过已存在的年份，加 `--force` 强制重生成 |
| 报纸太短/太长 | 调 `config.json` 的 `max_tokens`（默认 8000） |
| 生成内容为空 | 推理模型（如 `deepseek-v4-flash`）会把输出预算花在"思考"上。程序已内置自动扩容重试；也可手动把 `max_tokens` 调到 8000~16000 |

---

## 存档直读路线（当前主路线）

`journal_save.py` 用 [Rakaly](https://github.com/rakaly/cli/releases)
（`rakaly.exe` 放在 `<项目目录>\tools\`）熔化最新 `.v3` 存档并提取**精确数据**，
除 GDP/生活水平/识字率/法律变化/条约/列强战事外，还提供：

- **激进派/效忠派占比**：按 `population_radicals` / `population_loyalists` 与全国总人口计算百分比，
  随「社会」「政界」「头版」数据一并交给模型
- **民生访谈板块**：随机选一个州 → 随机选该州一个建筑，取建筑内 **SoL 最低** 的 POP
  （总人口>10），把生活水平、识字率、出生/死亡率、每周收入/支出、受抚养人口比例、
  消费与税赋结构、政治倾向、粮食安全打包成「民生访谈」板块数据，让记者以跟踪采访一户家庭的形式写作
- **邻里富户板块**：同一建筑内 **SoL 最高** 的 POP（总人口>10），以同样的访谈体写作，
  与民生访谈形成贫富对照；建筑内合格 POP 不足 2 个时重新随机建筑。
  追踪对象生活水平低于「富户」档（SoL<15）时，板块称谓自动降格为「殷实之家」，
  避免头衔与数据打架
- **家庭账本**：访谈板块附该户月收入/支出/结余；高生活水平人群消费由积蓄支撑时
  （结余为负），补「靠历年积蓄填补」一行说明；商品消费量读数可按
  `interview_consumption_qty_scale` 系数放大，食品类另有 `interview_food_qty_min` 每月下限
- **失业民生板块（条件发送）**：若随机州失业率（失业POP劳动力/该州总人口）>5%，
  追加该州人口最多的失业 POP + 失业率数据，以同样访谈体写作；否则该板块不发送
- **去年战事**：筛选上一历年发生的战争（玩家参战或列强参战），仅列主要参加者
  （玩家 / 列强 / 外交博弈主要方），附开始/和约日期、参战方、双方死伤与耗资，
  供「战事专电」报道；不含当前交战状态

---

## 已知限制

- **不同民族/宗教 pop 的生活水平**：经查游戏脚本仅有国家级平均 SoL（`c:国家.average_sol`），
  **无按文化/宗教聚合的 SoL 脚本值**，且 V3 未开放人口遍历聚合，故暂无法精确读取各民族/宗教
  pop 的生活水平。当前只能给出民族/宗教的**人口占比档位**。若后续需要，可考虑解析存档
  （.v3 文本化后按 pop 聚合），作为扩展方向。
- **依赖游戏数据目录**：存档直读需要解析游戏本体文件（本地化、法律、建筑、文化等），
  首次运行前必须在 `config.json` 填好 `game_dir`（游戏安装根目录）。
- **存档为二进制格式**：`.v3` 默认是压缩二进制，必须借助
  [Rakaly CLI](https://github.com/rakaly/cli/releases) 熔化后才能解析。
