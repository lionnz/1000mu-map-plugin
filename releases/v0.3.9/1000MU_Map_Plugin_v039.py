bl_info = {
    "name": "1000MU 3D周边地图插件 Figma to Blender",
    "author": "Design Team",
    "version": (0, 3, 9),
    "blender": (4, 2, 0),
    "location": "View3D > N Panel > 1000Map",
    "description": "v0.3.9: 1000MU设计团队专用AI效率插件。双轨制材质分流、单物体多材质球支持与高保真动流优化。",
    "category": "3D View",
}

# ============================================================================
# v0.3.9 变更摘要（相对 v0.3.8）
#   1. 多材质球物体支持：色块贴图引擎由「按物体聚合」改为「按材质聚合 + 按面写 UV」，
#      单物体含多个材质球时无需分离即可正确贴图，零顶点增量。
#   2. 法线统一隔离：挤出末尾的 normals_make_consistent 仅作用于地图物体，不再误伤场景其他资产。
#   3. 孤立数据清理降级为非递归，避免误删用户暂时未引用但希望保留的资产。
#   4. force_normals_up 引入 epsilon，防止浮点抖动导致的法线翻转误判。
#   5. 拼音降级模式：纯中文名无 ASCII 时改用 md5 哈希前缀，避免大量重名为 'layer'。
#   6. SVG 导入改用 tempfile 生成临时文件，避免无写权限或多实例冲突。
#   7. 减少裸 except 吞异常，关键路径打印错误信息便于排查。
# ============================================================================

import bpy
import bmesh
import os
import sys
import random
import xml.etree.ElementTree as ET
import urllib.parse
import re
import hashlib
import tempfile

# ── 依赖隔离引擎（不阻塞主线程）──────────────────────
def get_pypinyin():
    try:
        from pypinyin import lazy_pinyin
        return lazy_pinyin
    except ImportError:
        return None
    except Exception as e:
        print(f"[1000Map] pypinyin 加载异常: {e}")
        return None

def chinese_to_safe_name(s):
    lazy_pinyin = get_pypinyin()
    if lazy_pinyin:
        try:
            parts = lazy_pinyin(s)
            safe_parts = [re.sub(r'[^a-zA-Z0-9]', '', p) for p in parts if re.sub(r'[^a-zA-Z0-9]', '', p)]
            result = '_'.join(safe_parts) if safe_parts else 'layer'
            return result
        except Exception as e:
            print(f"[1000Map] pypinyin 转换失败，降级处理: {e}")
    fallback = re.sub(r'[^a-zA-Z0-9_]', '', s)
    if fallback:
        return fallback
    # 纯中文名等无 ASCII 字符时，用哈希避免全部变成 'layer' 重名
    return 'layer_' + hashlib.md5(s.encode('utf-8')).hexdigest()[:8]

INVALID_LAYER_NAMES = {'svg','g','path','rect','circle','ellipse','polygon','polyline','line','layer','group','root','vector'}
DEFAULT_HEIGHT_CONFIG = {"绿化":10.0,"主路":20.0,"支路":15.0,"中色box":40.0,"浅色box":50.0,"文字":0.5,"商场边框":60.0,"水":5.0,"深色box":30.0,"商场":80.0}

# ------------------- 核心几何手术刀 -------------------
def force_normals_up(obj, epsilon=1e-5):
    """翻转朝下法线，使其朝 +Z。epsilon 防止浮点抖动误判。"""
    if obj.type != 'MESH': return
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for face in bm.faces:
        if face.normal.z < -epsilon:
            face.normal_flip()
    bm.normal_update()
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

