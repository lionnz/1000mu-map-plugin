import bpy
import bmesh
import math

class MAP_OT_check_zero_area(bpy.types.Operator):
    """检查所选网格是否存在0面积面"""
    bl_idname = "map.check_zero_area"
    bl_label = "检查0面积的面"
    bl_description = "检查选中网格是否存在0面积面（面积<0.0001），将问题物体归入集合"
    bl_options = {'REGISTER', 'UNDO'}

    AREA_THRESHOLD = 0.0001

    def execute(self, context):
        mesh_objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not mesh_objs:
            self.report({'WARNING'}, "请先选中网格物体")
            return {'CANCELLED'}

        problem_objs = []
        for obj in mesh_objs:
            has_zero = False
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            for face in bm.faces:
                if face.calc_area() < self.AREA_THRESHOLD:
                    has_zero = True
                    break
            bm.free()
            if has_zero:
                problem_objs.append(obj)

        if problem_objs:
            # 查找或创建集合
            col = bpy.data.collections.get("0面积的面")
            if col is None:
                col = bpy.data.collections.new("0面积的面")
                context.scene.collection.children.link(col)
            # 把问题物体移动至集合（从其他集合移除，避免一物体多集合混乱）
            for obj in problem_objs:
                if obj.name not in col.objects:
                    col.objects.link(obj)
                # 从场景集合及其他集合中取消链接
                for c in list(obj.users_collection):
                    if c != col:
                        c.objects.unlink(obj)

            self.report({'INFO'},
                f"共检查 {len(mesh_objs)} 个网格，其中 {len(problem_objs)} 个存在0面积的面，已移动至集合「0面积的面」")
        else:
            self.report({'INFO'}, f"共检查 {len(mesh_objs)} 个网格，全部正常，没有0面积的面")

        return {'FINISHED'}


