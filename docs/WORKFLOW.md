# 安装与输入准备

## 安装插件

使用 Blender 5.2，渲染引擎选择 EEVEE。PMX 导入已包含在 RandomPlayToon 安装包中，不需要另外安装 MMD Tools。

从源码生成安装包时，在仓库根目录运行：

```sh
python python_scripts/generalization/release/package_release.py
python python_scripts/animation/release/package_copy.py
```

使用可用的 Python 3。ZIP 输出到本地 `dist/`。在 Blender“首选项 → 插件 → 从磁盘安装”选择对应 ZIP 并启用。安装包中的源码与必要节点资源由本仓库生成，角色资产需自行下载。

## Toon 输入目录

从 [模之屋](https://www.aplaybox.com/) 获取官方发布的角色模型包，解压后保留原文件结构。不要只取出 PMX 而丢弃纹理目录。

```text
models/
└── Vivian/
    ├── 薇薇安.pmx
    ├── skin.bmp
    ├── hair.bmp
    ├── tex/
    │   ├── 体.png
    │   ├── 颜.png
    │   └── 髮.png
    └── spa/
        └── ...
```

文件名与纹理格式随模型包而变化，图中仅为结构示意。Toon 的“配套纹理目录”留空时，按 PMX 所在目录查找原相对路径；模型与纹理分开保存时，选择能包含 `tex/`、`spa/` 等原相对目录的纹理根目录。

从 [ZZ-Model-Importer-Assets](https://github.com/leotorrez/ZZ-Model-Importer-Assets/tree/main) 获取对应的渲染素材，保留角色目录中的 DDS、索引和配套文件。

```text
ZZ-Model-Importer-Assets/
└── PlayerCharacterData/
    └── Vivian/
        ├── hash.json
        ├── VivianBodyADiffuse.dds
        ├── VivianBodyANormalMap.dds
        ├── VivianBodyALightMap.dds
        ├── VivianBodyAMaterialMap.dds
        ├── VivianHairADiffuse.dds
        ├── ...
        └── VivianFaceADiffuse.dds
```

“渲染素材目录”可选择单个角色目录、`PlayerCharacterData/` 或资产库根目录。素材所属角色与服装要和模型一致；已适配配置会检查输入内容，不能以改名绕过版本差异。

## Toon 操作与输出

1. 3D 视图按 N，进入 **RandomPlayToon**。
2. 填写模型 PMX、配套纹理目录、渲染素材目录和新的 `.blend` 输出路径。
3. 点击 **一键重建**，等待后台任务完成。
4. 点击 **打开重建结果**。
5. 把任意窗口切换为 **文本编辑器**，在顶部的文本列表中选择 **`01_启用风格面板`**，点击 **运行脚本**，或把鼠标放在文本编辑器内按 **Alt+P**。
6. 回到 3D 视图按 **N**，打开角色英文名对应的参数页，选择风格或修改单个部位。
7. 保存模板，按 F12 查看最终描边、透眼与辉光。

参数面板脚本运行一次即可，只启用界面，不会重新导入模型或重建材质。重新启动 Blender 后，如果参数面板没有出现，再运行一次。

生成的 `.blend` 包含用户提供的模型和纹理、重建材质、控制节点、效果合成与场景。旁边的 `.report.json` 和工程内的构建报告记录输入匹配、例外及检查结果。已有 `.blend` 可以直接打开调参，平时不需要重复导入。

## Copy 输入目录

Copy 使用已保存的 Toon 着色模板，以及匹配的 Alembic 导出结果。缓存需保留配套校验文件：

```text
animation-input/
├── animation.abc
├── metadata.json
├── verification.npz
├── material_animation.npz
└── camera.vmd                # 可选，独立提供的相机轨道
```

`metadata.json` 描述模型身份、缓存哈希、帧率、时长、单位比例和网格路径；`verification.npz` 保存抽样几何、UV、法线与面分区；`material_animation.npz` 保存材质／可见性检查数据。这些应由导出流程一并生成，不能用空文件替代。

当前 Copy 接受已验证的 Vivian、SunnaMaid 缓存结构，网格路径为 `/character/mesh`，输入元数据 schema 为 1。这个源码仓库不包含生成该验证结构的动画导出器。用户已有普通 `.abc` 时，需要先将导出和校验数据适配到此输入约定。

## Copy 操作与输出

1. 进入 N 侧栏 **ABC渲染**，选择保存好的着色模板和 ABC。
2. 输入新的 `.blend` 完整路径，或先用“选择目录”选择输出文件夹。
3. 选择输出帧率，填写缓存实际包含的预热秒数，点击 **将渲染效果套用到 ABC**。
4. 完成后 **打开结果**，播放时间轴，并用 F12 检查最终效果。
5. 如有相机 VMD，在相机面板填写源帧率与预热偏移，再导入相机。

输出 `.blend` 保存材质、辅助效果、头部方向关键帧与相机动画，旁边的 `.report.json` 记录套用验证。**动画仍通过外部 ABC 播放**，移动工程时需同时保留缓存并重新定位缓存路径。源动作中的物理表现沿用 ABC。

## 仓库文件

| 目录 | Git 保存的内容 |
| --- | --- |
| `addons/random_play_toon/` | PMX 着色、材质／效果代码、角色匹配配置、必要节点与校准资源 |
| `addons/random_play_copy/` | ABC 验证与材质套用、风格面板、相机处理 |
| `python_scripts/.../release/` | 两个插件的打包脚本 |
| `python_scripts/animation/build/sync_copy_style_panel.py` | 维护共用风格面板的脚本 |
| `docs/` | Markdown 操作说明与精选渲染／面板图片 |

原模型包、原始 DDS 与索引素材库、动作缓存、完整演示场景、实验记录、测试输出、日志和 `dist/` 不在 Git 跟踪范围内。资源必须从原发布者获取，仓库不二次分发。