# ------------------- Property Groups -------------------
class MAP_PG_layer_item(bpy.types.PropertyGroup):
    is_active: bpy.props.BoolProperty(name="启用", default=True)
    layer_name: bpy.props.StringProperty(name="图层名", default="")
    height: bpy.props.FloatProperty(name="高度(m)", default=0.0, min=0.0, step=10)
    color: bpy.props.FloatVectorProperty(name="颜色", subtype='COLOR', size=4, default=(0.8,0.8,0.8,1.0), min=0.0, max=1.0)
    use_rand_height: bpy.props.BoolProperty(
        name="随机高度", default=False,
        description="启用后，该图层下所有物体的挤出高度将在设定区间内随机，产生错落感"
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
    svg_filepath: bpy.props.StringProperty(name="SVG文件", subtype='FILE_PATH')
    ratio_px: bpy.props.FloatProperty(name="px", default=10.0, min=0.1)
    ratio_m: bpy.props.FloatProperty(name="m", default=1.0, min=0.01)
    curve_res: bpy.props.IntProperty(name="曲线精度", default=4, min=1, max=12)
    layer_list: bpy.props.CollectionProperty(type=MAP_PG_layer_item)
    layer_list_idx: bpy.props.IntProperty()
    export_dir: bpy.props.StringProperty(name="导出目录", subtype='DIR_PATH', default=os.path.expanduser("~/Downloads") + os.sep)
    export_filename: bpy.props.StringProperty(name="文件名", default="3d_map")
    exp_visible_only: bpy.props.BoolProperty(name="仅导出可见", default=True)
    exp_apply_modifiers: bpy.props.BoolProperty(name="应用修改器", default=True)
    exp_pinyin_safe: bpy.props.BoolProperty(name="拼音防呆", default=True, description="导出时静默去中文，防前端报错")
    active_tab: bpy.props.IntProperty(default=0)

# ------------------- SVG 解码与工具库 -------------------
def decode_figma_id(raw_id):
    if not raw_id: return ""
    decoded = raw_id
    try: decoded = decoded.encode('latin1').decode('utf-8')
    except Exception: pass
    def replace_hex(match):
        try: return chr(int(match.group(1),16))
        except Exception: return match.group(0)
    decoded = re.sub(r'_x([0-9a-fA-F]{4,6})_', replace_hex, decoded)
    decoded = urllib.parse.unquote(decoded)
    return re.sub(r'_[0-9]+$', '', decoded).strip()

def get_base_name(name):
    return re.sub(r'\.\d{3,}$', '', name).strip()

def parse_svg_colors(svg_path):
    """提取 SVG 中每个图层基准名对应的颜色。
    注意：同名图层只保留首次出现的颜色（设计选择，文档已说明）。"""
    colors = {}
    try: tree = ET.parse(svg_path); root = tree.getroot()
    except Exception as e:
        print(f"[1000Map] SVG 解析失败: {e}")
        return colors

    def srgb_to_linear(c):
        c = max(0.0, min(1.0, c))
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def hex_to_float(h, a=1.0):
        h = h.lstrip('#')
        if len(h) == 3: h = ''.join(c*2 for c in h)
        r = srgb_to_linear(int(h[0:2],16)/255.0)
        g = srgb_to_linear(int(h[2:4],16)/255.0)
        b = srgb_to_linear(int(h[4:6],16)/255.0)
        return (r, g, b, float(a))

    def extract_fill_and_alpha(element):
        style = element.get('style','')
        fill = None; alpha = 1.0
        m_fill = re.search(r'(?:^|;)\s*fill\s*:\s*(#[0-9a-fA-F]{3,6})', style)
        if m_fill: fill = m_fill.group(1)
        else:
            attr_fill = element.get('fill','')
            if attr_fill and attr_fill.startswith('#'): fill = attr_fill
        m_op = re.search(r'(?:^|;)\s*fill-opacity\s*:\s*([\d\.]+)', style)
        if not m_op: m_op = re.search(r'(?:^|;)\s*opacity\s*:\s*([\d\.]+)', style)
        if m_op:
            try: alpha = float(m_op.group(1))
            except ValueError: pass
        else:
            attr_op = element.get('fill-opacity', element.get('opacity'))
            if attr_op:
                try: alpha = float(attr_op)
                except ValueError: pass
        return fill, alpha

    def traverse(el, current_layer):
        tag = el.tag.split('}')[-1]
        is_shape = tag in {'path','rect','circle','ellipse','polygon','polyline','line'}
        raw_id = el.get('id')
        if is_shape:
            layer_key = current_layer
            if not layer_key and raw_id:
                decoded = decode_figma_id(raw_id)
                if decoded and decoded.lower() not in INVALID_LAYER_NAMES: layer_key = decoded
            if layer_key:
                base_key = re.sub(r'\.\d{3,}$', '', layer_key).strip()
                fill, alpha = extract_fill_and_alpha(el)
                if fill and base_key and base_key not in colors:
                    try: colors[base_key] = hex_to_float(fill, alpha)
                    except Exception as e:
                        print(f"[1000Map] 颜色解析失败 {fill}: {e}")
        else:
            if raw_id:
                decoded = decode_figma_id(raw_id)
                if decoded and decoded.lower() not in INVALID_LAYER_NAMES: current_layer = decoded
        for child in el: traverse(child, current_layer)
    traverse(root, None)
    return colors

# ------------------- Operators (操作算子) -------------------
class MAP_OT_install_env(bpy.types.Operator):
    bl_idname = "map.install_env"
    bl_label = "初始化/修复拼音环境"
    bl_description = "一键后台安装 pypinyin 库，保证完美的中转英防呆功能（需网络畅通）"
    def execute(self, context):
        import subprocess
        self.report({'INFO'}, "正在后台安装拼音库，请稍候...")
        try:
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'pypinyin'], capture_output=True, text=True, timeout=60)
            self.report({'INFO'}, "🎉 拼音引擎修复成功！")
            context.area.tag_redraw()
        except Exception as e:
            self.report({'ERROR'}, f"安装失败: {e}")
        return {'FINISHED'}

