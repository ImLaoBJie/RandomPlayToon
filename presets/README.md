# 角色自动配置与风格预设

这里是全部角色配置与风格参数的唯一维护目录。选择已登记版本的 PMX 并新建工程时，插件自动读取对应配置，不要求手动导入 JSON。

当前代码按 PMX 内容指纹识别，不按文件名或模型名称匹配。本次整理未改变识别规则。

## 目录

```text
presets/
├── Alice/                 # model.json：本角色自动匹配与材质配置
├── SunnaMaid/              # 其余角色同样各自一个文件夹
├── …
├── shared/                # 共享默认参数、各角色参数覆盖和材质修正
├── Vivian/                # model.json 与两套可选风格参数
├── AliceSummer/           # 泳装角色的两套参数，默认自动使用 01
├── LucySummer/
├── VivianSummer/
├── YuzuhaSummer/
└── catalog.json           # 全部模型识别，以及四个泳装角色的默认风格索引
```

全部 `.scene.json` 已删除，也不再加载其中的灯光、世界、相机和渲染设置。新建仍使用构建器的基础场景；已有工程及其灯光和用户调整不受影响。

## 全部自动角色配置

| 角色／形态 | 新建时自动使用 | 可选完整风格 | 自动模型配置 |
| --- | --- | --- | --- |
| Vivian | 内置角色默认配置 | [01_CrispCel](Vivian/01_CrispCel.json)、[02_CoolGlow](Vivian/02_CoolGlow.json) | [配置](Vivian/model.json) |
| Alice | 内置角色默认配置 | 未单独导出 | [配置](Alice/model.json) |
| SunnaMaid | 内置角色默认配置 | 未单独导出 | [配置](SunnaMaid/model.json) |
| Yuzuha | 内置角色默认配置 | 未单独导出 | [配置](Yuzuha/model.json) |
| Pyrois | 内置角色默认配置 | 未单独导出 | [配置](Pyrois/model.json) |
| AriaDiscordant | 内置角色默认配置 | 未单独导出 | [配置](AriaDiscordant/model.json) |
| AriaRobotDiscordant | 内置角色默认配置 | 未单独导出 | [配置](AriaRobotDiscordant/model.json) |
| NangongYuRapsody | 内置角色默认配置 | 未单独导出 | [配置](NangongYuRapsody/model.json) |
| Yidhari | 内置角色默认配置 | 未单独导出 | [配置](Yidhari/model.json) |
| YeShunguang | 内置角色默认配置 | 未单独导出 | [配置](YeShunguang/model.json) |
| YeShunguang_White | 内置角色默认配置 | 未单独导出 | [配置](YeShunguang_White/model.json) |
| Norma | 内置角色默认配置 | 未单独导出 | [配置](Norma/model.json) |
| Remielle | 内置角色默认配置 | 未单独导出 | [配置](Remielle/model.json) |
| AliceSummer | 01_CrispCel 参数（场景光照模式） | [01_CrispCel](AliceSummer/01_CrispCel.json)、[02_CoolGlow](AliceSummer/02_CoolGlow.json) | [匹配索引](catalog.json) |
| LucySummer | 01_CrispCel 参数（场景光照模式） | [01_CrispCel](LucySummer/01_CrispCel.json)、[02_CoolGlow](LucySummer/02_CoolGlow.json) | [匹配索引](catalog.json) |
| VivianSummer | 01_CrispCel 参数（场景光照模式） | [01_CrispCel](VivianSummer/01_CrispCel.json)、[02_CoolGlow](VivianSummer/02_CoolGlow.json) | [匹配索引](catalog.json) |
| YuzuhaSummer | 01_CrispCel 参数（场景光照模式） | [01_CrispCel](YuzuhaSummer/01_CrispCel.json)、[02_CoolGlow](YuzuhaSummer/02_CoolGlow.json) | [匹配索引](catalog.json) |

以上共 17 个角色／形态配置。独立武器和附件也按模型名称各自存放，未计入角色数。

## 默认参数从哪里来

- [catalog.json](catalog.json)：模型识别目录；每个模型的分区、贴图配对及适配证据位于 `<角色或模型名>/model.json`。
- [shared/parameter_overrides.json](shared/parameter_overrides.json)：角色参数覆盖。
- [shared/character_refinement.json](shared/character_refinement.json)：角色专属参数及处理选项。
- [shared/detail_profiles.json](shared/detail_profiles.json)：透明、描边、反射等材质适配选项。
- [shared/vivian_global_defaults.json](shared/vivian_global_defaults.json)：共享面板默认参数。

这些配置会自动应用，不是需要用户导入的个人风格文件。材质构建算法、共享控制定义及普通薇薇安的底层网格校准／节点模板仍属于插件实现资源。

## 可选风格文件

四个泳装角色新建时自动加载 01_CrispCel 面板参数。02_CoolGlow 使用虚拟光照与亮块，是备用风格。普通薇薇安自动使用原有默认模板，两份独立 JSON 是另外提供的可选风格，并未替换其自动默认配置。

需要主动切换已有工程的整套风格时，才使用现有“载入个人预设”按钮。光照模式按钮只切换模式，不替换整套参数；载入风格 JSON 不替换灯光对象、世界或相机。

打包脚本将本目录直接放入安装包的 `random_play_toon/presets/`；这是发布副本，源码中不另行维护。打开旧工程不会重新应用默认参数。
