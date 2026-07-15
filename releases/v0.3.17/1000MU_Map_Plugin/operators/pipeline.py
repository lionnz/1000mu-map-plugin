import bpy, bmesh, random, os, re, tempfile, xml.etree.ElementTree as ET
import math

from ..constants import INVALID_LAYER_NAMES, ADDON_MODULE
from ..utils import decode_figma_id, get_base_name, parse_svg_colors, force_normals_up, get_height_presets, chinese_to_safe_name, MAX_SVG_SIZE

class MAP_OT_switch_tab(bpy.types.Operator):
    bl_idname = "map.switch_tab"; bl_label = "切换标签"
    bl_description = "切换插件的功能标签页"
    bl_options = {'REGISTER', 'UNDO'}
    tab_index: bpy.props.IntProperty(default=0)
    def execute(self,context): context.scene.map_props.active_tab = self.tab_index; return {'FINISHED'}

class MAP_OT_import_svg(bpy.types.Operator):
    bl_idname = "map.import_svg"
    bl_label = "导入并重构空间"
    bl_description = "导入SVG地图，自动换算物理尺寸并转换为3D网格平面"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.map_props
        input_file = bpy.path.abspath(props.svg_filepath)
        if not os.path.exists(input_file) or not input_file.lower().endswith('.svg'):
            self.report({'ERROR'}, "请选择有效的SVG文件！"); return {'CANCELLED'}

        # 安全：检查 SVG 文件大小，防止 XML 实体扩展攻击（Billion Laughs）导致内存耗尽
        try:
            if os.path.getsize(input_file) > MAX_SVG_SIZE:
                self.report({'ERROR'}, f"SVG 文件过大（>{MAX_SVG_SIZE//1024//1024}MB），可能存在安全风险！")
                return {'CANCELLED'}
        except OSError as e:
            self.report({'ERROR'}, f"SVG 文件大小检查失败: {e}")
            return {'CANCELLED'}

        # 安全：使用 NamedTemporaryFile 避免 TOCTOU 窗口，文件句柄保持打开直到写入完成
        temp_svg_file = tempfile.NamedTemporaryFile(suffix='.svg', prefix='blender_map_', mode='wb', delete=False)
        temp_svg = temp_svg_file.name
        temp_svg_file.close()  # 关闭句柄，稍后通过路径写入（Blender 的 ET.write 需要路径）
        ET.register_namespace('',"http://www.w3.org/2000/svg")
        try:
            tree = ET.parse(input_file); root = tree.getroot()
        except (ET.ParseError, OSError) as e:
            self.report({'ERROR'}, f"SVG 解析失败: {e}")
            if os.path.exists(temp_svg): os.remove(temp_svg)
            return {'CANCELLED'}

        def parse_dim(val):
            if not val: return None
            try: return float(str(val).replace('px', '').strip())
            except ValueError: return None

        svg_w = parse_dim(root.get('width'))
        svg_h = parse_dim(root.get('height'))

        if svg_w is None or svg_h is None:
            viewbox = root.get('viewBox')
            if viewbox:
                try:
                    parts = viewbox.split()
                    if len(parts) >= 4:
                        if svg_w is None: svg_w = float(parts[2])
                        if svg_h is None: svg_h = float(parts[3])
                except Exception:
                    pass

        svg_w = svg_w if svg_w is not None else 1000.0
        svg_h = svg_h if svg_h is not None else 1000.0

        def apply_target_id(element, current_target_id):
            tag = element.tag.split('}')[-1]
            is_shape = tag in {'path','rect','circle','ellipse','polygon','polyline','line'}
            raw_id = element.get('id')
            if is_shape:
                if current_target_id: element.set('id', current_target_id)
                elif raw_id:
                    decoded = decode_figma_id(raw_id)
                    if decoded and decoded.lower() not in INVALID_LAYER_NAMES: element.set('id', decoded)
            else:
                if raw_id and current_target_id is None:
                    decoded = decode_figma_id(raw_id)
                    if decoded and decoded.lower() not in INVALID_LAYER_NAMES: current_target_id = decoded
            for child in element: apply_target_id(child, current_target_id)

        root_g = [c for c in root if c.tag.split('}')[-1] == 'g']
        if len(root_g) == 1:
            for child in root_g[0]:
                apply_target_id(child, None)
        else:
            for child in root:
                apply_target_id(child, None)
        tree.write(temp_svg,encoding='utf-8',xml_declaration=True)

        # 解析 SVG 颜色并存储到场景（供 refresh_layer_list 使用）
        svg_colors = parse_svg_colors(input_file)
        context.scene['map_svg_colors'] = {k: list(v) for k, v in svg_colors.items()}

        existing_objs = set(context.scene.objects)
        bpy.ops.import_curve.svg(filepath=temp_svg)
        if os.path.exists(temp_svg): os.remove(temp_svg)
        new_objs = set(context.scene.objects)-existing_objs
        curves = [o for o in new_objs if o.type=='CURVE']
        if not curves: self.report({'WARNING'},"未检测到有效曲线！"); return {'CANCELLED'}

        scale_factor = 3543.0*(props.ratio_m/props.ratio_px)
        offset_x, offset_y = -(svg_w*props.ratio_m/props.ratio_px)/2, -(svg_h*props.ratio_m/props.ratio_px)/2

        bpy.ops.object.select_all(action='DESELECT')
        for obj in curves:
            obj.select_set(True)
            obj.data.resolution_u = props.curve_res
            obj.data.dimensions='2D'; obj.data.fill_mode='BOTH'
            obj.scale=(scale_factor,scale_factor,scale_factor)

        context.view_layer.objects.active = curves[0]
        bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)

        # 方案B：用几何节点的填充曲线替代传统曲线转网格的2D填充
        try:
            for obj in curves:
                obj.data.fill_mode = 'NONE'
                mod = obj.modifiers.new(name='FillCurve', type='NODES')
                ng = bpy.data.node_groups.new('FillCurve_NGons', type='GeometryNodeTree')
                ng.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
                ng.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
                nodes = ng.nodes; links = ng.links
                input_node = nodes.new('NodeGroupInput')
                output_node = nodes.new('NodeGroupOutput')
                fill_node = nodes.new('GeometryNodeFillCurve')
                if hasattr(fill_node, 'fill_mode'):
                    fill_node.fill_mode = 'NGONS'
                elif hasattr(fill_node, 'mode'):
                    fill_node.mode = 'NGONS'
                links.new(input_node.outputs[0], fill_node.inputs[0])
                links.new(fill_node.outputs[0], output_node.inputs[0])
                mod.node_group = ng
        except (RuntimeError, AttributeError, TypeError, KeyError) as e:
            print(f"[1000Map] 方案B几何节点填充失败，降级为传统转换: {e}")
            for obj in curves:
                for m in list(obj.modifiers):
                    if m.name == 'FillCurve':
                        obj.modifiers.remove(m)
                try:
                    obj.data.fill_mode = 'BOTH'
                except (RuntimeError, AttributeError):
                    pass

        bpy.ops.object.convert(target='MESH')

        # 清理方案B的节点组（convert 后已无引用）
        for ng in list(bpy.data.node_groups):
            if ng.name.startswith('FillCurve_NGons') and ng.users == 0:
                bpy.data.node_groups.remove(ng)

        meshes = [o for o in new_objs if o.type=='MESH']

        # 面三角化 → 三角面转四边面 + 兜底清理
        # FillCurve 烘焙后的 N-gon 面在 GLB 导出三角化时可能产生0面积面，
        # 先用 Blender 原生 BEAUTY 三角化再合并回四边面，让拓扑更稳定；
        # 最后兜底清理残留的0面积退化面（BEAUTY对复杂形状可能产生细长三角形）
        for obj in meshes:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            try:
                bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
                bpy.ops.mesh.tris_convert_to_quads(face_threshold=math.radians(1.0), shape_threshold=math.radians(1.0))
            except RuntimeError as e:
                print(f"[1000Map] 三角化/转四边面失败 {obj.name}: {e}")
            bpy.ops.object.mode_set(mode='OBJECT')

            # 兜底清理：删除残留的0面积退化面
            bm2 = bmesh.new()
            bm2.from_mesh(obj.data)
            degenerate_faces = [f for f in bm2.faces if f.calc_area() < 0.0001]
            if degenerate_faces:
                bmesh.ops.delete(bm2, geom=degenerate_faces, context='FACES')
                bm2.to_mesh(obj.data)
                obj.data.update()
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.remove_doubles(threshold=0.0001)
                bpy.ops.mesh.delete_loose()
                bpy.ops.object.mode_set(mode='OBJECT')
                print(f"[1000Map] 导入兜底清理 {obj.name}: 删除 {len(degenerate_faces)} 个退化面")
            bm2.free()

        # 为导入的网格创建并分配材质
        # SVG 导入的曲线虽有 SVGMat 材质，但 convert 烘焙几何节点会清空材质，
        # 且 SVGMat 不含 Principled BSDF，视口显示不正确。
        # 这里直接从解析的 SVG 颜色创建标准材质（Mat_{图层名}），与一键挤出共用命名。
        for obj in meshes:
            base = get_base_name(obj.name)
            color = svg_colors.get(base, (0.8, 0.8, 0.8, 1.0))
            matname = f"Mat_{base}"
            if matname not in bpy.data.materials:
                mat = bpy.data.materials.new(name=matname); mat.use_nodes = True
                nodes = mat.node_tree.nodes; links = mat.node_tree.links
                for n in nodes: nodes.remove(n)
                bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                output = nodes.new('ShaderNodeOutputMaterial')
                bsdf.location = (0, 300); output.location = (300, 300)
                links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            else:
                mat = bpy.data.materials[matname]
                bsdf = mat.node_tree.nodes.get('Principled BSDF')
            if bsdf:
                bsdf.inputs['Base Color'].default_value = color
                bsdf.inputs['Alpha'].default_value = color[3]
                bsdf.inputs['Roughness'].default_value = 0.2 if color[3] < 1.0 else 0.8
            if color[3] < 1.0:
                mat.blend_method = 'BLEND'
                if hasattr(mat, 'shadow_method'):
                    mat.shadow_method = 'NONE'
            mat.diffuse_color = color
            obj.data.materials.clear(); obj.data.materials.append(mat)

        for obj in meshes: obj.location.x+=offset_x; obj.location.y+=offset_y
        bpy.ops.object.select_all(action='DESELECT'); [o.select_set(True) for o in meshes]; context.view_layer.objects.active=meshes[0]
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=False)

        self.report({'INFO'}, "导入成功！请选中导入的网格物体，到「挤出」标签页点击「刷新图层列表」")
        return {'FINISHED'}