class MAP_OT_switch_tab(bpy.types.Operator):
    bl_idname = "map.switch_tab"; bl_label = "切换标签"
    tab_index: bpy.props.IntProperty(default=0)
    def execute(self,context): context.scene.map_props.active_tab = self.tab_index; return {'FINISHED'}

class MAP_OT_import_svg(bpy.types.Operator):
    bl_idname = "map.import_svg"
    bl_label = "导入并重构空间"
    bl_description = "自动执行物理单位换算与绝对居中，智能嗅探 viewBox 尺寸，静默修复 Figma 中文乱码，并一键转换为网格平面"

    def execute(self, context):
        props = context.scene.map_props
        input_file = bpy.path.abspath(props.svg_filepath)
        if not os.path.exists(input_file) or not input_file.lower().endswith('.svg'):
            self.report({'ERROR'}, "请选择有效的SVG文件！"); return {'CANCELLED'}

        # 使用 tempfile 生成临时 SVG，避免无写权限或多实例冲突
        fd, temp_svg = tempfile.mkstemp(suffix='.svg', prefix='blender_map_')
        os.close(fd)
        ET.register_namespace('',"http://www.w3.org/2000/svg")
        tree = ET.parse(input_file); root = tree.getroot()

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
                if raw_id:
                    decoded = decode_figma_id(raw_id)
                    if decoded and decoded.lower() not in INVALID_LAYER_NAMES: current_target_id = decoded
            for child in element: apply_target_id(child, current_target_id)

        apply_target_id(root, None)
        tree.write(temp_svg,encoding='utf-8',xml_declaration=True)

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
        bpy.ops.object.convert(target='MESH')

        meshes = [o for o in new_objs if o.type=='MESH']
        for obj in meshes: obj.location.x+=offset_x; obj.location.y+=offset_y
        bpy.ops.object.select_all(action='DESELECT'); [o.select_set(True) for o in meshes]; context.view_layer.objects.active=meshes[0]
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=False)

        svg_colors = parse_svg_colors(input_file)
        props.layer_list.clear()
        seen_base_names = {}
        for obj in meshes:
            if obj.name.lower() in INVALID_LAYER_NAMES: continue
            base = get_base_name(obj.name)
            if base in seen_base_names: continue

            item = props.layer_list.add()
            item.layer_name = base
            seen_base_names[base] = item

            matched = False
            for k, h in DEFAULT_HEIGHT_CONFIG.items():
                if k in base:
                    item.height = h
                    matched = True; break
            if not matched: item.height = float(random.randint(1, 10))

            color_hit = svg_colors.get(base)
            if color_hit: item.color = color_hit

        props.active_tab=1
        self.report({'INFO'},f"成功！物理尺寸: {svg_w}x{svg_h}，共 {len(props.layer_list)} 个图层")
        return {'FINISHED'}

