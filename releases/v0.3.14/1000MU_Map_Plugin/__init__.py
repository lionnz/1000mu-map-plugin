bl_info = {
    "name": "1000MU 3D周边地图插件 Figma to Blender",
    "author": "Design Team",
    "version": (0, 3, 14),
    "blender": (4, 2, 0),
    "location": "View3D > N Panel > 1000Map",
    "description": "v0.3.14: 内置 pypinyin 拼音引擎，移除网络安装依赖。兼容 Blender 4.2-4.5。",
    "category": "3D View",
}

# v0.3.14 变更摘要（融合 v0.3.9–v0.3.13 所有优化）
#   1. 内置 pypinyin 拼音引擎，无需联网安装，开箱即用
#   2. 兼容 Blender 4.5：material.shadow_method 改为 hasattr 检测
#   3. 偏好设置可配置高度预设表（v0.3.12）
#   4. 色块贴图：支持单物体多材质球（v0.3.9）、冗余槽自动合并（v0.3.10）、回归修复（v0.3.11）
#   5. 法线统一隔离、非递归孤立清理、epsilon 防抖、md5 防重名、tempfile 隔离（v0.3.9）
#   6. 随机高度开启时自动填充区间、UI 布局优化、description 悬浮提示（v0.3.13）

import sys
import os

# 将 vendored pypinyin 加入 sys.path，优先于系统安装的版本
_vendor_dir = os.path.join(os.path.dirname(__file__), 'vendor')
if os.path.isdir(_vendor_dir) and _vendor_dir not in sys.path:
    sys.path.insert(0, _vendor_dir)

import bpy
import bmesh
import random
import xml.etree.ElementTree as ET
import urllib.parse
import re
import hashlib
import tempfile

# ── 内置拼音引擎（v0.3.14 vendored pypinyin）──────────────────────
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
    return 'layer_' + hashlib.md5(s.encode('utf-8')).hexdigest()[:8]

INVALID_LAYER_NAMES = {'svg','g','path','rect','circle','ellipse','polygon','polyline','line','layer','group','root','vector'}

BUILTIN_HEIGHT_PRESETS = [
    ("绿化", 10.0),
    ("主路", 20.0),
    ("支路", 15.0),
    ("中色box", 40.0),
    ("浅色box", 50.0),
    ("深色box", 30.0),
    ("文字", 0.5),
    ("商场边框", 60.0),
    ("商场", 80.0),
    ("水", 5.0),
]

ADDON_MODULE = __name__

def get_height_presets(context):
    try:
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        if prefs and prefs.height_presets:
            return [(p.keyword, p.height) for p in prefs.height_presets if p.keyword]
    except Exception as e:
        print(f"[1000Map] 读取偏好设置预设失败，降级使用内置默认值: {e}")
    return list(BUILTIN_HEIGHT_PRESETS)

def force_normals_up(obj, epsilon=1e-5):
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

def _on_use_rand_height(self, context):
    if self.use_rand_height and self.height > 0:
        self.rand_height_min = round(self.height * 0.5, 2)
        self.rand_height_max = round(self.height * 1.5, 2)

class MAP_PG_layer_item(bpy.types.PropertyGroup):
    is_active: bpy.props.BoolProperty(name="启用", default=True,
        description="取消勾选后，该图层将不参与挤出和导出")
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
    export_dir: bpy.props.StringProperty(name="导出目录", subtype='DIR_PATH', default=os.path.expanduser("~/Downloads") + os.sep,
        description="GLB文件的导出目标目录")
    export_filename: bpy.props.StringProperty(name="文件名", default="3d_map",
        description="导出的GLB文件名（无需加 .glb 后缀）")
    exp_visible_only: bpy.props.BoolProperty(name="仅导出可见", default=True,
        description="开启后仅导出视口中可见的物体，隐藏物体将被忽略")
    exp_apply_modifiers: bpy.props.BoolProperty(name="应用修改器", default=True,
        description="导出前自动应用挤出、焊接等修改器，确保GLB包含最终形态")
    exp_pinyin_safe: bpy.props.BoolProperty(name="拼音防呆", default=True, description="导出时静默去中文，防前端报错")
    active_tab: bpy.props.IntProperty(default=0)

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