class MAP_OT_refresh_layer_list(bpy.types.Operator):
    bl_idname = "map.refresh_layer_list"
    bl_label = "刷新图层列表"
    bl_description = "根据当前选中的网格物体生成图层配置列表"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.map_props
        mesh_objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not mesh_objs:
            self.report({'WARNING'}, "请先选中网格物体")
            return {'CANCELLED'}

        # 读取导入时存储的 SVG 颜色
        svg_colors = context.scene.get('map_svg_colors', {})

        # 按基础名去重
        seen = set()
        base_names = []
        for obj in mesh_objs:
            base = get_base_name(obj.name)
            if base in seen: continue
            seen.add(base)
            base_names.append(base)

        props.layer_list.clear()
        for base in base_names:
            item = props.layer_list.add()
            item.layer_name = base
            matched = False
            for kw, h in get_height_presets(context):
                if kw and kw in base:
                    item.height = h
                    matched = True; break
            if not matched: item.height = float(random.randint(1, 10))

            # 从 SVG 颜色字典中查找，找不到则用默认灰色
            if base in svg_colors:
                c = svg_colors[base]
                item.color = (c[0], c[1], c[2], c[3])
            else:
                item.color = (0.8, 0.8, 0.8, 1.0)

        self.report({'INFO'}, f"已从选中物体生成 {len(props.layer_list)} 个图层")
        return {'FINISHED'}

