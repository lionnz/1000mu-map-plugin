import bpy

from .constants import ADDON_MODULE, BUILTIN_HEIGHT_PRESETS
from .props import MAP_PG_height_preset

class MAP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_MODULE

    height_presets: bpy.props.CollectionProperty(type=MAP_PG_height_preset)
    active_preset_idx: bpy.props.IntProperty(default=0)
    presets_hash: bpy.props.StringProperty(default="", description="内置预设内容指纹，用于检测升级后自动更新预设表")

    def draw(self, context):
        layout = self.layout
        layout.label(text="默认高度预设表（图层名包含关键词即命中）", icon='PRESET')

        row = layout.row()
        row.template_list(
            'MAP_UL_prefs_presets', '',
            self, 'height_presets',
            self, 'active_preset_idx',
            rows=10
        )

        col = row.column(align=True)
        col.operator('map.add_preset', icon='ADD', text='')
        col.operator('map.del_preset', icon='REMOVE', text='')

        layout.separator()
        layout.operator('map.reset_presets', icon='FILE_REFRESH', text='恢复内置默认值')

        layout.separator()
        box = layout.box()
        box.label(text="使用说明", icon='INFO')
        box.label(text="• 关键词「包含」匹配：图层名只要包含关键词即命中")
        box.label(text="  例如：「主路-辅道」匹配关键词「主路」")
        box.label(text="• 多个关键词同时命中时，按上表顺序优先匹配第一个")
        box.label(text="• 未命中任何关键词的图层，自动取 1–10m 随机高度")
        box.label(text="• 预设保存在用户设置中，所有工程文件共享")