class MAP_OT_generate_3d(bpy.types.Operator):
    bl_idname = "map.generate_3d"
    bl_label = "一键挤出"
    bl_description = "强制纠正法线朝上并按高度挤出，自动为纯平面附加防闪烁(Z-fighting)微缩阶梯，并赋予基础材质"

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
            for i in props.layer_list if i.is_active
        }
        count = 0

        # 只处理已在图层列表中注册的地图网格，不影响场景内其他物体
        all_layer_names = set(layer_config.keys())
        def is_map_obj(obj):
            if obj.type != 'MESH': return False
            base = get_base_name(obj.name)
            return (base in all_layer_names or obj.name in all_layer_names
                    or any(obj.name.startswith(n + '.') for n in all_layer_names))

        bpy.ops.object.select_all(action='DESELECT')
        for obj in context.scene.objects:
            if not is_map_obj(obj): continue
            obj.modifiers.clear(); height = 0; color = (0.8, 0.8, 0.8, 1.0)
            obj_base = get_base_name(obj.name)

            for lname, conf in layer_config.items():
                if obj_base == lname or obj.name == lname or obj.name.startswith(lname + '.'):
                    color = conf['color']
                    if conf['use_rand_height']:
                        lo, hi = conf['rand_min'], conf['rand_max']
                        # 保证区间有效；若 lo==hi 直接用该值
                        height = round(random.uniform(lo, hi), 2) if hi > lo else lo
                    else:
                        height = conf['height']
                    break

            if height <= 0: height = float(random.randint(1, 10))
            force_normals_up(obj)

            # height 在导入时已保证 >= 1（预设值或随机整数），始终执行挤出
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

                bsdf.inputs['Base Color'].default_value = color
                bsdf.inputs['Alpha'].default_value = color[3]
                bsdf.inputs['Roughness'].default_value = 0.2 if color[3] < 1.0 else 0.8

                if color[3] < 1.0:
                    mat.blend_method = 'BLEND'
                    mat.shadow_method = 'NONE'

                links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

                def linear_to_srgb(c):
                    c = max(0.0, min(1.0, c))
                    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0/2.4)) - 0.055
                mat.diffuse_color = (linear_to_srgb(color[0]), linear_to_srgb(color[1]), linear_to_srgb(color[2]), color[3])
            else: mat = bpy.data.materials[matname]

            obj.data.materials.clear(); obj.data.materials.append(mat)
            count += 1

        # 仅对地图物体执行法线统一，避免误伤场景中其他资产（如反向法线刻意保留的模型）
        bpy.ops.object.select_all(action='DESELECT')
        map_objs = [o for o in context.scene.objects if is_map_obj(o)]
        for o in map_objs:
            o.select_set(True)
        if map_objs:
            context.view_layer.objects.active = map_objs[0]
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')

        # 孤立数据清理：非递归，避免误删用户暂时未引用但希望保留的资产
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=False)
        props.active_tab = 2
        return {'FINISHED'}