class MAP_OT_switch_tab(bpy.types.Operator):
    bl_idname = "map.switch_tab"; bl_label = "切换标签"
    bl_description = "切换插件的功能标签页"
    tab_index: bpy.props.IntProperty(default=0)
    def execute(self,context): context.scene.map_props.active_tab = self.tab_index; return {'FINISHED'}

class MAP_OT_import_svg(bpy.types.Operator):
    bl_idname = "map.import_svg"
    bl_label = "导入并重构空间"
    bl_description = "导入SVG地图，自动换算物理尺寸并转换为3D网格平面"

    def execute(self, context):
        props = context.scene.map_props
        input_file = bpy.path.abspath(props.svg_filepath)
        if not os.path.exists(input_file) or not input_file.lower().endswith('.svg'):
            self.report({'ERROR'}, "请选择有效的SVG文件！"); return {'CANCELLED'}

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
            for kw, h in get_height_presets(context):
                if kw and kw in base:
                    item.height = h
                    matched = True; break
            if not matched: item.height = float(random.randint(1, 10))

            color_hit = svg_colors.get(base)
            if color_hit: item.color = color_hit

        self.report({'INFO'},f"导入成功！共 {len(props.layer_list)} 个图层，请在「配置」标签页设置高度与颜色")
        return {'FINISHED'}

class MAP_OT_generate_3d(bpy.types.Operator):
    bl_idname = "map.generate_3d"
    bl_label = "一键挤出"
    bl_description = "按图层配置的高度和颜色执行3D挤出，自动修正法线方向并赋予基础材质"

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

                bsdf.inputs['Base Color'].default_value = color
                bsdf.inputs['Alpha'].default_value = color[3]
                bsdf.inputs['Roughness'].default_value = 0.2 if color[3] < 1.0 else 0.8

                if color[3] < 1.0:
                    mat.blend_method = 'BLEND'
                    if hasattr(mat, 'shadow_method'):
                        mat.shadow_method = 'NONE'

                links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

                def linear_to_srgb(c):
                    c = max(0.0, min(1.0, c))
                    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0/2.4)) - 0.055
                mat.diffuse_color = (linear_to_srgb(color[0]), linear_to_srgb(color[1]), linear_to_srgb(color[2]), color[3])
            else: mat = bpy.data.materials[matname]

            obj.data.materials.clear(); obj.data.materials.append(mat)
            count += 1

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

        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=False)
        self.report({'INFO'}, "挤出完成！请在「导出」标签页生成色块贴图并导出GLB")
        return {'FINISHED'}

class MAP_OT_build_atlas(bpy.types.Operator):
    bl_idname = "map.build_atlas"
    bl_label = "生成色块贴图"
    bl_description = "按材质颜色生成全局色块贴图，自动合并相同材质以优化渲染性能"
    BLOCK = 64

    def execute(self, context):
        import math
        mesh_objs = [o for o in context.scene.objects if o.type == 'MESH' and not o.hide_viewport]
        if not mesh_objs: self.report({'ERROR'}, "场景中没有可见网格！"); return {'CANCELLED'}

        def linear_to_srgb(c):
            c = max(0.0, min(1.0, c))
            return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055

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

        self.report({'INFO'}, f"⚡ 双轨制图集生成完成 (按材质聚合，自动合并冗余槽)！")
        return {'FINISHED'}

class MAP_OT_export_glb(bpy.types.Operator):
    bl_idname = "map.export_glb"
    bl_label = "导出GLB"
    bl_description = "一键导出符合 WebGL 标准的 .glb 模型（内置拼音引擎，防前端报错）"

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

class MAP_PG_height_preset(bpy.types.PropertyGroup):
    keyword: bpy.props.StringProperty(
        name="关键词", default="新图层",
        description="图层名包含此关键词即命中预设高度"
    )
    height: bpy.props.FloatProperty(
        name="高度(m)", default=10.0, min=0.0, step=10,
        description="匹配该关键词的图层默认挤出高度（米）"
    )

