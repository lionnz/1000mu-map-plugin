import bpy
import bmesh
from mathutils import Matrix, Vector
from bpy.app.handlers import persistent


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

        self.report({'INFO'}, f"原点设置完成：成功 {success}/{len(obj_face_data)}")
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


classes = (
    MAP_OT_clean_uvmap,
    MAP_OT_clear_split_normals,
    MAP_OT_set_origin_to_face,
)
