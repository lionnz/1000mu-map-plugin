import bpy
import bmesh
import math
from mathutils import Matrix, Vector
from bpy.app.handlers import persistent

from ..utils import linear_to_srgb


# ============================================================
# Task 7.1: UVmap 批量清理
# ============================================================
class MAP_OT_clean_uvmap(bpy.types.Operator):
    bl_idname = "map.clean_uvmap"
    bl_label = "UVmap批量清理"
    bl_description = "确保每个网格有且仅有一个UV层，名称为UVMap"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh_objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not mesh_objs:
            self.report({'WARNING'}, "请先选中网格物体")
            return {'CANCELLED'}

        renamed = 0
        removed = 0
        for obj in mesh_objs:
            uv_layers = obj.data.uv_layers
            if len(uv_layers) == 0:
                continue  # 无UV跳过
            elif len(uv_layers) == 1:
                if uv_layers[0].name != 'UVMap':
                    uv_layers[0].name = 'UVMap'
                    renamed += 1
            else:
                # 多个UV：保留活动层，删除其余
                # 注意：遍历时删除UV层会导致引用失效，必须先收集名称再逐个删除
                active = uv_layers.active
                active_name = active.name if active else uv_layers[0].name
                remove_names = [uv.name for uv in uv_layers if uv.name != active_name]
                for name in remove_names:
                    uv_layer = uv_layers.get(name)
                    if uv_layer:
                        uv_layers.remove(uv_layer)
                        removed += 1
                # 删除后重新通过名称获取活动层
                active = uv_layers.get(active_name) or uv_layers[0]
                if active.name != 'UVMap':
                    active.name = 'UVMap'
                    renamed += 1

        if renamed == 0 and removed == 0:
            self.report({'INFO'}, f"共检查 {len(mesh_objs)} 个网格，UV全部正常，无需清理")
        else:
            self.report({'INFO'}, f"UV清理完成：改名 {renamed}，删除多余 {removed}")
        return {'FINISHED'}


# ============================================================
# Task 7.2: 自定义法向批量清理
# 合并自 dp_batch_clear_split_normals.py
# ============================================================
@persistent
def _reset_batch_clear_state(dummy=None):
    for scene in bpy.data.scenes:
        try:
            scene.batch_clear_progress = -1.0
            scene.batch_clear_report = ""
        except (AttributeError, RuntimeError):
            pass


class MAP_OT_clear_split_normals(bpy.types.Operator):
    bl_idname = "map.clear_split_normals"
    bl_label = "对所选网格物体进行自定义法向批量清理"
    bl_description = "批量移除选中网格的自定义拆边法向数据"
    bl_options = {'REGISTER', 'UNDO'}

    _timer = None
    _objects = []
    _total = 0
    _index = 0
    _success = 0
    _failed = 0
    _no_data = 0
    _skipped = 0
    _batch_size = 50
    _original_active = None
    _selected_objs = []

    @classmethod
    def poll(cls, context):
        return context.selected_objects and len(context.selected_objects) > 0

    def modal(self, context, event):
        if event.type == 'TIMER':
            batch_end = min(self._index + self._batch_size, self._total)
            for i in range(self._index, batch_end):
                obj = self._objects[i]
                if not obj.data.has_custom_normals:
                    self._no_data += 1
                    continue
                context.view_layer.objects.active = obj
                try:
                    bpy.ops.mesh.customdata_custom_splitnormals_clear()
                    self._success += 1
                except Exception:
                    self._failed += 1

            self._index = batch_end
            progress = self._index / self._total
            context.scene.batch_clear_progress = progress

            if context.area:
                for region in context.area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()

            if self._index >= self._total:
                self.finish(context)
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def finish(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)

        for obj in self._selected_objs:
            obj.select_set(True)
        if self._original_active and self._original_active in self._selected_objs:
            context.view_layer.objects.active = self._original_active
        elif self._objects:
            context.view_layer.objects.active = self._objects[0]

        report = (
            f"✅ 成功清理: {self._success} 个物体\n"
            f"❌ 失败: {self._failed} 个物体 (无法清除)\n"
            f"⏭️ 无需清理: {self._no_data} 个物体 (已无自定义法向)\n"
            f"⏭️ 跳过: {self._skipped} 个非网格物体\n"
            f"📦 总选中物体数: {len(self._selected_objs)}"
        )
        context.scene.batch_clear_report = report
        context.scene.batch_clear_progress = 1.0

        if self._success == 0 and self._no_data > 0:
            self.report({'INFO'}, f"共检查 {self._no_data} 个网格，全部无自定义法向，无需清理")
        else:
            self.report({'INFO'}, f"清理完毕：成功 {self._success}，无需清理 {self._no_data}")
        print(f"[批量清除] {report}")

        self._objects = []
        self._selected_objs = []

    def execute(self, context):
        return self.invoke(context, None)

    def invoke(self, context, event):
        if hasattr(self, '_timer') and self._timer is not None:
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        selected = context.selected_objects
        if not selected:
            self.report({'WARNING'}, "未选中任何物体")
            return {'CANCELLED'}

        mesh_objs = [obj for obj in selected if obj.type == 'MESH']
        non_mesh = [obj for obj in selected if obj.type != 'MESH']

        if not mesh_objs:
            self.report({'WARNING'}, "选中的物体中没有网格物体")
            return {'CANCELLED'}

        self._objects = mesh_objs
        self._total = len(mesh_objs)
        self._index = 0
        self._success = 0
        self._failed = 0
        self._no_data = 0
        self._skipped = len(non_mesh)
        self._original_active = context.view_layer.objects.active
        self._selected_objs = list(selected)

        context.scene.batch_clear_progress = 0.0
        context.scene.batch_clear_report = ""

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)

        return {'RUNNING_MODAL'}


