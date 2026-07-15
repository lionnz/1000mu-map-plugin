import re, hashlib, urllib.parse, os, xml.etree.ElementTree as ET
import bpy, bmesh

from .constants import INVALID_LAYER_NAMES, BUILTIN_HEIGHT_PRESETS, ADDON_MODULE

# 安全：限制 SVG 文件大小，防止 XML 实体扩展攻击（Billion Laughs）导致内存耗尽
MAX_SVG_SIZE = 50 * 1024 * 1024  # 50MB 上限

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
    # 安全：检查文件大小，防止 XML 实体扩展攻击（Billion Laughs）导致内存耗尽
    try:
        if os.path.getsize(svg_path) > MAX_SVG_SIZE:
            print(f"[1000Map] SVG 文件过大（>{MAX_SVG_SIZE//1024//1024}MB），可能存在安全风险，已跳过解析")
            return colors
    except OSError as e:
        print(f"[1000Map] SVG 文件大小检查失败: {e}")
        return colors
    try: tree = ET.parse(svg_path); root = tree.getroot()
    except (ET.ParseError, OSError) as e:
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
            if raw_id and current_layer is None:
                decoded = decode_figma_id(raw_id)
                if decoded and decoded.lower() not in INVALID_LAYER_NAMES: current_layer = decoded
        for child in el: traverse(child, current_layer)

    root_g = [c for c in root if c.tag.split('}')[-1] == 'g']
    if len(root_g) == 1:
        for child in root_g[0]:
            traverse(child, None)
    else:
        for child in root:
            traverse(child, None)
    return colors

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

def get_height_presets(context):
    try:
        prefs = context.preferences.addons[ADDON_MODULE].preferences
        if prefs and prefs.height_presets:
            return [(p.keyword, p.height) for p in prefs.height_presets if p.keyword]
    except Exception as e:
        print(f"[1000Map] 读取偏好设置预设失败，降级使用内置默认值: {e}")
    return list(BUILTIN_HEIGHT_PRESETS)

def _on_use_rand_height(self, context):
    if self.use_rand_height and self.height > 0:
        self.rand_height_min = round(self.height * 0.5, 2)
        self.rand_height_max = round(self.height * 1.5, 2)

def linear_to_srgb(c):
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0/2.4)) - 0.055