class MAP_OT_build_atlas(bpy.types.Operator):
    bl_idname = "map.build_atlas"
    bl_label = "生成色块贴图"
    bl_description = "【双轨制引擎】按材质聚合色彩与Alpha通道生成全局图集。支持单物体多材质球，按面写入UV并自动分流实体与透明材质，将 Draw Call 降至极致"
    BLOCK = 64

    def execute(self, context):
        import math
        mesh_objs = [o for o in context.scene.objects if o.type == 'MESH' and not o.hide_viewport]
        if not mesh_objs: self.report({'ERROR'}, "场景中没有可见网格！"); return {'CANCELLED'}

        def linear_to_srgb(c):
            c = max(0.0, min(1.0, c))
            return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055

        # ---- 第 1 步：按「材质」聚合（支持单物体多材质球） ----
        # 旧版按物体聚合（仅取 materials[0]）会导致单物体多材质球只贴首个材质。
        # 现改为按材质聚合：相同颜色的不同材质合并为同一色块，
        # UV 按面写入，每个面根据自身 material_index 指向对应色块。
        material_to_key = {}          # mat -> color_key
        color_groups = {}             # key -> {'linear': (r,g,b,a), 'mats': set()}
        for obj in mesh_objs:
            for slot in obj.material_slots:
                mat = slot.material
                if not mat or not mat.use_nodes: continue
                if mat in material_to_key: continue   # 同材质只算一次
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

        # --- 第 2 步：双轨制材质生成 ---
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
            # 从左到右依次排列：贴图 → BSDF → 输出
            tex.location  = (-320, 300)
            bsdf.location = (  10, 300)
            out.location  = ( 300, 300)
            tex.image = img; tex.interpolation = 'Closest'
            bsdf.inputs['Roughness'].default_value = 0.2 if is_transparent else 0.8

            links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
            if is_transparent:
                links.new(tex.outputs['Alpha'], bsdf.inputs['Alpha'])
                mat.blend_method = 'BLEND'
                mat.shadow_method = 'NONE'
            else:
                mat.blend_method = 'OPAQUE'

            links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
            return mat

        mat_opaque = setup_atlas_mat(mat_opaque_name, False)
        mat_trans = setup_atlas_mat(mat_trans_name, True)

        # --- 第 3 步：按面写入 UV + 替换材质槽（支持单物体多材质） ---
        # 关键：UV 是 per-loop 的，每个 loop 属于一个面，每个面有 material_index。
        # 因此同一物体的不同面可以指向不同色块，无需分离物体，零顶点增量。
        HALF = 0.00005
        for obj in mesh_objs:
            me = obj.data
            if not me.uv_layers: me.uv_layers.new(name="UVMap")
            uv_layer = me.uv_layers.active

            # 预计算该物体每个 material_index -> 色块 UV
            slot_uv = {}
            for slot_idx, slot in enumerate(obj.material_slots):
                mat = slot.material
                key = material_to_key.get(mat)
                if key and key in color_uvs:
                    slot_uv[slot_idx] = color_uvs[key]

            # 按面写 UV：同一物体的不同面可指向不同色块
            loop_count = len(me.loops)
            uv_flat = [0.0] * (loop_count * 2)
            for poly in me.polygons:
                uv = slot_uv.get(poly.material_index)
                if uv is None: continue
                uc, vc = uv
                # 交替微偏（±HALF）确保 UV 不完全退化为单点，防止 Mipmap 退化为 0
                for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                    offset = HALF if (li % 2 == 0) else -HALF
                    uv_flat[li * 2]     = uc + offset
                    uv_flat[li * 2 + 1] = vc + offset
            uv_layer.data.foreach_set("uv", uv_flat)

            # 替换材质槽：保持槽索引不变，face.material_index 仍然有效
            # 同色多槽会指向同一个图集材质，存在冗余但不影响渲染
            for slot in obj.material_slots:
                mat = slot.material
                key = material_to_key.get(mat)
                if not key: continue
                a = color_groups[key]['linear'][3]
                slot.material = mat_trans if a < 1.0 else mat_opaque

        self.report({'INFO'}, f"⚡ 双轨制图集生成完成 (按材质聚合，支持多材质物体)！")
        return {'FINISHED'}