# ============================================================
# Task 7.3: 按所选面批量设置原点
# ============================================================
class MAP_OT_set_origin_to_face(bpy.types.Operator):
    bl_idname = "map.set_origin_to_face"
    bl_label = "按所选面批量设置原点"
    bl_description = "将每个网格物体原点设置到其选中面的中心，旋转对齐完整面坐标系"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' and len(context.selected_objects) > 0

    def execute(self, context):
        # 记录当前编辑模式下的选中面信息
        obj_face_data = {}
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            selected_faces = [f for f in bm.faces if f.select]
            if not selected_faces:
                continue
            face = selected_faces[0]  # 取第一个选中面
            center = face.calc_center_median()
            normal = face.normal.copy()
            # BMFace 无 calc_tangent()，用面的第一条边方向作为切线
            edge = face.edges[0]
            tangent = (edge.verts[1].co - edge.verts[0].co).normalized()
            obj_face_data[obj] = (center.copy(), normal, tangent)

        if not obj_face_data:
            self.report({'WARNING'}, "未找到任何选中面的网格物体")
            return {'CANCELLED'}

        # 退出编辑模式
        bpy.ops.object.mode_set(mode='OBJECT')

        success = 0
        for obj, (center, normal, tangent) in obj_face_data.items():
            try:
                self._set_origin_to_face(obj, center, normal, tangent)
                success += 1
            except (RuntimeError, AttributeError, TypeError, ValueError, ReferenceError) as e:
                print(f"[1000Map] 设置原点失败 {obj.name}: {e}")

        total = len(obj_face_data)
        if success < total:
            self.report({'WARNING'}, f"原点设置完成：成功 {success}/{total}（部分失败，详情见控制台）")
        else:
            self.report({'INFO'}, f"原点设置完成：成功 {success}/{total}")
        return {'FINISHED'}

    def _set_origin_to_face(self, obj, center, normal, tangent):
        """将物体原点设置到面中心，旋转对齐面坐标系"""
        # 构建面坐标系：X=切线, Y=法向×切线, Z=法向
        x_axis = tangent.normalized()
        z_axis = normal.normalized()
        y_axis = z_axis.cross(x_axis).normalized()
        # 重新正交化X轴
        x_axis = y_axis.cross(z_axis).normalized()

        # 旋转矩阵（列向量为面坐标系的三个轴）
        rot_mat = Matrix((
            (x_axis.x, y_axis.x, z_axis.x, 0),
            (x_axis.y, y_axis.y, z_axis.y, 0),
            (x_axis.z, y_axis.z, z_axis.z, 0),
            (0, 0, 0, 1),
        ))

        # 平移矩阵（到面中心）
        trans_mat = Matrix.Translation(center)

        # 新原点变换矩阵
        new_origin_mat = trans_mat @ rot_mat

        # 当前世界矩阵
        old_world = obj.matrix_world.copy()

        # 计算需要施加给网格数据的变换
        # new_world = new_origin_mat
        # 网格数据需要变换：mesh_transform = new_origin_mat的逆 × old_world
        mesh_transform = new_origin_mat.inverted() @ old_world

        # 设置新的世界矩阵
        obj.matrix_world = new_origin_mat

        # 反向偏移网格数据
        obj.data.transform(mesh_transform)


