"""Store a self-contained, explicitly run parameter UI inside the blend."""
from pathlib import Path

PANEL_TEXT='01_启用风格面板'

def embed_panel():
    import bpy
    source=(Path(__file__).parent/'style_panel.py').read_text(encoding='utf8')
    text=bpy.data.texts.get(PANEL_TEXT) or bpy.data.texts.new(PANEL_TEXT)
    text.clear();text.write(source);text.use_module=False
    readme=bpy.data.texts.get('00_RandomPlayToon_使用说明') or bpy.data.texts.new('00_RandomPlayToon_使用说明')
    readme.clear();readme.write('RandomPlayToon 0.9.3 · 已重建场景\n\n模型、材质和参数均已保存，不需要重新导入或重建。\n\n推荐：安装并启用 RandomPlayToon 插件，然后直接打开本文件。\n3D 视图按 N：RandomPlayToon 为重建页，英文角色名为参数页。\n\n未安装插件：切换到文本编辑器，选择 01_启用风格面板，点击运行脚本（Alt+P）。\n返回 3D 视图，按 N，在英文角色页调节参数；按 F12 查看最终透眼和辉光。\n内置脚本只提供参数面板；一键重建需要完整插件。\n内置脚本需要在每次启动 Blender 后手动运行一次，不要求开启全局自动运行脚本。\n')
    bpy.context.scene['rpt_panel_version']='0.9.3'
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type in {'VIEW_3D','NODE_EDITOR'}:area.spaces.active.show_region_ui=True