class MAP_UL_prefs_presets(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.prop(item, 'keyword', text='', emboss=True)
        row.prop(item, 'height', text='')

class MAP_OT_add_preset(bpy.types.Operator):
    bl_idname = "map.add_preset"
    bl_label = "添加预设"
    bl_description = "添加一行新的高度预设"
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        item = prefs.height_presets.add()
        item.keyword = "新图层"
        item.height = 10.0
        prefs.active_preset_idx = len(prefs.height_presets) - 1
        return {'FINISHED'}

class MAP_OT_del_preset(bpy.types.Operator):
    bl_idname = "map.del_preset"
    bl_label = "删除预设"
    bl_description = "删除当前选中的高度预设"
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        idx = prefs.active_preset_idx
        if 0 <= idx < len(prefs.height_presets):
            prefs.height_presets.remove(idx)
            prefs.active_preset_idx = max(0, min(idx, len(prefs.height_presets) - 1))
        return {'FINISHED'}

class MAP_OT_reset_presets(bpy.types.Operator):
    bl_idname = "map.reset_presets"
    bl_label = "恢复内置默认值"
    bl_description = "清空当前预设，恢复为插件内置的 10 条默认预设"
    def execute(self, context):
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        prefs.height_presets.clear()
        for kw, h in BUILTIN_HEIGHT_PRESETS:
            item = prefs.height_presets.add()
            item.keyword = kw
            item.height = h
        prefs.active_preset_idx = 0
        self.report({'INFO'}, f"已恢复 {len(BUILTIN_HEIGHT_PRESETS)} 条内置默认预设")
        return {'FINISHED'}

class MAP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_MODULE

    height_presets: bpy.props.CollectionProperty(type=MAP_PG_height_preset)
    active_preset_idx: bpy.props.IntProperty(default=0)

    def draw(self, context):
        layout = self.layout
        layout.label(text="默认高度预设表（图层名包含关键词即命中）", icon='PRESET')

        row = layout.row()
        row.template_list(
            'MAP_UL_prefs_presets', '',
            self, 'height_presets',
            self, 'active_preset_idx',
            rows=10
        )

        col = row.column(align=True)
        col.operator('map.add_preset', icon='ADD', text='')
        col.operator('map.del_preset', icon='REMOVE', text='')

        layout.separator()
        layout.operator('map.reset_presets', icon='FILE_REFRESH', text='恢复内置默认值')

        layout.separator()
        box = layout.box()
        box.label(text="使用说明", icon='INFO')
        box.label(text="• 关键词「包含」匹配：图层名只要包含关键词即命中")
        box.label(text="  例如：「主路-辅道」匹配关键词「主路」")
        box.label(text="• 多个关键词同时命中时，按上表顺序优先匹配第一个")
        box.label(text="• 未命中任何关键词的图层，自动取 1–10m 随机高度")
        box.label(text="• 预设保存在用户设置中，所有工程文件共享")

class MAP_UL_layer_list(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        split = layout.split(factor=0.08)
        split.prop(item, 'is_active', text='', icon='HIDE_OFF' if item.is_active else 'HIDE_ON', toggle=True)
        right = split.row()
        s_name = right.split(factor=0.261)
        name_row = s_name.row()
        name_row.prop(item, 'layer_name', text='', emboss=False)
        rest = s_name.row()
        rest_align = rest.row(align=True)
        values_row = rest_align.row(align=True)
        values_row.prop(item, 'use_rand_height', text='', icon='SHADERFX', toggle=True)
        if item.use_rand_height:
            r_min = values_row.row(align=True)
            r_min.prop(item, 'rand_height_min', text='')
            r_max = values_row.row(align=True)
            r_max.prop(item, 'rand_height_max', text='')
        else:
            values_row.prop(item, 'height', text='')
        color_row = rest_align.row()
        color_row.scale_x = 0.31
        color_row.prop(item, 'color', text='')

class MAP_PT_main_panel(bpy.types.Panel):
    bl_label="1000MU 3D周边地图插件"
    bl_idname="MAP_PT_main_panel"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='1000Map'
    def draw(self,context):
        props=context.scene.map_props; layout=self.layout
        row=layout.row(align=True)
        for idx,text in enumerate(['导入','配置','导出']):
            op=row.operator('map.switch_tab',text=text,depress=(props.active_tab==idx)); op.tab_index=idx
        layout.separator()

        if props.active_tab==0:
            box1 = layout.box()
            box1.label(text='数据导入',icon='IMPORT')
            box1.prop(props,'svg_filepath',text='')

            layout.separator()

            box2 = layout.box()
            box2.label(text='比例换算',icon='CON_SIZELIKE')
            row = box2.row(align=True)

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
            box2.separator()
            box2.label(text='曲线精度',icon='CURVE_DATA')
            box2.prop(props,'curve_res',slider=True)

            layout.separator()

            box3 = layout.box()
            btn_row=box3.row(); btn_row.scale_y=1.2; btn_row.operator('map.import_svg',icon='LIGHT_SUN')
            if len(props.layer_list)>0: box3.separator(); box3.label(text=f"已导入 {len(props.layer_list)} 个图层",icon='INFO'); gen_row=box3.row(); gen_row.scale_y=1.2; gen_row.operator('map.generate_3d',icon='ROCKET',text='一键挤出')

        elif props.active_tab==1:
            if len(props.layer_list)==0: layout.label(text='请先在「导入」标签页导入SVG',icon='INFO')
            else:
                box=layout.box(); box.label(text=f'图层配置 ({len(props.layer_list)}个)',icon='MOD_BUILD')
                row=box.row(); row.template_list('MAP_UL_layer_list','',props,'layer_list',props,'layer_list_idx',rows=max(5, min(len(props.layer_list), 10)))
                layout.separator()
                gen_row=layout.row(); gen_row.scale_y=1.6; gen_row.operator('map.generate_3d',icon='PLAY',text='一键挤出')

        elif props.active_tab==2:
            opt_box = layout.box()
            opt_box.label(text='渲染与性能优化', icon='SHADING_TEXTURE')
            atlas_row = opt_box.row()
            atlas_row.scale_y = 1.2
            atlas_row.operator('map.build_atlas', icon='IMAGE_DATA')

            layout.separator()

            box = layout.box()
            box.label(text='导出交付', icon='EXPORT')

            row1 = box.row(align=True)
            split1 = row1.split(factor=0.15)
            split1.label(text='路径:')
            split1.prop(props,'export_dir',text='')

            row2 = box.row(align=True)
            split2 = row2.split(factor=0.15)
            split2.label(text='文件名:')
            fn_row = split2.row(align=True)
            fn_row.prop(props,'export_filename',text='')
            fn_row.label(text='.glb')

            box.separator()
            r=box.row(align=True); r.prop(props,'exp_visible_only'); r.prop(props,'exp_apply_modifiers'); r.prop(props,'exp_pinyin_safe')
            exp_row=box.row(); exp_row.scale_y=1.5; exp_row.operator('map.export_glb',icon='PACKAGE')

classes=(
    MAP_PG_layer_item,
    MAP_PG_main_props,
    MAP_PG_height_preset,
    MAP_OT_switch_tab,
    MAP_OT_import_svg,
    MAP_OT_generate_3d,
    MAP_OT_build_atlas,
    MAP_OT_export_glb,
    MAP_OT_add_preset,
    MAP_OT_del_preset,
    MAP_OT_reset_presets,
    MAP_UL_layer_list,
    MAP_UL_prefs_presets,
    MAP_PT_main_panel,
    MAP_AddonPreferences,
)

def register():
    for cls in classes: bpy.utils.register_class(cls)
    bpy.types.Scene.map_props=bpy.props.PointerProperty(type=MAP_PG_main_props)

    try:
        prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
        if prefs is not None and len(prefs.height_presets) == 0:
            for kw, h in BUILTIN_HEIGHT_PRESETS:
                item = prefs.height_presets.add()
                item.keyword = kw
                item.height = h
    except Exception as e:
        print(f"[1000Map] 填充默认预设失败（可手动点击「恢复内置默认值」）: {e}")

def unregister():
    for cls in reversed(classes): bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene,'map_props'): del bpy.types.Scene.map_props

if __name__=='__main__': register()