class MAP_OT_generate_3d(bpy.types.Operator):
    bl_idname = "map.generate_3d"
    bl_label = "一键挤出"
    bl_description = "按图层配置的高度和颜色执行3D挤出，自动修正法线方向并赋予基础材质"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.map_props
        if len(props.layer_list) == 0: self.report({'ERROR'}, "请先导入SVG！"); return {'CANCELLED'}

        layer_config = {
            i.layer_name: {
                'height':         i.height,
                'color':          i.color,
                'use_rand_height': i.use_rand_height,
                'rand_min':       min(i.rand_height_min, i.rand_height_max),
                'rand_max':       max(i.rand_height_min, i.rand_height_max),
            }
            for i in props.layer_list
        }
        count = 0

        all_layer_names = set(layer_config.keys())
        def is_map_obj(obj):
            if obj.type != 'MESH': return False
            base = get_base_name(obj.name)
            return (base in all_layer_names or obj.name in all_layer_names
                    or any(obj.name.startswith(n + '.') for n in all_layer_names))

        for obj in context.selected_objects:
            if obj.type != 'MESH': continue
            if not is_map_obj(obj): continue
            obj.modifiers.clear(); height = 0; color = (0.8, 0.8, 0.8, 1.0)
            obj_base = get_base_name(obj.name)

            for lname, conf in layer_config.items():
                if obj_base == lname or obj.name == lname or obj.name.startswith(lname + '.'):
                    color = conf['color']
                    if conf['use_rand_height']:
                        lo, hi = conf['rand_min'], conf['rand_max']
                        height = round(random.uniform(lo, hi), 2) if hi > lo else lo
                    else:
                        height = conf['height']
                    break

            if height <= 0: height = float(random.randint(1, 10))
            force_normals_up(obj)

            m = obj.modifiers.new(name='Extrude', type='SOLIDIFY'); m.thickness = height; m.offset = 1.0

            obj.modifiers.new(name='Weld', type='WELD'); obj.modifiers.new(name='Triangulate', type='TRIANGULATE')

            matname = f"Mat_{get_base_name(obj.name)}"
            if matname not in bpy.data.materials:
                mat = bpy.data.materials.new(name=matname); mat.use_nodes = True
                nodes = mat.node_tree.nodes; links = mat.node_tree.links
                for n in nodes: nodes.remove(n)
                bsdf = nodes.new('ShaderNodeBsdfPrincipled')
                output = nodes.new('ShaderNodeOutputMaterial')
                bsdf.location = (0, 300); output.location = (300, 300)
                links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])
            else:
                mat = bpy.data.materials[matname]
                bsdf = mat.node_tree.nodes.get('Principled BSDF')
            # 始终更新颜色（用户可能在图层列表中修改了颜色）
            if bsdf:
                bsdf.inputs['Base Color'].default_value = color
                bsdf.inputs['Alpha'].default_value = color[3]
                bsdf.inputs['Roughness'].default_value = 0.2 if color[3] < 1.0 else 0.8
            if color[3] < 1.0:
                mat.blend_method = 'BLEND'
                if hasattr(mat, 'shadow_method'):
                    mat.shadow_method = 'NONE'
            mat.diffuse_color = color

            obj.data.materials.clear(); obj.data.materials.append(mat)
            count += 1

        map_objs = [o for o in context.selected_objects if o.type == 'MESH' and is_map_obj(o)]
        for o in map_objs:
            o.select_set(True)
        if map_objs:
            context.view_layer.objects.active = map_objs[0]
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        # 手动清理挤出过程中产生的孤立网格和材质数据
        # 不使用 bpy.ops.outliner.orphans_purge()，避免内层 operator 的 ERROR 报告穿透状态栏
        for collection in (bpy.data.meshes, bpy.data.materials):
            orphans = [item for item in collection if item.users == 0]
            for item in orphans:
                try:
                    collection.remove(item)
                except (RuntimeError, ReferenceError):
                    pass

        if count == 0:
            self.report({'WARNING'}, "未挤出任何物体：选中的网格物体不在图层列表中，请先「刷新图层列表」")
        else:
            self.report({'INFO'}, f"挤出完成：共处理 {count} 个物体。请在「导出」标签页生成色块贴图并导出GLB")
        return {'FINISHED'}

