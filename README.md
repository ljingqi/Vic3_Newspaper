# 维多利亚3 年度报纸 Mod —《世界纪闻》

在《维多利亚3》中，每年年初自动把玩家国家的**经济 / 战争 / 外交**数据导出，
交给 DeepSeek LLM 生成一份**19 世纪风格报纸**（Markdown），保存在 `D:/Journal`。

```
┌──────────────────┐   每年1月1日    ┌──────────────────┐
│  游戏端 mod      │ ──────────────▶ │  debug.log       │
│ on_yearly_pulse  │  debug_log 写入 │  (Victoria 3/logs)│
└──────────────────┘                 └────────┬─────────┘
                                              │ 监控
                                 ┌────────────▼─────────┐
                                 │ Python 伴生程序       │
                                 │ 解析→打包Prompt→调用  │
                                 │ DeepSeek API         │
                                 └────────────┬─────────┘
                                              ▼
                                    D:/Journal/<国名>/报纸_1837.md
```

---

## 文件清单

| 路径 | 说明 |
| --- | --- |
| `C:\Users\CHINE\Documents\Paradox Interactive\Victoria 3\mod\v3journal\` | **游戏 mod**（.metadata / common / localization / thumbnail） |
| `D:\Journal\journal.py` | **Python 伴生程序**（主程序） |
| `D:\Journal\config.json` | 配置文件（DeepSeek Key、日志路径等） |
| `D:\Journal\requirements.txt` | Python 依赖（requests） |
| `D:\Journal\README.md` | 本文档 |
| `D:\Journal\<国名>\报纸_<年份>.md` | 生成的报纸（按存档/国名分文件夹，自动产生） |
| `D:\Journal\<国名>\data\raw_<年份>.json` | 每年导出的原始数据（随报纸同放于该存档文件夹，用于 regen 重试） |

> 注意：GitHub 仓库**不包含**以下内容（已在 `.gitignore` 中排除），使用前需自行准备：
> - `config.json`（含你的 DeepSeek API Key，切勿上传）
> - `tools\`（rakaly 等二进制工具，下载方式见下文「工具与环境准备」）
> - 各测试集文件夹（`<国名>\报纸_*.md` 与 `<国名>\data\raw_*.json`，由程序自动生成）

> 每次开始一个新存档并运行 `watch`，都会**新建一个以国名命名的文件夹**（如 `法兰西`）；
> 若同名文件夹已存在（再次用同一国家开新档），自动在名字后加数字（`法兰西2`、`法兰西3`……）。

---

## 工具与环境准备

克隆仓库后，还需要准备三样东西（仓库里都没有）：

1. **下载 Rakaly**：到 [rakaly/cli Releases](https://github.com/rakaly/cli/releases)
   下载 Windows 版（如 `rakaly-cli-windows-*.zip`，内含 `rakaly.exe`），解压后把
   **`rakaly.exe`** 放到 **`D:\Journal\tools\rakaly.exe`**（`tools` 目录需自行创建）。
   `journal_save.py` 会从这里调用它来熔化 `.v3` 存档。
2. **安装 Python 依赖**：
   ```bat
   python -m pip install -r requirements.txt
   ```
3. **创建配置文件 `D:\Journal\config.json`**（仓库不含，模板如下）：
   ```json
   {
     "deepseek_api_key": "sk-你的密钥",
     "deepseek_model": "deepseek-chat",
     "deepseek_base_url": "https://api.deepseek.com/chat/completions",
     "game_log_path": "",
     "journal_dir": "D:/Journal"
   }
   ```

准备完成后，运行 `python journal_save.py check` 可自检存档、rakaly 是否就绪。

---

## 第一步：启用游戏 mod

1. 启动游戏 Launcher（Paradox Launcher）。
2. 在 **Playsets（合集）** 中找到 **V3 Journal 报纸Mod**，勾选启用。
   （如果列表里没出现：Launcher 界面左下角 → **Mods** 标签页，确认能看到该 mod；再回到 playset 启用。）
3. 用该 playset **启动游戏**，开始或载入一个存档。

> mod 采用"松文件"格式（loose files），已包含在
> `Documents\Paradox Interactive\Victoria 3\mod\v3journal\`。
> 游戏版本 1.13.x 已支持（`supported_game_version: 1.13.*`）。
> 若 launcher 识别不到，可在 mod 文件夹旁补一个 `v3journal.mod` 描述符：
> ```
> name="V3 Journal 报纸Mod"
> supported_version="1.13.*"
> path="mod/v3journal"
> ```

## 第二步：配置 DeepSeek API Key

1. 到 [platform.deepseek.com](https://platform.deepseek.com) 注册并申请 API Key（形如 `sk-xxxxxxxx`）。
2. 编辑 `D:\Journal\config.json`（不在仓库内，模板见上文「工具与环境准备」），把 Key 填入 `deepseek_api_key`：

```json
{ "deepseek_api_key": "sk-你的密钥" }
```

3. 可选：`deepseek_model` 可改为 `deepseek-chat`（默认）或 `deepseek-reasoner`（推理模式，更慢）。

## 第三步：运行伴生程序

```bat
cd /d D:\Journal
python -m pip install -r requirements.txt   :: 首次运行, 安装依赖
python journal.py check                      :: 自检 mod 数据是否写入日志
python journal.py test-llm                   :: 测试 API 连通性
python journal.py watch                      :: 持续监控(建议常驻后台)
```

`watch` 会每 5 秒检查一次 `debug.log`。**游戏内每当 1 月 1 日年度滚动**，mod 会写出
一个数据块，伴生程序随即调用 DeepSeek 生成当期报纸并写入
`D:\Journal\<国名>\报纸_<年份>.md`（同时弹出一个游戏内事件提示）。
> 首次运行 `watch` 后会以玩家国名新建文件夹；同一国家再次开新档则生成 `国名2`。

### 全部命令

| 命令 | 作用 |
| --- | --- |
| `python journal.py watch [--force]` | 持续监控日志，新数据到达即生成（后台运行） |
| `python journal.py once [日志路径]` | 扫描一份已有日志文件（测试用，可扫描整份） |
| `python journal.py regen <年份> [--player 国家名]` | 用已保存的原始数据重新生成某年报纸；`--player` 可在旧数据缺玩家名时补填并按国名决定文件夹，例如 `regen 1836 --player 法兰西`（会在全部分档文件夹中查找该年份数据） |
| `python journal.py test-llm` | 测试 DeepSeek API 连通性 |
| `python journal.py check` | 自检：日志路径、|JOURNAL| 标记是否出现、API Key 是否配置 |
| `python journal.py config` | 打印当前生效的配置（隐藏密钥） |

---

## 导出的数据内容（定性档位）

脚本字符串插值不支持输出任意数值，因此 mod 采用**触发式分段**导出量级档位，足够 LLM 把握形势：

- **经济**：GDP、人口量级档位、平均生活水平（SoL，**细分至 2 点区间**如 10~12，并标注是否**低于民众预期**）、恶名
- **法律**：31 项关键法律（政体/选举权/国教/奴隶制/**公民权法案**/**言论自由**/经济制度/教育）的现行状态，逐年对比可侦测**本年度法律变化**（新施行/废除）；模型能看到现行**言论自由**法律以增风味
- **商品价格**：41 种关键商品相对基准价的涨跌档位（暴涨 ≥150% / 上涨 / 暴跌 ≤50% / 下跌 / 平稳），可统计本年度最贵与最便宜的商品
- **战争**：**去年（上一历年）发生的战争记录**——玩家参战或列强参战，仅列主要参加者
  （玩家 / 列强 / 外交博弈的主要方，舍去英国一长串附庸等非主要参加者），含对阵双方、
  起止/和约日期、死伤、耗资、是否已结束；**不含今年是否处于交战状态的信息**
- **外交**：**宿敌名单**（来自 pacts 的 rivalry）、本国条约关系（同盟/防御条约/禁运等）、**附庸国名单**
- **内政**：政体（君主制/共和国/神权制等）、**首都/都城名**（存档直读路线直接取首都 state 的城市 hub 名，如京都；取不到则回退州名；两路都缺失时提示模型按国名常识补填）、统治者姓名、**当前执政利益集团**（组阁集团及其政治力量 clout 占比）、主要利益集团力量格局、恶名
- **民族与宗教**：**前三大民族**（按人口占比排序）及**主要宗教**的占比档位（过半 / 可观 / 有一定占比），提示词中宗教取前三
- **职业构成**：**主要 pop 职业**（农民/劳工/贵族/资本家等 15 种）的占比档位，提示词中取前三
- **移民动向**：本年度成为移民目的地的动向（来自 on_migration_target_created 事件流）
- **民生说明**：提示词附带 SoL 数字档位说明（0~30：5以下赤贫 / 10温饱 / 15小康 / 20富足），模型能据此理解生活水平数字
- **历年对比**：伴生程序会自动把此前几年的原始数据一并交给模型，生成历年发展对照表（含第一大族/第一大教列），让报纸能评述发展轨迹与民族宗教构成变迁

> 如果你需要**精确数值**（GDP 具体数字等），见下文"备选方案"。

---

## 报纸风格与生成方式

**分板块生成**：程序把报纸拆成若干板块，**每次请求只生成一个板块**，最后组合成完整报纸——
这样每个板块只看到它相关的数据，避免一次性长文导致模型漏掉某类数据（例如战争伤亡）：

1. **抬头**（一次请求）：由国名、都城、政体、年份决定报名与抬头（都城若为州名则改用通用都城名）
2. 随后逐板块生成：**头版** → **战事专电**（仅去年战争）→ **外交风云** → **经济要闻** →
   **政界动态**（含法律变化）→ **民族宗教与社会** → **民生访谈** → **邻里富户** →
   **失业民生**（仅当随机州失业率>5%时发送）→ **本报评论**（结合历年对照）→ **广告与启示**

风格要求：

- **半文半白**文风：以白话为主体、晓畅明白，又保留文言的凝练庄重（梁启超、鲁迅及民国初年
  《申报》《大公报》的笔法）。
- **报名动态生成**：报名由【都城/首都】名直接派生，如《罗马公报》《巴黎回声报》
  《江户政闻录》，可结合【政体】微调（如《巴黎共和公报》），并随时代变迁而调整。
- **抬头必须点名国家**：显著写明报名、国名、首都、政体与年份。
- 每个板块**只基于该板块的给定事实合理演绎，不编造具体数字或国家名**。

> 生成速度说明：一份报纸约需 **10~11 次 API 请求**（1 次抬头 + 9~10 个板块，
> 失业民生视失业率而定）。程序已向请求加入
> `"thinking": {"type": "disabled"}` 关闭思考模式以加快生成（若 API 不接受该参数可删除）。

> 已知说明：
> - **数据导出架构(v6)**：快照由 **`on_monthly_pulse_country` + `month = 8`（9月，0索引）** 触发，
>   数据导出全部在**事件 v3journal.1 的 immediate** 中执行——事件 immediate 支持保存作用域插值，
>   可提取**统治者名**（`[SCOPE.sCharacter('x').GetFullNameNoFormatting]`）、**前三大文化名**
>   （`[SCOPE.sCulture('x').GetName]`）。on_action 触发事件前打 `|JOURNAL|SNAP|` 诊断标记，
>   若 SNAP 出现但无数据，说明事件文件未加载（可据此定位）。
> - **首都名**：debug_log 路线受插值限制不输出首都名；**存档直读路线（journal_save.py）**会直接解析
>   首都 state 的城市 hub 名（如德川幕府 → 京都），取不到时回退州名，不再让模型凭空猜测。
> - **民族文化名**：wiki 确认引用文化的方式有 `[GetCulture('文化key').GetName]`（全局函数，需知道
>   key）与 `[SCOPE.sCulture('作用域名').GetName]`（保存作用域，仅在事件 immediate 生效）。当前
>   在 on_action 内用 `[THIS.GetKey]` 尝试取文化 key（若失败则名称为空，仅保留占比档位）。
> - `[THIS.ScriptValue('标准脚本值')]` 实测返回 0，故经济指标用触发器档位（无法输出精确数值）。

---

## 故障排查

| 症状 | 处理 |
| --- | --- |
| `check` 提示日志中无 `|JOURNAL|` 标记 | ① 确认 mod 已在 playset 启用；② 年份还没滚动（需到 1 月 1 日）；③ 查看 `Documents\...\Victoria 3\logs\error.log` 是否有 mod 脚本报错 |
| mod 某行报 `Data error in loc string` | 说明该插值函数在此作用域不可用。`[THIS.GetXxx]` 直连不可靠：国家名须用 `[THIS.GetCountry.GetNameNoFormatting]`，州/人物名须用 `save_scope_as` 保存后再 `[SCOPE.xxx.GetNameNoFormatting]`。请**重启游戏**使 mod 改动生效 |
| `test-llm` 失败 | 检查网络、Key 是否正确、`deepseek_base_url` 是否为 `https://api.deepseek.com/chat/completions` |
| 重复生成/想重试某年 | 用 `regen <年份>`；`watch` 默认跳过已存在的年份，加 `--force` 强制重生成 |
| 报纸太短/太长 | 调 `config.json` 的 `max_tokens`（默认 8000） |
| 生成内容为空 | 推理模型（如 `deepseek-v4-flash`）会把输出预算花在"思考"上。程序已内置自动扩容重试；也可手动把 `max_tokens` 调到 8000~16000 |

