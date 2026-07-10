import bpy


class MAP_OT_purge_scene(bpy.types.Operator):
    """清理当前文件中未使用的数据"""
    bl_idname = "map.purge_scene"
    bl_label = "从该文件中清理未使用的数据"
    bl_description = "递归清理孤立数据块（本地数据+已关联数据），保持工程文件清爽"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # 递归清理，直到没有孤立数据可清
        purged_count = 0
        while True:
            before = len(bpy.data.meshes) + len(bpy.data.materials) + len(bpy.data.images) + len(bpy.data.curves)
            try:
                bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
            except Exception as e:
                print(f"[1000Map] 清理中断: {e}")
                break
            after = len(bpy.data.meshes) + len(bpy.data.materials) + len(bpy.data.images) + len(bpy.data.curves)
            if before == after:
                break
            purged_count += (before - after)
        self.report({'INFO'}, f"清理完成，移除 {purged_count} 个孤立数据块")
        return {'FINISHED'}


classes = (
    MAP_OT_purge_scene,
)