# ============================================================
# 场景清理：移除孤立数据块
# ============================================================
class MAP_OT_purge_scene(bpy.types.Operator):
    """清理当前文件中未使用的数据"""
    bl_idname = "map.purge_scene"
    bl_label = "从该文件中清理未使用的数据"
    bl_description = "递归清理孤立数据块（本地数据+已关联数据），保持工程文件清爽"
    bl_options = {'REGISTER', 'UNDO'}

    def _purge_orphans(self):
        """手动移除所有 users==0 的孤立数据块（递归直到无孤立数据）

        不使用 bpy.ops.outliner.orphans_purge()，该内层 operator 在某些场景
        会 report ERROR，其错误报告穿透到状态栏显示红叉，覆盖我们的 INFO 提示。
        手动 bpy.data.X.remove() 不产生任何 operator 报告。
        """
        collections = (
            bpy.data.meshes, bpy.data.materials, bpy.data.images,
            bpy.data.curves, bpy.data.node_groups, bpy.data.actions,
            bpy.data.cameras, bpy.data.lights, bpy.data.textures,
            bpy.data.metaballs, bpy.data.lattices, bpy.data.fonts,
            bpy.data.armatures,
        )
        total_removed = 0
        while True:
            batch_removed = 0
            for collection in collections:
                orphans = [item for item in collection if item.users == 0]
                for item in orphans:
                    try:
                        collection.remove(item)
                        batch_removed += 1
                    except (RuntimeError, ReferenceError):
                        pass
            if batch_removed == 0:
                break
            total_removed += batch_removed
        return total_removed

    def execute(self, context):
        try:
            purged_count = self._purge_orphans()
        except Exception as e:
            self.report({'WARNING'}, f"清理过程中出现异常: {e}")
            return {'CANCELLED'}

        if purged_count == 0:
            self.report({'INFO'}, "场景很干净，没有孤立数据块")
        else:
            self.report({'INFO'}, f"清理完成，移除 {purged_count} 个孤立数据块")
        return {'FINISHED'}


