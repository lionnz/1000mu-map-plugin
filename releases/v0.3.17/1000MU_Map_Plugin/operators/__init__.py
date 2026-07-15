from .pipeline import (
    MAP_OT_switch_tab,
    MAP_OT_import_svg,
    MAP_OT_generate_3d,
    MAP_OT_export_glb,
    MAP_OT_refresh_layer_list,
)
from .presets import (
    MAP_OT_add_preset,
    MAP_OT_del_preset,
    MAP_OT_reset_presets,
)
from .view_tools import (
    MAP_OT_set_clip,
    MAP_OT_set_shading,
)
from .mesh_tools import (
    MAP_OT_check_zero_area,
    MAP_OT_retopology,
)
from .repair_tools import (
    MAP_OT_purge_scene,
    MAP_OT_clean_uvmap,
    MAP_OT_clear_split_normals,
    MAP_OT_set_origin_to_face,
    MAP_OT_build_atlas,
)

classes = (
    # 核心流程
    MAP_OT_switch_tab,
    MAP_OT_import_svg,
    MAP_OT_generate_3d,
    MAP_OT_export_glb,
    MAP_OT_refresh_layer_list,
    # 预设管理
    MAP_OT_add_preset,
    MAP_OT_del_preset,
    MAP_OT_reset_presets,
    # 视图工具
    MAP_OT_set_clip,
    MAP_OT_set_shading,
    # 网格工具
    MAP_OT_check_zero_area,
    MAP_OT_retopology,
    # 修复与清理工具（导出-实用小工具）
    MAP_OT_purge_scene,
    MAP_OT_clean_uvmap,
    MAP_OT_clear_split_normals,
    MAP_OT_set_origin_to_face,
    MAP_OT_build_atlas,
)