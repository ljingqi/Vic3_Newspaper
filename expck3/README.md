# expck3 — CK3 人物记忆缓存与传记流水线实验

为「新建项目」做的先行实验：验证**能否用 CK3 年度自动存档为玩家角色累积「一生记忆」**，
并在**主角死后自动生成传记文本**。全部实验基于真实存档
`山南观察使，边诚_869_02_22.ck3`（游戏 1.19.0.6，东方王朝类 mod 环境）。

> **2026-08-27 重大修正**：记忆机制初版（v1）误判「记忆库键=角色 id、每角色一条」；
> 实测确认（exp6~exp9）：**database 键=记忆 id（与角色共享 id 池）**，
> 角色经 `alive_data.memories`（记忆 id 列表）持有记忆，**每角色可有多条**；
> **角色死亡时 memories 被清空**。以下结论均已按 v2 修正。

## 实验结论（v2 修正后）

| 问题 | 结论 | 依据 |
| --- | --- | --- |
| 记忆系统的真实结构？ | `character_memory_manager.database`：键=**记忆 id**，值=记忆对象（type/participants/creation_date/end_date/variables）；每个角色的 `alive_data.memories` = **记忆 id 列表**（多对多）。 | exp6/exp7/exp9；玩家 11368 有 5 条记忆，仇人浣（10692）有 10 条 |
| 每个角色能有几条记忆？ | **多条**（游戏内可见的事件都有对应记忆）。 | 玩家 5 条：让出夔州/结仇浣/囚禁阿足/丧妻/娶善至；浣 10 条 |
| 非玩家 NPC 死后记忆保留吗？ | ❌ **不保留**：角色死亡时 `alive_data.memories` 被清空（868 活有记忆→869 已死 141 人**全部清空**；对照活人 6792/6793 保留），记忆对象也随之从 database 移除（未引用仅 8 条）。 | exp8 |
| 每年自动存档可用吗？ | ✅ 实测 868.1.1 / 869.1.1 两档存在；`SAV0100e` 信封 + **未压缩明文 pdxscript**；rakaly json 0.6~1s 直接熔化。 | — |
| 缓存库方案？ | ✅ **必要且唯一**：主角死后其生前记忆全部清空，只有历年存档缓存能恢复。`cache/memories.json` 已实现跨档去重合并。 | exp8 + exp4 |
| 主角死后自动生成？ | ✅ `pipeline.py` 扫描→熔化→提取→`player_death` 检测→生成终传；`demo-death` 已演示。 | — |

## 主角「边诚」（id=11368）两年大事（全部来自真实记忆）

**主角亲历（5 条记忆）**：
- 867.9.8 让出夔州（k_kuizhou，归 10798 诚）——同日受任山南观察使（天朝官制轮换）
- 868.1.14 与浣（10692）结仇
- 868.1.14 囚禁前妻阿足（13386）
- 868.1.21 丧妻——阿足被处决，**主角行刑**（dead_data: killer=11368）
- 868.8.18 娶善至（39250）

**交叉读取到的剧情（相关人物记忆）**：
- 868.1.9 浣与阿足相恋 → 868.1.14 浣与阿足分手（broke_up_lovers）
- 868.1.16 仁顺（浣妻）与阿足结仇 → 868.1.21 仁顺仇人身亡
- 浣另有：867.3.7 娶仁顺、868.4.2 私通月霞（月霞同日失踪而亡）、868.12.11 恋慇 等
- 867.9.8 同日：诚（10798）失土、铎（10818）登位——官制大规模轮换