# ============================================================
# 色块贴图打包：按材质颜色生成全局色块贴图
# ============================================================
class MAP_OT_build_atlas(bpy.types.Operator):
    bl_idname = "map.build_atlas"
    bl_label = "生成色块贴图"
    bl_description = "按材质颜色生成全局色块贴图，自动合并相同材质以优化渲染性能"
    bl_options = {'REGISTER', 'UNDO'}
    BLOCK = 64

    def execute(self, context):
        mesh_objs = [o for o in context.scene.objects if o.type == 'MESH' and not o.hide_viewport]
        if not mesh_objs: self.report({'ERROR'}, "场景中没有可见网格！"); return {'CANCELLED'}

        material_to_key = {}
        color_groups = {}
        for obj in mesh_objs:
            for slot in obj.material_slots:
                mat = slot.material
                if not mat or not mat.use_nodes: continue
                if mat in material_to_key: continue
                bsdf = next((n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if not bsdf: continue
                r, g, b, _ = bsdf.inputs['Base Color'].default_value
                a = bsdf.inputs['Alpha'].default_value
                lin = (r, g, b, a)
                key = tuple(round(c, 3) for c in lin)
                material_to_key[mat] = key
                if key not in color_groups:
                    color_groups[key] = {'linear': lin, 'mats': set()}
                color_groups[key]['mats'].add(mat)

        entries = list(color_groups.items()); N = len(entries)
        if N == 0:
            self.report({'ERROR'}, "未找到任何 Principled BSDF 材质，请先执行「一键挤出」！")
            return {'CANCELLED'}
        grid_cols = math.ceil(math.sqrt(N)); grid_rows = math.ceil(N / grid_cols)

        def next_pow2(x):
            p = 1
            while p < x: p <<= 1
            return p

        img_w = next_pow2(grid_cols * self.BLOCK); img_h = next_pow2(grid_rows * self.BLOCK)
        atlas_name = "3DMap_ColorAtlas"
        if atlas_name in bpy.data.images: bpy.data.images.remove(bpy.data.images[atlas_name])

        img = bpy.data.images.new(atlas_name, width=img_w, height=img_h, alpha=True)
        img.colorspace_settings.name = 'sRGB'
        pixels = [0.0] * (img_w * img_h * 4); color_uvs = {}

        for i, (key, data) in enumerate(entries):
            col_idx = i % grid_cols; row_idx = i // grid_cols
            sr = linear_to_srgb(data['linear'][0]); sg = linear_to_srgb(data['linear'][1])
            sb = linear_to_srgb(data['linear'][2]); a = data['linear'][3]
            px0 = col_idx * self.BLOCK; py0 = row_idx * self.BLOCK
            for dy in range(self.BLOCK):
                for dx in range(self.BLOCK):
                    idx = ((py0 + dy) * img_w + (px0 + dx)) * 4
                    pixels[idx], pixels[idx+1], pixels[idx+2], pixels[idx+3] = sr, sg, sb, a
            color_uvs[key] = ((col_idx * self.BLOCK + self.BLOCK * 0.5) / img_w,
                              (row_idx * self.BLOCK + self.BLOCK * 0.5) / img_h)
        img.pixels = pixels; img.pack()

        mat_opaque_name = "Mat_3DMap_Atlas_Opaque"
        mat_trans_name = "Mat_3DMap_Atlas_Transparent"

        for m_name in [mat_opaque_name, mat_trans_name]:
            if m_name in bpy.data.materials:
                bpy.data.materials.remove(bpy.data.materials[m_name])

        def setup_atlas_mat(name, is_transparent):
            mat = bpy.data.materials.new(name=name)
            mat.use_nodes = True
            nodes = mat.node_tree.nodes; links = mat.node_tree.links
            for n in nodes: nodes.remove(n)

            tex  = nodes.new('ShaderNodeTexImage')
            bsdf = nodes.new('ShaderNodeBsdfPrincipled')
            out  = nodes.new('ShaderNodeOutputMaterial')
            tex.location  = (-320, 300)
            bsdf.location = (  10, 300)
            out.location  = ( 300, 300)
            tex.image = img; tex.interpolation = 'Closest'
            bsdf.inputs['Roughness'].default_value = 0.2 if is_transparent else 0.8

            links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
            if is_transparent:
                links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
                mat.blend_method = 'BLEND'
                if hasattr(mat, 'shadow_method'):
                    mat.shadow_method = 'NONE'
            else:
                mat.blend_method = 'OPAQUE'

            links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
            return mat

        mat_opaque = setup_atlas_mat(mat_opaque_name, False)
        mat_trans = setup_atlas_mat(mat_trans_name, True)

        HALF = 0.00005
        for obj in mesh_objs:
            me = obj.data
            if not me.uv_layers: me.uv_layers.new(name="UVMap")
            uv_layer = me.uv_layers.active

            slot_uv = {}
            for slot_idx, slot in enumerate(obj.material_slots):
                mat = slot.material
                key = material_to_key.get(mat)
                if key and key in color_uvs:
                    slot_uv[slot_idx] = color_uvs[key]

            loop_count = len(me.loops)
            uv_flat = [0.0] * (loop_count * 2)
            for poly in me.polygons:
                uv = slot_uv.get(poly.material_index)
                if uv is None: continue
                uc, vc = uv
                for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                    offset = HALF if (li % 2 == 0) else -HALF
                    uv_flat[li * 2]     = uc + offset
                    uv_flat[li * 2 + 1] = vc + offset
            uv_layer.data.foreach_set("uv", uv_flat)

            slots = list(obj.material_slots)
            if not slots: continue

            target_mats = []
            for slot in slots:
                mat = slot.material
                key = material_to_key.get(mat)
                if not key:
                    target_mats.append(mat)
                else:
                    a = color_groups[key]['linear'][3]
                    target_mats.append(mat_trans if a < 1.0 else mat_opaque)

            for slot_idx, slot in enumerate(slots):
                slot.material = target_mats[slot_idx]

            new_mats = []
            old_to_new = {}
            seen = {}
            for old_idx, mat in enumerate(target_mats):
                if mat in seen:
                    old_to_new[old_idx] = seen[mat]
                else:
                    seen[mat] = len(new_mats)
                    old_to_new[old_idx] = len(new_mats)
                    new_mats.append(mat)

            if len(new_mats) == len(slots): continue

            obj.data.materials.clear()
            for mat in new_mats:
                obj.data.materials.append(mat)

            for poly in obj.data.polygons:
                new_idx = old_to_new.get(poly.material_index)
                if new_idx is not None:
                    poly.material_index = new_idx

        self.report({'INFO'}, "色块贴图生成完成（按材质聚合，自动合并冗余槽）")
        return {'FINISHED'}


classes = (
    MAP_OT_purge_scene,
    MAP_OT_clean_uvmap,
    MAP_OT_clear_split_normals,
    MAP_OT_set_origin_to_face,
    MAP_OT_build_atlas,
)