class MAP_OT_export_glb(bpy.types.Operator):
    bl_idname = "map.export_glb"
    bl_label = "导出GLB"
    bl_description = "打开Blender原生glTF导出设置（可选拼音防呆）"
    bl_options = {'REGISTER'}

    # 安全：用列表存储多次导出的还原数据，避免类变量被覆盖导致原名永久丢失
    _restore_queue = None  # list[(obj_restore, mat_restore)] 或 None
    _dialog_was_open = False  # 追踪弹窗状态

    def execute(self, context):
        props = context.scene.map_props

        all_mesh_objs = [o for o in context.scene.objects if o.type == 'MESH']
        if not all_mesh_objs:
            self.report({'WARNING'}, "场景中没有网格物体！")
            return {'CANCELLED'}

        # 拼音防呆：记录原名并改名
        if props.exp_pinyin_safe:
            obj_restore = {}
            mat_restore = {}
            for o in all_mesh_objs:
                obj_restore[o] = (o.name, o.data.name if o.data else None)
                new_name = chinese_to_safe_name(o.name)
                o.name = new_name
                if o.data:
                    o.data.name = new_name
            for o in all_mesh_objs:
                for slot in o.material_slots:
                    if slot.material and slot.material not in mat_restore:
                        mat_restore[slot.material] = slot.material.name
                        slot.material.name = 'Mat_' + chinese_to_safe_name(slot.material.name.removeprefix('Mat_'))

            # 安全：追加到队列而非覆盖，防止连续导出丢失前一次的还原数据
            if MAP_OT_export_glb._restore_queue is None:
                MAP_OT_export_glb._restore_queue = []
            MAP_OT_export_glb._restore_queue.append((obj_restore, mat_restore))
            MAP_OT_export_glb._dialog_was_open = True
            # 仅在无计时器运行时注册，避免重复注册
            if not bpy.app.timers.is_registered(self._timer_restore_names):
                bpy.app.timers.register(self._timer_restore_names, first_interval=1.0)

        # 打开原生导出弹窗
        bpy.ops.export_scene.gltf(
            'INVOKE_DEFAULT',
            export_format='GLB',
            use_visible=props.exp_visible_only,
            export_apply=props.exp_apply_modifiers,
        )
        return {'FINISHED'}

    @staticmethod
    def _is_export_dialog_open():
        """检测导出弹窗（文件浏览器）是否仍然打开"""
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'FILE_BROWSER' and area.ui_type != 'ASSETS':
                    return True
        return False

    @staticmethod
    def _timer_restore_names():
        """计时器回调：等待导出弹窗关闭后，再延迟2秒还原原名"""
        queue = MAP_OT_export_glb._restore_queue
        if not queue:
            MAP_OT_export_glb._restore_queue = None
            MAP_OT_export_glb._dialog_was_open = False
            return None

        # 阶段1：等待导出弹窗关闭
        if MAP_OT_export_glb._dialog_was_open:
            if MAP_OT_export_glb._is_export_dialog_open():
                return 1.0  # 弹窗仍开着，继续等待
            # 弹窗已关闭，进入阶段2：等待2秒确保导出文件写入完成
            MAP_OT_export_glb._dialog_was_open = False
            return 2.0

        # 阶段2：弹窗已关闭且已等待2秒，现在还原原名
        obj_restore, mat_restore = queue.pop(0)
        for o, (obj_name, data_name) in obj_restore.items():
            try:
                o.name = obj_name
                if o.data and data_name:
                    o.data.name = data_name
            except (ReferenceError, RuntimeError) as e:
                print(f"[1000Map] 恢复物体名失败: {e}")
        for mat, orig_name in mat_restore.items():
            try:
                mat.name = orig_name
            except (ReferenceError, RuntimeError) as e:
                print(f"[1000Map] 恢复材质名失败: {e}")

        # 队列还有数据则继续处理，否则停止
        if MAP_OT_export_glb._restore_queue:
            MAP_OT_export_glb._dialog_was_open = True
            return 1.0
        MAP_OT_export_glb._restore_queue = None
        return None