其余档案事实：生 817.1.1；自创边氏（家主）；汉族/经学；科举四试及第；特质轻信/急躁/睚眦必报/学识三阶/身心合一/治理者；执政两年无战役记录；869.2.22 时 52 岁，健康 4.5、国库 219.1 金、直辖 7 地、封臣 9 人、储君 13530。

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `cache_lib.py` | **缓存库核心 v2**：记忆经 `alive_data.memories` → database 提取；玩家一致性保护；相关人物集（家族/家庭/记忆参与者，两轮扩展）；跨档去重合并；`summarize_relations` 结仇汇总（双方视角） |
| `pipeline.py` | 流水线：`scan`（玩家名过滤+熔化+并入+死亡检测）/ `status` / `bio` / `demo-death` / `watch` |
| `biography.py` | 小传生成器 v2：确定性模板，主角亲历/相关人物动态分节，名字查 names.json 兜底 |
| `build_names.py` | 生成 `data/names.json`：**全档 43912 角色 id→中文名 本地化映射表（单独 json）** |
| `exp4_build_cache.py` | 用 data/ 三档重建缓存（v2） |
| `exp6_alive_data_memories.py` | 验证 alive_data.memories = 记忆 id 列表（关键修正实验） |
| `exp7_verify_owner.py` | 记忆归属排查（真实仇人 10692、记忆 id 11368 属 22169） |
| `exp8_dead_memory_retention.py` | **死后记忆清空验证**（141 人全清空 vs 活人 6792/6793 保留） |
| `exp9_owner_of_ids.py` | 撞号记忆 id 真实 owner 查证 |
| `exp1/2/3/5_*.py` | ⚠️ v1 错误假设下的旧实验，已标注废弃（勿作依据） |
| `cache/memories.json` | 缓存产物（schema=2，15 人 41 条记忆，来源 3 档） |
| `data/names.json` | 全档角色名映射（43912 人） |
| `data/melt_*.json` | 三档 rakaly 熔化 JSON（可删除重建） |
| `output/边诚小传_867-869.md` | **小传成品 v2** |

## 用法

```bat
python build_names.py               :: 重建 data/names.json
python exp4_build_cache.py          :: 重建缓存
python pipeline.py scan             :: 扫描存档目录, 并入新档, 死亡检测
python pipeline.py status           :: 缓存状态
python pipeline.py bio              :: 生成小传 md
python pipeline.py demo-death       :: 演示主角死后自动生成
python pipeline.py watch [秒]       :: 循环监控, 主角死后自动产出终传
```

## 存档格式备忘（新项目直接用）

- 手动存档：`SAV0102c` 信封 + 明文 `meta_data` + ZIP（内含单个明文 `gamestate`）。
- 自动存档：`SAV0100e`/`SAV01006` 信封 + 校验行 + **未压缩明文 gamestate**（无 ZIP）。
- 均可 `rakaly json` 直接熔化（0.6~1s，紧凑 JSON）。
- 关键数据位置（熔化后 JSON）：
  - 玩家：`currently_played_characters` / `played_character` / `meta_data`
  - 角色库：`living` / `dead_unprunable` / `characters.dead_prunable`（`dead_data{date,reason,killer,liege,named_title}`）
  - **记忆：`character_memory_manager.database`（键=记忆 id）+ 角色 `alive_data.memories`（id 列表）**
  - 战争 `wars.active_wars`（含 `battle_results`）、战斗 `combats.*`、围城 `sieges`
  - 关系 `opinions.active_opinions` / `relations.active_relations` / `secrets` / `stories.active`
  - 头衔 `landed_titles.landed_titles`（`title_name_data.name` 中文名内嵌）、特质 `traits_lookup`（列表下标=id）、文化 `culture_manager.cultures`、信仰 `religion.faiths`

## 已知限制与下一步（供新项目）

1. **角色死亡即清空记忆** → `watch` 常驻年度存档是硬性要求；死亡档需在角色入 dead 库**之前**的最后一次活档抓取（自动存档是 1.1，手动存可补）。
2. **战争只存活跃** → 历史战役靠战役类记忆 + `combat_results`。
3. **出生地不在存档** → 留白或 mod 变量。
4. **内容 mod 不在本机** → 人名码点解码 + `names.json`；头衔名存档内嵌中文。
5. 下一步建议：LLM 润色（复用 Journal 的 DeepSeek 管线与正向提示词规则）；记忆类型→中文模板库扩充；`watch` 常驻 + 死亡触发讣告；多角色传记（仇人浣的视角小传已具备数据基础）。