---

## 备选方案（若日志方案不可用）

**方案 A — 强制开启 debug 模式（保证 debug_log 写入）**
在 Steam 中右键游戏 → 属性 → 启动选项加入 `-debug_mode`，再启动。正常游玩时
debug.log 其实已在写入（本方案已验证），此开关只是额外保险。

**方案 B — 运行时直接读取游戏自动存档**
游戏默认每年 1 月 1 日把 `autosave.v3` 写入 `Documents\...\Victoria 3\save games\`，
这是游戏运行时持续更新的实时数据源。但 `.v3` 默认是**压缩二进制**格式，纯 Python
无法直接解析，需要借助 [Rakaly CLI](https://github.com/rakaly/cli/releases)
先转为文本，或用 `-debug_mode` 把"存档格式"设为 **Text**。本版本暂未内置该解析，
可作为后续扩展（原始 JSON 已存于 `D:\Journal\data\`，接入解析后可直接复用）。

**方案 C — journal_save.py 存档直读（当前索科托等测试使用的路线）**
`python journal_save.py newspaper <年份>` 用 [Rakaly](https://github.com/rakaly/cli/releases)
（`rakaly.exe` 放在 `D:\Journal\tools\`）熔化最新 `.v3` 存档并提取**精确数据**，
除 GDP/生活水平/识字率/法律变化/条约/列强战事外，还提供：

- **激进派/效忠派占比**：按 `population_radicals` / `population_loyalists` 与全国总人口计算百分比，
  随「社会」「政界」「头版」数据一并交给模型
- **民生访谈板块**：随机选一个州 → 随机选该州一个建筑，取建筑内 **SoL 最低** 的 POP
  （总人口>10），把生活水平、识字率、出生/死亡率、每周收入/支出、受抚养人口比例、
  消费与税赋结构、政治倾向、粮食安全打包成「民生访谈」板块数据，让记者以跟踪采访一户家庭的形式写作
- **邻里富户板块**：同一建筑内 **SoL 最高** 的 POP（总人口>10），以同样的访谈体写作，
  与民生访谈形成贫富对照；建筑内合格 POP 不足 2 个时重新随机建筑
- **失业民生板块（条件发送）**：若随机州失业率（失业POP劳动力/该州总人口）>5%，
  追加该州人口最多的失业 POP + 失业率数据，以同样访谈体写作；否则该板块不发送
- **去年战事**：筛选上一历年发生的战争（玩家参战或列强参战），仅列主要参加者
  （玩家 / 列强 / 外交博弈主要方），附开始/和约日期、参战方、双方死伤与耗资，
  供「战事专电」报道；不含当前交战状态

---

## 已知限制

- `on_yearly_pulse_country` 每年触发一次，报告日期以游戏年度脉冲为准。
- 商品价格、民族宗教占比、战争伤亡/花费为档位（脚本无法输出精确数值）。
- 仅导出**玩家国家**为主视角 + **世界前八强**的战争/外交概览。
- **列强的战争对手**：V3 嵌套作用域迭代器在 ordered_country 内不执行，无法列出"谁在和谁打"，
  仅能给出各列强的交战/和平状态；玩家自己参与战争的对手可正常列出。
- **法律 Amendments**：脚本可遍历（`every_scope_amendment`），但导出其效果/文本不实际（每个修正案
  的 modifiers 复杂），暂不实现。
- **精确数据（非 debug_log 路线）**：已提供 `D:\Journal\saveparse.py` 读取 .v3 存档信封
  （SAV01033 + ZIP gamestate，已验证可读）。默认 gamestate 为**二进制**，需用
  [Rakaly CLI](https://github.com/rakaly/cli/releases) 熔化，或游戏 debug 模式把存档格式
  设为 **Text** 后解析——届时可精确读取 GDP/生活水平/前三大文化名/战争参与方等 debug_log 拿不到的数据。
- **不同民族/宗教 pop 的生活水平**：经查游戏脚本仅有国家级平均 SoL（`c:国家.average_sol`），
  **无按文化/宗教聚合的 SoL 脚本值**，且 V3 未开放人口遍历聚合，故暂无法精确读取各民族/宗教
  pop 的生活水平。当前只能给出民族/宗教的**人口占比档位**。若后续需要，可考虑解析存档
  （.v3 文本化后按 pop 聚合），作为扩展方向。
- **移民**：V3 只暴露"移民目的地创建"（`on_migration_target_created`），无法逐条捕获单个 pop
  迁移；本 mod 记录"某省成为移民目的地"这一档事件。