class MAP_OT_retopology(bpy.types.Operator):
    """对所选网格重新拓扑，消除0面积面"""
    bl_idname = "map.retopology"
    bl_label = "重新拓扑"
    bl_description = "通过轮廓线提取+曲线填充重建网格拓扑，消除0面积面"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh_objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not mesh_objs:
            self.report({'WARNING'}, "请先选中网格物体")
            return {'CANCELLED'}

        success = 0
        failed = 0
        for obj in mesh_objs:
            try:
                self._retopo_single(context, obj)
                success += 1
            except (RuntimeError, AttributeError, TypeError, ValueError, ReferenceError) as e:
                print(f"[1000Map] 重新拓扑失败 {obj.name}: {e}")
                failed += 1

        if failed > 0:
            self.report({'WARNING'}, f"重新拓扑完成：成功 {success}，失败 {failed}（详情见控制台）")
        elif success == 0:
            self.report({'WARNING'}, "重新拓扑失败：未成功处理任何网格")
        else:
            self.report({'INFO'}, f"重新拓扑完成：成功 {success} 个网格")
        return {'FINISHED'}

    def _retopo_single(self, context, obj):
        """对单个网格执行重新拓扑：提取边界轮廓线→转曲线→填充曲线→转网格"""
        # 确保在物体模式
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 保存材质列表
        # 根因：bmesh 删除所有面后网格只剩边线，convert(target='CURVE') 时
        # Blender 发现没有面引用材质，不会把材质槽迁移到曲线物体，
        # 导致最终转回网格时材质丢失。需手动保存并在最后恢复。
        saved_materials = list(obj.data.materials)

        # 前置优化：按距离合并 + 有限融并
        # 针对GLB三角化后产生的退化网格（重合顶点、共线折点），
        # 先清理冗余顶点，避免边界边提取阶段误判轮廓线
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        try:
            bpy.ops.mesh.remove_doubles(threshold=0.0001)  # 0.1mm 按距离合并
            bpy.ops.mesh.dissolve_limited(angle_limit=math.radians(0.1))  # 0.1° 有限融并
        except RuntimeError as e:
            print(f"[1000Map] 前置优化失败 {obj.name}: {e}")
        bpy.ops.object.mode_set(mode='OBJECT')

        # 步骤1-5：用 bmesh 提取边界轮廓线（替代 bpy.ops 的5步操作）
        bm = bmesh.new()
        bm.from_mesh(obj.data)

        # 1. 删除松散元素（孤立顶点和边）
        loose_verts = [v for v in bm.verts if not v.link_edges]
        loose_edges = [e for e in bm.edges if not e.link_faces]
        if loose_verts:
            bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')
        if loose_edges:
            bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

        # 2. 找到边界边（只属于一个面的边，即区域轮廓线）
        boundary_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        if not boundary_edges:
            bm.free()
            raise ValueError("网格没有边界边，无法提取轮廓")

        # 3. 删除所有面
        bmesh.ops.delete(bm, geom=list(bm.faces), context='FACES_ONLY')

        # 4. 删除非边界边（保留轮廓线）
        non_boundary_edges = [e for e in bm.edges if e not in set(boundary_edges)]
        if non_boundary_edges:
            bmesh.ops.delete(bm, geom=non_boundary_edges, context='EDGES')

        # 5. 删除孤立顶点（不属于任何边的）
        isolated_verts = [v for v in bm.verts if not v.link_edges]
        if isolated_verts:
            bmesh.ops.delete(bm, geom=isolated_verts, context='VERTS')

        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

        # 步骤6：有限融并（最大角度0.1度）——需要 bpy.ops
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        try:
            bpy.ops.mesh.dissolve_limited(angle_limit=math.radians(0.1))
        except RuntimeError as e:
            print(f"[1000Map] 有限融并失败 {obj.name}: {e}")
        bpy.ops.object.mode_set(mode='OBJECT')

        # 步骤7：转曲线
        try:
            bpy.ops.object.convert(target='CURVE')
        except RuntimeError as e:
            raise RuntimeError(f"转曲线失败: {e}")

        # 设置曲线为2D（用户确认：不需要3D，2D即可）
        obj.data.dimensions = '2D'

        # 步骤8：创建几何节点组（Group Input → Fill Curve → Group Output）
        # 注意：Blender 4.x 中 type 枚举值为 'GeometryNodeTree'（非 'GEOMETRY'）
        ng = bpy.data.node_groups.new(f'FillCurve_{obj.name}', type='GeometryNodeTree')

        # 创建 Geometry socket（Blender 4.0+ 用 ng.interface.new_socket）
        ng.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

        nodes = ng.nodes
        links = ng.links
        input_node = nodes.new('NodeGroupInput')
        input_node.location = (-400, 0)
        output_node = nodes.new('NodeGroupOutput')
        output_node.location = (400, 0)

        fill_node = nodes.new('GeometryNodeFillCurve')
        fill_node.location = (0, 0)
        # Blender 4.2 中 FillCurve 默认即 N-gons 模式，无 fill_mode 属性
        if hasattr(fill_node, 'fill_mode'):
            fill_node.fill_mode = 'NGONS'
        elif hasattr(fill_node, 'mode'):
            fill_node.mode = 'NGONS'

        # 连接：Group Input → Fill Curve → Group Output
        links.new(input_node.outputs[0], fill_node.inputs[0])
        links.new(fill_node.outputs[0], output_node.inputs[0])

        # 将节点组赋给修改器
        mod = obj.modifiers.new(name='FillCurve', type='NODES')
        mod.node_group = ng

        # 步骤9：转回网格
        # Blender 4.2 中 convert(target='MESH') 会自动烘焙几何节点修改器结果
        bpy.ops.object.convert(target='MESH')

        # 恢复材质（bmesh 删面后转曲线，材质槽未迁移，需手动恢复）
        if saved_materials:
            obj.data.materials.clear()
            for mat in saved_materials:
                if mat is not None:
                    obj.data.materials.append(mat)

        # 步骤10：面三角化 → 三角面转四边面
        # 烘焙后的网格面可能不够稳定，先三角化再转四边面，
        # 用 Blender 原生算法重建稳定拓扑，降低 GLB 导出三角化时产生0面积面的概率
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        try:
            bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
            bpy.ops.mesh.tris_convert_to_quads(face_threshold=math.radians(1.0), shape_threshold=math.radians(1.0))
        except RuntimeError as e:
            print(f"[1000Map] 三角化/转四边面失败 {obj.name}: {e}")
        bpy.ops.object.mode_set(mode='OBJECT')

        # 步骤11：兜底清理——删除残留的0面积退化面
        # BEAUTY三角化对复杂形状可能产生细长退化三角形，
        # 1°阈值下tris_convert_to_quads无法合并，需直接检测并删除
        bm2 = bmesh.new()
        bm2.from_mesh(obj.data)
        degenerate_faces = [f for f in bm2.faces if f.calc_area() < 0.0001]
        if degenerate_faces:
            bmesh.ops.delete(bm2, geom=degenerate_faces, context='FACES')
            bm2.to_mesh(obj.data)
            obj.data.update()
            # 删除面后清理孤立顶点
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.remove_doubles(threshold=0.0001)
            bpy.ops.mesh.delete_loose()
            bpy.ops.object.mode_set(mode='OBJECT')
            print(f"[1000Map] 兜底清理 {obj.name}: 删除 {len(degenerate_faces)} 个退化面")
        bm2.free()

        # 清理不再引用的几何节点组，避免 bpy.data.node_groups 堆积
        if ng.users == 0:
            bpy.data.node_groups.remove(ng)