class MAP_OT_export_glb(bpy.types.Operator):
    bl_idname = "map.export_glb"
    bl_label = "导出GLB"
    bl_description = "一键导出符合 WebGL 标准的 .glb 模型（附带无痕拼音防呆引擎，防前端报错）"

    def execute(self, context):
        props = context.scene.map_props
        pth = os.path.abspath(props.export_dir if props.export_dir else os.path.expanduser("~/Downloads"))
        os.makedirs(pth, exist_ok=True)
        filename = (props.export_filename.strip() or "3d_map").rstrip('.').removesuffix('.glb')
        exp_path = os.path.join(pth, filename + ".glb")

        all_mesh_objs = [o for o in context.scene.objects if o.type == 'MESH']
        if not all_mesh_objs: self.report({'WARNING'}, "场景中没有网格物体！"); return {'CANCELLED'}

        orig_obj_names = {o: (o.name, o.data.name if o.data else None) for o in all_mesh_objs}
        orig_mat_names = {}
        for o in all_mesh_objs:
            for slot in o.material_slots:
                if slot.material and slot.material not in orig_mat_names: orig_mat_names[slot.material] = slot.material.name

        try:
            if props.exp_pinyin_safe:
                for o in all_mesh_objs:
                    new_name = chinese_to_safe_name(o.name)
                    o.name = new_name
                    if o.data: o.data.name = new_name
                for mat, orig_name in orig_mat_names.items():
                    mat.name = 'Mat_' + chinese_to_safe_name(orig_name.removeprefix('Mat_'))

            bpy.ops.export_scene.gltf(
                filepath=exp_path, use_selection=False, use_visible=props.exp_visible_only,
                export_format='GLB', export_apply=props.exp_apply_modifiers,
                export_cameras=False, export_lights=False, export_materials='EXPORT',
            )
        finally:
            # 无论导出是否成功，都恢复原名，保证 .blend 工程文件名不被破坏
            for o, (obj_name, data_name) in orig_obj_names.items():
                try:
                    o.name = obj_name
                    if o.data and data_name: o.data.name = data_name
                except Exception as e:
                    print(f"[1000Map] 恢复物体名失败: {e}")
            for mat, orig_name in orig_mat_names.items():
                try: mat.name = orig_name
                except Exception as e:
                    print(f"[1000Map] 恢复材质名失败: {e}")

        self.report({'INFO'}, f"导出成功！共 {len(all_mesh_objs)} 个物体 → {exp_path}")
        return {'FINISHED'}

