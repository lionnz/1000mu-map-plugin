import bpy

class MAP_UL_layer_list(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        split = layout.split(factor=0.10)
        split.prop(item, 'color', text='')
        right = split.row(align=True)
        s_name = right.split(factor=0.40)
        s_name.prop(item, 'layer_name', text='', emboss=False)
        values_row = s_name.row(align=True)
        values_row.prop(item, 'use_rand_height', text='', icon='SHADERFX', toggle=True)
        if item.use_rand_height:
            values_row.prop(item, 'rand_height_min', text='')
            values_row.prop(item, 'rand_height_max', text='')
        else:
            values_row.prop(item, 'height', text='')

class MAP_UL_prefs_presets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'keyword', text='', emboss=True)
        row.prop(item, 'height', text='')

class MAP_PT_main_panel(bpy.types.Panel):
    bl_label="1000MU 3D MAP 插件"
    bl_idname="MAP_PT_main_panel"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='1000Map'
    def draw(self,context):
        props=context.scene.map_props; layout=self.layout
        row=layout.row(align=True)
        for idx,text in enumerate(['导入','挤出','导出']):
            op=row.operator('map.switch_tab',text=text,depress=(props.active_tab==idx)); op.tab_index=idx
        layout.separator()

        if props.active_tab==0:
            # 视图设置 + 场景清理（合并为一个板块）
            box = layout.box()
            box.label(text="视图设置", icon='VIEW3D')
            row = box.row(align=True)
            current_clip = props.clip_preset
            for preset_id, label in [('DEFAULT','默认'), ('FAR_X10','远点×10'), ('X10','×10')]:
                op = row.operator("map.set_clip", text=label, depress=(current_clip == preset_id))
                op.preset = preset_id
            row = box.row(align=True)
            for preset_id, label in [('FAR_X100','远点×100'), ('X100','×100'), ('X1000','×1000')]:
                op = row.operator("map.set_clip", text=label, depress=(current_clip == preset_id))
                op.preset = preset_id
            # 着色方式
            col = box.column(align=True)
            col.label(text="着色方式：", icon='SHADING_RENDERED')
            row = col.row(align=True)
            current_shading = props.shading_preset
            op1 = row.operator("map.set_shading", text="默认视图着色", depress=(current_shading == 'DEFAULT'))
            op1.preset = 'DEFAULT'
            op2 = row.operator("map.set_shading", text="paint.sl+材质", depress=(current_shading == 'PAINT_MAT'))
            op2.preset = 'PAINT_MAT'
            op3 = row.operator("map.set_shading", text="paint.sl+纹理", depress=(current_shading == 'PAINT_TEX'))
            op3.preset = 'PAINT_TEX'

            layout.separator()

            layout.prop(props,'svg_filepath',text='SVG文件')

            layout.separator()

            layout.label(text='比例换算',icon='CON_SIZELIKE')
            row = layout.row(align=True)
            left = row.row(align=True)
            left.scale_x = 4.2
            left.prop(props,'ratio_px',text='')
            unit_l = row.row(align=True)
            unit_l.scale_x = 0.5
            unit_l.label(text='px')
            center = row.row(align=True)
            center.scale_x = 1.0
            center.alignment = 'CENTER'
            center.label(text='=')
            right = row.row(align=True)
            right.scale_x = 4.2
            right.prop(props,'ratio_m',text='')
            unit_r = row.row(align=True)
            unit_r.scale_x = 0.3
            unit_r.label(text='m')

            layout.prop(props,'curve_res',slider=True)

            layout.separator()

            btn_row=layout.row(); btn_row.scale_y=1.2; btn_row.operator('map.import_svg',icon='LIGHT_SUN')
            if len(props.layer_list)>0:
                layout.label(text=f"已导入 {len(props.layer_list)} 个图层",icon='INFO')
                gen_row=layout.row(); gen_row.scale_y=1.2; gen_row.operator('map.generate_3d',icon='PLAY',text='一键挤出')

        elif props.active_tab==1:
            box = layout.box()
            box.label(text="网格平面优化", icon='MESH_DATA')
            row = box.row(align=True)
            row.operator("map.check_zero_area", text='检查所选网格的"0面积的面"', icon='ZOOM_ALL')
            row = box.row(align=True)
            row.operator("map.retopology", text="对所选网格物体进行重新拓扑", icon='MOD_REMESH')
            row = box.row(align=True)
            row.operator("map.optimize_curve", text="对所选曲线物体进行网格优化", icon='CURVE_DATA')

            layout.separator()

            row = layout.row(align=True)
            row.operator("map.refresh_layer_list", text="刷新图层列表（从选中物体）", icon='FILE_REFRESH')

            if len(props.layer_list)==0: layout.label(text='请先在「导入」标签页导入SVG',icon='INFO')
            else:
                box=layout.box(); box.label(text=f'图层配置 ({len(props.layer_list)}个)',icon='MOD_BUILD')
                row=box.row(); row.template_list('MAP_UL_layer_list','',props,'layer_list',props,'layer_list_idx',rows=max(5, min(len(props.layer_list), 10)))
                layout.separator()
                gen_row=layout.row(); gen_row.scale_y=1.6; gen_row.operator('map.generate_3d',icon='PLAY',text='一键挤出')

        elif props.active_tab==2:
            box = layout.box()
            box.label(text="实用小工具", icon='TOOL_SETTINGS')
            box.operator("map.purge_scene", text="从该文件中清理未使用的数据", icon='BRUSH_DATA')
            box.operator("map.clean_uvmap", text="UVmap 批量清理 (所选网格)", icon='GROUP_UVS')
            box.operator("map.clear_split_normals", text="自定义法向批量清理 (所选网格)", icon='NORMALS_VERTEX')
            box.operator("map.set_origin_to_face", text="编辑模式下、根据批量选择的面对所选网格进行批量设置原点", icon='ORIENTATION_CURSOR')
            box.operator("map.build_atlas", text="材质球打包、生成色块贴图", icon='IMAGE_DATA')

            if hasattr(context.scene, 'batch_clear_progress') and context.scene.batch_clear_progress > 0:
                box.progress(factor=context.scene.batch_clear_progress, text="法向清理中...")

            layout.separator()

            box = layout.box()
            box.label(text='导出交付', icon='EXPORT')
            box.prop(props,'exp_visible_only', text="仅导出可见")
            box.prop(props,'exp_apply_modifiers', text="应用修改器")
            box.prop(props,'exp_pinyin_safe', text="导出时静默中文转拼音，防前端报错")
            exp_row=box.row(); exp_row.scale_y=1.5; exp_row.operator('map.export_glb',icon='PACKAGE')
