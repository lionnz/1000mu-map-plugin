import bpy

from ..constants import ADDON_MODULE, BUILTIN_HEIGHT_PRESETS, BUILTIN_PRESETS_HASH

class MAP_OT_add_preset(bpy.types.Operator):
    bl_idname = "map.add_preset"
    bl_label = "添加预设"
    bl_description = "添加一行新的高度预设"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        item = prefs.height_presets.add()
        item.keyword = "新图层"
        item.height = 10.0
        prefs.active_preset_idx = len(prefs.height_presets) - 1
        return {'FINISHED'}

class MAP_OT_del_preset(bpy.types.Operator):
    bl_idname = "map.del_preset"
    bl_label = "删除预设"
    bl_description = "删除当前选中的高度预设"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        idx = prefs.active_preset_idx
        if 0 <= idx < len(prefs.height_presets):
            prefs.height_presets.remove(idx)
            prefs.active_preset_idx = max(0, min(idx, len(prefs.height_presets) - 1))
        return {'FINISHED'}

class MAP_OT_reset_presets(bpy.types.Operator):
    bl_idname = "map.reset_presets"
    bl_label = "恢复内置默认值"
    bl_description = "清空当前预设，恢复为插件内置的 10 条默认预设"
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        prefs.height_presets.clear()
        for kw, h in BUILTIN_HEIGHT_PRESETS:
            item = prefs.height_presets.add()
            item.keyword = kw
            item.height = h
        prefs.presets_hash = BUILTIN_PRESETS_HASH
        prefs.active_preset_idx = 0
        self.report({'INFO'}, f"已恢复 {len(BUILTIN_HEIGHT_PRESETS)} 条内置默认预设")
        return {'FINISHED'}