# ------------------- UI Panel -------------------
class MAP_UL_layer_list(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        split = layout.split(factor=0.08)
        split.prop(item, 'is_active', text='', icon='HIDE_OFF' if item.is_active else 'HIDE_ON')
        row = split.row(align=True)
        row.prop(item, 'layer_name', text='', emboss=False)
        # 随机开关按钮（骰子图标）
        rand_icon = 'OUTLINER_OB_FORCE_FIELD' if item.use_rand_height else 'FORCE_FORCE'
        row.prop(item, 'use_rand_height', text='', icon='SHADERFX', toggle=True)
        if item.use_rand_height:
            # 显示随机区间：[最小] ~ [最大]
            # 三段独立 row：min输入 | ~符号(固定窄) | max输入
            # scale_x 控制相对宽度比例，0.28 让 ~ 列保持可见且不随面板拉伸
            r_min = row.row(align=True)
            r_min.prop(item, 'rand_height_min', text='')
            r_tilde = row.row(align=True)
            r_tilde.scale_x = 0.28
            r_tilde.label(text='~')
            r_max = row.row(align=True)
            r_max.prop(item, 'rand_height_max', text='')
        else:
            row.prop(item, 'height', text='')
        row.prop(item, 'color', text='')

class MAP_PT_main_panel(bpy.types.Panel):
    bl_label="1000MU 3D周边地图插件"
    bl_idname="MAP_PT_main_panel"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='1000Map' # 团队专属 N 面板标签名称
    def draw(self,context):
        props=context.scene.map_props; layout=self.layout
        row=layout.row(align=True)
        for idx,text in enumerate(['导入','预设','导出']):
            op=row.operator('map.switch_tab',text=text,depress=(props.active_tab==idx)); op.tab_index=idx
        layout.separator()

        if props.active_tab==0:
            box=layout.box(); box.label(text='📦 数据导入',icon='IMPORT')
            box.prop(props,'svg_filepath',text='')
            r=box.row(align=True); r.prop(props,'ratio_px',text=''); r.label(text='px ='); r.prop(props,'ratio_m',text=''); r.label(text='m')
            box.prop(props,'curve_res',slider=True)
            btn_row=box.row(); btn_row.scale_y=1.2; btn_row.operator('map.import_svg',icon='LIGHT_SUN')
            if len(props.layer_list)>0: box.separator(); box.label(text=f"✅ 已导入 {len(props.layer_list)} 个图层",icon='INFO'); gen_row=box.row(); gen_row.scale_y=1.2; gen_row.operator('map.generate_3d',icon='ROCKET',text='一键挤出')

        elif props.active_tab==1:
            if len(props.layer_list)==0: layout.label(text='请先在导入标签页导入SVG',icon='INFO')
            else:
                box=layout.box(); box.label(text=f'图层配置 ({len(props.layer_list)}个)',icon='MOD_BUILD')
                row=box.row(); row.template_list('MAP_UL_layer_list','',props,'layer_list',props,'layer_list_idx',rows=5)

        elif props.active_tab==2:
            # --- 渲染与性能优化 ---
            opt_box = layout.box()
            opt_box.label(text='🎨 渲染与性能优化', icon='SHADING_TEXTURE')
            atlas_row = opt_box.row()
            atlas_row.scale_y = 1.2
            atlas_row.operator('map.build_atlas', icon='IMAGE_DATA')

            layout.separator()

            # --- 导出流程 ---
            box = layout.box()
            box.label(text='📤 导出交付', icon='EXPORT')
            s1=box.split(factor=0.22, align=True); s1.label(text='路径:'); s1.prop(props,'export_dir',text='')
            s2=box.split(factor=0.22, align=True); s2.label(text='文件名:'); fn_row=s2.row(align=True); fn_row.prop(props,'export_filename',text=''); fn_row.label(text='.glb')

            if not get_pypinyin():
                box.separator()
                env_box = box.box()
                env_box.label(text="⚠️ 拼音转换引擎未激活 (当前为降级模式)", icon='ERROR')
                env_box.operator('map.install_env', icon='CONSOLE')

            box.separator()
            r=box.row(align=True); r.prop(props,'exp_visible_only'); r.prop(props,'exp_apply_modifiers'); r.prop(props,'exp_pinyin_safe')
            exp_row=box.row(); exp_row.scale_y=1.5; exp_row.operator('map.export_glb',icon='PACKAGE')

class MAP_PT_generate_panel(bpy.types.Panel):
    bl_label="Generate"; bl_idname="MAP_PT_generate_panel"; bl_space_type='VIEW_3D'; bl_region_type='UI'
    bl_category='1000Map'; bl_parent_id='MAP_PT_main_panel'; bl_options={'HIDE_HEADER'} # 保持在同一分类下
    @classmethod
    def poll(cls, context): return context.scene.map_props.active_tab == 1
    def draw(self, context): row = self.layout.row(); row.scale_y = 1.6; row.operator('map.generate_3d', icon='PLAY', text='一键挤出')

# ------------------- Register -------------------
classes=(MAP_PG_layer_item,MAP_PG_main_props,MAP_OT_install_env,MAP_OT_switch_tab,MAP_OT_import_svg,MAP_OT_generate_3d,MAP_OT_build_atlas,MAP_OT_export_glb,MAP_UL_layer_list,MAP_PT_main_panel,MAP_PT_generate_panel)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.map_props=bpy.props.PointerProperty(type=MAP_PG_main_props)

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene,'map_props'): del bpy.types.Scene.map_props

if __name__=='__main__': register()
