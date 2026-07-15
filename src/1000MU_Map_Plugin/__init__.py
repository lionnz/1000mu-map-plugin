bl_info = {
    "name": "1000MU 3D MAP 插件",
    "author": "Design Team",
    "version": (0, 3, 17),
    "blender": (4, 2, 0),
    "location": "View3D > N Panel > 1000Map",
    "description": "v0.3.17: 面板布局调整、新增曲线物体网格优化、修复清理提示红叉BUG。兼容 Blender 4.2-4.5。",
    "category": "3D View",
}

# v0.3.14 变更摘要（融合 v0.3.9–v0.3.13 所有优化）
#   1. 内置 pypinyin 拼音引擎，无需联网安装，开箱即用
#   2. 兼容 Blender 4.5：material.shadow_method 改为 hasattr 检测
#   3. 偏好设置可配置高度预设表（v0.3.12）
#   4. 色块贴图：支持单物体多材质球（v0.3.9）、冗余槽自动合并（v0.3.10）、回归修复（v0.3.11）
#   5. 法线统一隔离、非递归孤立清理、epsilon 防抖、md5 防重名、tempfile 隔离（v0.3.9）
#   6. 随机高度开启时自动填充区间、UI 布局优化、description 悬浮提示（v0.3.13）

import sys
import os

# 将 vendored pypinyin 加入 sys.path
# 安全：使用 append 而非 insert(0)，避免遮蔽标准库模块
_vendor_dir = os.path.join(os.path.dirname(__file__), 'vendor')
if os.path.isdir(_vendor_dir) and _vendor_dir not in sys.path:
    sys.path.append(_vendor_dir)

import bpy
from .props import MAP_PG_layer_item, MAP_PG_main_props, MAP_PG_height_preset
from .operators import classes as operator_classes
from .operators.repair_tools import _reset_batch_clear_state
from .ui import MAP_UL_layer_list, MAP_UL_prefs_presets, MAP_PT_main_panel
from .preferences import MAP_AddonPreferences
from .constants import BUILTIN_HEIGHT_PRESETS, BUILTIN_PRESETS_HASH, ADDON_MODULE

classes = (
    MAP_PG_layer_item,
    MAP_PG_main_props,
    MAP_PG_height_preset,
) + operator_classes + (
    MAP_UL_layer_list,
    MAP_UL_prefs_presets,
    MAP_PT_main_panel,
    MAP_AddonPreferences,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.map_props = bpy.props.PointerProperty(type=MAP_PG_main_props)
    # 法向清理的进度条和报告属性
    bpy.types.Scene.batch_clear_progress = bpy.props.FloatProperty(default=-1.0, min=-1.0, max=1.0)
    bpy.types.Scene.batch_clear_report = bpy.props.StringProperty(default="")
    # load_post handler：新文件加载后重置批量清理状态
    if _reset_batch_clear_state not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_reset_batch_clear_state)

    try:
        prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
        if prefs is not None and prefs.presets_hash != BUILTIN_PRESETS_HASH:
            prefs.height_presets.clear()
            for kw, h in BUILTIN_HEIGHT_PRESETS:
                item = prefs.height_presets.add()
                item.keyword = kw
                item.height = h
            prefs.presets_hash = BUILTIN_PRESETS_HASH
            print("[1000Map] 检测到内置预设已更新，已自动同步至偏好设置")
    except Exception as e:
        print(f"[1000Map] 填充默认预设失败（可手动点击「恢复内置默认值」）: {e}")

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, 'map_props'):
        del bpy.types.Scene.map_props
    if hasattr(bpy.types.Scene, 'batch_clear_progress'):
        del bpy.types.Scene.batch_clear_progress
    if hasattr(bpy.types.Scene, 'batch_clear_report'):
        del bpy.types.Scene.batch_clear_report
    if _reset_batch_clear_state in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_reset_batch_clear_state)

if __name__ == '__main__':
    register()