class MAP_OT_optimize_curve(bpy.types.Operator):
    """对所选曲线物体进行网格优化：FillCurve填充→三角化→转四边面→兜底清理0面积面"""
    bl_idname = "map.optimize_curve"
    bl_label = "对所选曲线物体进行网格优化"
    bl_description = "对选中曲线物体执行 FillCurve 填充→转网格→面三角化→转四边面→兜底清理0面积面，生成稳定拓扑"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        curve_objs = [o for o in context.selected_objects if o.type == 'CURVE']
        if not curve_objs:
            self.report({'WARNING'}, "未选中任何曲线物体")
            return {'CANCELLED'}

        success = 0
        failed = 0
        for obj in curve_objs:
            try:
                self._optimize_single(context, obj)
                success += 1
            except (RuntimeError, AttributeError, TypeError, ValueError, ReferenceError) as e:
                print(f"[1000Map] 曲线网格优化失败 {obj.name}: {e}")
                failed += 1

        if failed > 0:
            self.report({'WARNING'}, f"曲线网格优化完成：成功 {success}，失败 {failed}（详情见控制台）")
        elif success == 0:
            self.report({'WARNING'}, "曲线网格优化失败：未成功处理任何曲线")
        else:
            self.report({'INFO'}, f"曲线网格优化完成：成功 {success} 条曲线")
        return {'FINISHED'}

    def _optimize_single(self, context, obj):
        """对单个曲线物体执行：FillCurve填充→转网格→面三角化→转四边面→兜底清理"""
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # 保存材质（convert 烘焙会清空材质）
        saved_materials = list(obj.data.materials)

        # 确保曲线为2D
        obj.data.dimensions = '2D'
        obj.data.fill_mode = 'NONE'

        # 创建 FillCurve 几何节点组
        ng = bpy.data.node_groups.new(f'FillCurve_{obj.name}', type='GeometryNodeTree')
        ng.interface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
        ng.interface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
        nodes = ng.nodes
        links = ng.links
        input_node = nodes.new('NodeGroupInput')
        output_node = nodes.new('NodeGroupOutput')
        fill_node = nodes.new('GeometryNodeFillCurve')
        if hasattr(fill_node, 'fill_mode'):
            fill_node.fill_mode = 'NGONS'
        elif hasattr(fill_node, 'mode'):
            fill_node.mode = 'NGONS'
        links.new(input_node.outputs[0], fill_node.inputs[0])
        links.new(fill_node.outputs[0], output_node.inputs[0])

        mod = obj.modifiers.new(name='FillCurve', type='NODES')
        mod.node_group = ng

        # 转网格（烘焙几何节点）
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.convert(target='MESH')

        # 恢复材质
        if saved_materials:
            obj.data.materials.clear()
            for mat in saved_materials:
                if mat is not None:
                    obj.data.materials.append(mat)

        # 面三角化 → 三角面转四边面
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
            print(f"[1000Map] 曲线优化兜底清理 {obj.name}: 删除 {len(degenerate_faces)} 个退化面")
        bm2.free()

        # 清理几何节点组
        if ng.users == 0:
            bpy.data.node_groups.remove(ng)


classes = (
    MAP_OT_check_zero_area,
    MAP_OT_retopology,
    MAP_OT_optimize_curve,
)
