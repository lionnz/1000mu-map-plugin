import bpy


class MAP_OT_set_clip(bpy.types.Operator):
    """快速设置视图裁剪范围"""
    bl_idname = "map.set_clip"
    bl_label = "设置视图裁剪"
    bl_description = "快速切换视图裁剪起始/结束距离，解决大比例地图破面问题"
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(
        name="裁剪预设",
        items=[
            ('DEFAULT', "默认", "Clip Start 0.01m / End 1000m"),
            ('FAR_X10', "远点×10", "Clip Start 0.01m / End 10000m"),
            ('X10', "×10", "Clip Start 0.1m / End 10000m"),
            ('FAR_X100', "远点×100", "Clip Start 0.01m / End 100000m"),
            ('X100', "×100", "Clip Start 1m / End 100000m"),
            ('X1000', "×1000", "Clip Start 10m / End 1000000m"),
        ],
        default='DEFAULT',
    )

    CLIP_PRESETS = {
        'DEFAULT':   (0.01, 1000.0),
        'FAR_X10':   (0.01, 10000.0),
        'X10':       (0.1, 10000.0),
        'FAR_X100':  (0.01, 100000.0),
        'X100':      (1.0, 100000.0),
        'X1000':     (10.0, 1000000.0),
    }

    def execute(self, context):
        props = context.scene.map_props
        props.clip_preset = self.preset
        start, end = self.CLIP_PRESETS[self.preset]
        if context.screen:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            space.clip_start = start
                            space.clip_end = end
        self.report({'INFO'}, f"视图裁剪: Start={start}m / End={end}m")
        return {'FINISHED'}


class MAP_OT_set_shading(bpy.types.Operator):
    """快速切换视图着色模式（实体+灯棚预设）"""
    bl_idname = "map.set_shading"
    bl_label = "视图着色预设"
    bl_description = "切换实体显示模式的灯棚与颜色类型，用于色块贴图检查"
    bl_options = {'REGISTER', 'UNDO'}

    preset: bpy.props.EnumProperty(
        name="着色预设",
        items=[
            ('DEFAULT', "默认着色", "实体+灯棚(默认)+材质颜色"),
            ('PAINT_MAT', "paint.sl+材质", "实体+灯棚(paint.sl)+材质颜色"),
            ('PAINT_TEX', "paint.sl+纹理", "实体+灯棚(paint.sl)+纹理"),
        ],
        default='DEFAULT',
    )

    SHADING_PRESETS = {
        'DEFAULT':   (None, 'MATERIAL'),        # None = 切换回 Blender 默认灯棚
        'PAINT_MAT': ('paint.sl', 'MATERIAL'),
        'PAINT_TEX': ('paint.sl', 'TEXTURE'),
    }

    def execute(self, context):
        props = context.scene.map_props
        props.shading_preset = self.preset
        studio_light_name, color_type = self.SHADING_PRESETS[self.preset]
        if context.screen:
            for area in context.screen.areas:
                if area.type == 'VIEW_3D':
                    for space in area.spaces:
                        if space.type == 'VIEW_3D':
                            shading = space.shading
                            shading.type = 'SOLID'
                            shading.light = 'STUDIO'
                            if studio_light_name is None:
                                for name in ['studio.exr', 'Default', 'studio']:
                                    try:
                                        shading.studio_light = name
                                        break
                                    except (TypeError, RuntimeError):
                                        continue
                            else:
                                try:
                                    shading.studio_light = studio_light_name
                                except (TypeError, RuntimeError) as e:
                                    print(f"[1000Map] 设置灯棚失败 '{studio_light_name}': {e}")
                                    try:
                                        available = [sl.name for sl in context.preferences.studio_lights if studio_light_name.lower() in sl.name.lower()]
                                        if available:
                                            shading.studio_light = available[0]
                                    except (TypeError, RuntimeError, AttributeError):
                                        pass
                            shading.color_type = color_type
        label = {'DEFAULT': '默认着色', 'PAINT_MAT': 'paint.sl+材质', 'PAINT_TEX': 'paint.sl+纹理'}[self.preset]
        self.report({'INFO'}, f"视图着色: {label}")
        return {'FINISHED'}


classes = (
    MAP_OT_set_clip,
    MAP_OT_set_shading,
)
