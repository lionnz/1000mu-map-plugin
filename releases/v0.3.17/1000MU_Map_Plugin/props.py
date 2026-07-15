import os
import bpy

from .utils import _on_use_rand_height

class MAP_PG_layer_item(bpy.types.PropertyGroup):
    layer_name: bpy.props.StringProperty(name="图层名", default="",
        description="从SVG中解析出的图层名称，不可手动修改")
    height: bpy.props.FloatProperty(name="高度(m)", default=0.0, min=0.0, step=10,
        description="该图层的3D挤出高度（米），命中预设时自动填充")
    color: bpy.props.FloatVectorProperty(name="颜色", subtype='COLOR', size=4, default=(0.8,0.8,0.8,1.0), min=0.0, max=1.0,
        description="该图层的基础材质颜色，自动取自SVG原始填充色")
    use_rand_height: bpy.props.BoolProperty(
        name="随机高度", default=False,
        description="启用后，该图层下所有物体的挤出高度将在设定区间内随机，产生错落感",
        update=_on_use_rand_height
    )
    rand_height_min: bpy.props.FloatProperty(
        name="最小", default=1.0, min=0.0, step=10,
        description="随机高度下限(m)"
    )
    rand_height_max: bpy.props.FloatProperty(
        name="最大", default=10.0, min=0.0, step=10,
        description="随机高度上限(m)"
    )

class MAP_PG_main_props(bpy.types.PropertyGroup):
    svg_filepath: bpy.props.StringProperty(name="SVG文件", subtype='FILE_PATH',
        description="选择Figma导出的SVG矢量地图文件，支持中文图层名")
    ratio_px: bpy.props.FloatProperty(name="px", default=10.0, min=0.1,
        description="SVG中像素对应的参考尺寸（例如：10px）")
    ratio_m: bpy.props.FloatProperty(name="m", default=1.0, min=0.01,
        description="上述像素对应的实际距离（米），用于换算物理比例")
    curve_res: bpy.props.IntProperty(name="曲线精度", default=4, min=1, max=12,
        description="曲线转网格时的采样精度，数值越高边缘越平滑")
    layer_list: bpy.props.CollectionProperty(type=MAP_PG_layer_item)
    layer_list_idx: bpy.props.IntProperty()
    exp_visible_only: bpy.props.BoolProperty(name="仅导出可见", default=True,
        description="开启后仅导出视口中可见的物体，隐藏物体将被忽略")
    exp_apply_modifiers: bpy.props.BoolProperty(name="应用修改器", default=True,
        description="导出前自动应用挤出、焊接等修改器，确保GLB包含最终形态")
    exp_pinyin_safe: bpy.props.BoolProperty(name="拼音防呆", default=True, description="导出时静默去中文，防前端报错")
    active_tab: bpy.props.IntProperty(default=0)
    clip_preset: bpy.props.EnumProperty(
        name="视图裁剪预设",
        items=[
            ('DEFAULT', "默认", ""),
            ('FAR_X10', "远点×10", ""),
            ('X10', "×10", ""),
            ('FAR_X100', "远点×100", ""),
            ('X100', "×100", ""),
            ('X1000', "×1000", ""),
        ],
        default='DEFAULT',
    )
    shading_preset: bpy.props.EnumProperty(
        name="视图着色预设",
        items=[
            ('DEFAULT', "默认视图着色", ""),
            ('PAINT_MAT', "paint.sl+材质", ""),
            ('PAINT_TEX', "paint.sl+纹理", ""),
        ],
        default='DEFAULT',
    )

class MAP_PG_height_preset(bpy.types.PropertyGroup):
    keyword: bpy.props.StringProperty(
        name="关键词", default="新图层",
        description="图层名包含此关键词即命中预设高度"
    )
    height: bpy.props.FloatProperty(
        name="高度(m)", default=10.0, min=0.0, step=10,
        description="匹配该关键词的图层默认挤出高度（米）"
    )
