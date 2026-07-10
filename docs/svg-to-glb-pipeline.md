# AI 使用 1000MU 3D MAP 插件的导出流程

本文件供 AI 读取，用于在 Blender 4.2+ 中通过「1000MU 3D MAP 插件」将 SVG 矢量地图转换为 3D GLB 模型。

---

## 一、前置确认（必须先与用户确认）

当用户要求 AI 直接使用某个 `.svg` 文件生成 3D map 时，AI **必须先确认以下 3 项关键补充信息**，不可自行假设默认值：

| 确认项 | 对应插件属性 | 说明 |
|--------|-------------|------|
| **像素转换物理单位** | `ratio_px` + `ratio_m` | SVG 中的像素与实际距离的换算关系。需问用户：「SVG 中多少像素对应实际多少米？」例如「10px = 1m」。 |
| **曲线精度** | `curve_res` | 曲线转网格的采样精度（1~12）。数值越高边缘越平滑，但面数更多。需问用户是否有特殊要求，无则用默认值 4。 |
| **导出位置** | GLB 文件保存路径 | 需问用户：「GLB 导出到哪个目录？文件名是什么？」必须使用绝对路径。 |

**确认话术示例：**

> 我可以使用 1000MU 3D MAP 插件将该 SVG 转换为 3D 地图模型。开始前需要确认 3 点：
> 1. 像素转换物理单位：SVG 中多少像素对应实际多少米？（例如 10px = 1m）
> 2. 曲线精度：默认 4，是否需要调整？（1~12，越高越平滑）
> 3. GLB 导出到哪个路径？（请提供完整路径，如 `/path/to/output.glb`）

---

## 二、环境准备

### 2.1 启动 Blender（后台模式）

```bash
"/Applications/Blender 4.2 LTS.app/Contents/MacOS/Blender" --background --python-expr "<脚本>"
```

### 2.2 加载插件

```python
import bpy, sys

# 禁用已加载的旧版本，清除模块缓存，确保使用最新代码
if '1000MU_Map_Plugin' in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_disable(module='1000MU_Map_Plugin')
for k in list(sys.modules):
    if k.startswith('1000MU_Map_Plugin'):
        del sys.modules[k]
bpy.ops.preferences.addon_enable(module='1000MU_Map_Plugin')
```

> 注意：如果修改了插件源码，需同步到 Blender 安装目录：
> `~/Library/Application Support/Blender/4.2/scripts/addons/1000MU_Map_Plugin/`

---

## 三、主流程：SVG → 3D Map GLB

### 步骤 1：设置参数 + 导入 SVG

```python
props = bpy.context.scene.map_props

# 设置用户确认的参数
props.svg_filepath = '/path/to/input.svg'   # SVG 文件绝对路径
props.ratio_px = 10.0                        # 像素值（用户确认）
props.ratio_m = 1.0                          # 对应的实际米数（用户确认）
props.curve_res = 4                          # 曲线精度（用户确认，默认4）

# 执行导入
bpy.ops.map.import_svg()
```

**导入做了什么：**
- 解析 SVG 颜色，存储到 `context.scene['map_svg_colors']`
- 用 `bpy.ops.import_curve.svg` 导入曲线
- 按比例缩放、居中
- 几何节点 FillCurve 填充曲线 → 转网格
- 从 SVG 颜色直接创建 `Mat_{图层名}` 标准材质（Principled BSDF + diffuse_color）并分配给网格

**导入后检查：**
```python
meshes = [o for o in bpy.data.objects if o.type == 'MESH']
print(f'导入网格数: {len(meshes)}')
has_mat = sum(1 for m in meshes if len(m.data.materials) > 0)
print(f'有材质: {has_mat}/{len(meshes)}')  # 应全部有材质
```

### 步骤 2：刷新图层列表

```python
# 全选导入的网格
bpy.ops.object.select_all(action='DESELECT')
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]

# 执行刷新
bpy.ops.map.refresh_layer_list()
```

**刷新做了什么：**
- 按基础名（去掉 `.001` `.002` 后缀）去重生成图层列表
- 自动匹配内置高度预设（见下表），未匹配的随机 1~10m
- 从 `map_svg_colors` 读取颜色填入图层

**内置高度预设（constants.py）：**

| 图层关键词 | 高度(m) |
|-----------|---------|
| 绿化 | 10.0 |
| 主路 | 20.0 |
| 支路 | 15.0 |
| 中色box | 40.0 |
| 浅色box | 50.0 |
| 深色box | 30.0 |
| 文字 | 0.5 |
| 商场边框 | 60.0 |
| 商场 | 80.0 |
| 水 | 5.0 |

**查看/修改图层配置：**
```python
props = bpy.context.scene.map_props
for item in props.layer_list:
    print(f'{item.layer_name}: height={item.height}, color={list(item.color)}')

# 可修改高度或颜色
# props.layer_list[0].height = 15.0
# props.layer_list[0].color = (0.9, 0.1, 0.1, 1.0)  # RGBA 线性值
```

### 步骤 3：一键挤出

```python
bpy.ops.map.generate_3d()
```

**挤出做了什么：**
- 对每个网格添加 Solidify（挤出）+ Weld（焊接）+ Triangulate（三角化）修改器
- 用图层配置的高度挤出，颜色更新到材质（始终覆盖，支持用户改色）
- 修正法线方向朝上
- 清理孤立数据

### 步骤 4：生成色块贴图

```python
bpy.ops.map.build_atlas()
```

**生成色块贴图做了什么：**
- 按材质颜色聚合，生成全局色块贴图 `3DMap_ColorAtlas`
- 创建两个图集材质：`Mat_3DMap_Atlas_Opaque`（不透明）、`Mat_3DMap_Atlas_Transparent`（透明）
- 为每个网格的 UV 重映射到对应色块，替换材质槽为图集材质

### 步骤 5：导出 GLB

#### 后台模式（AI 自动化用）

后台模式无法使用插件的 `map.export_glb`（它用 `INVOKE_DEFAULT` 弹窗 + timer 还原名称），需直接调用 glTF 导出，并**手动实现拼音防呆**（改名 → 导出 → 同步还原名称）：

```python
import os, importlib

glb_path = '/path/to/output.glb'  # 用户确认的导出路径
if os.path.exists(glb_path):
    os.remove(glb_path)

# 全选所有网格
bpy.ops.object.select_all(action='DESELECT')
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]

# 拼音防呆：导出前中文名转拼音，导出后同步还原（后台模式不能用 timer）
# 复用插件的 chinese_to_safe_name 函数
_utils = importlib.import_module('1000MU_Map_Plugin.utils')
chinese_to_safe_name = _utils.chinese_to_safe_name

obj_restore = {}
mat_restore = {}
for o in meshes:
    obj_restore[o] = (o.name, o.data.name if o.data else None)
    new_name = chinese_to_safe_name(o.name)
    o.name = new_name
    if o.data:
        o.data.name = new_name
for o in meshes:
    for slot in o.material_slots:
        if slot.material and slot.material not in mat_restore:
            mat_restore[slot.material] = slot.material.name
            slot.material.name = 'Mat_' + chinese_to_safe_name(slot.material.name.removeprefix('Mat_'))

# 导出 GLB
bpy.ops.export_scene.gltf(
    filepath=glb_path,
    export_format='GLB',
    use_visible=True,        # 仅导出可见
    export_apply=True,       # 应用修改器
)

# 同步还原名称（后台模式无 timer，直接还原）
for o, (obj_name, data_name) in obj_restore.items():
    o.name = obj_name
    if o.data and data_name:
        o.data.name = data_name
for mat, orig_name in mat_restore.items():
    mat.name = orig_name

# 验证
if os.path.exists(glb_path):
    size_kb = os.path.getsize(glb_path) / 1024
    print(f'GLB 导出成功: {glb_path}, 大小={size_kb:.1f}KB')
else:
    print('GLB 导出失败!')
```

#### 前台模式（用户交互用）

```python
# 插件原生的导出按钮（弹窗，支持拼音防呆）
bpy.ops.map.export_glb()
```

插件导出属性：
- `props.exp_visible_only`：仅导出可见（默认 True）
- `props.exp_apply_modifiers`：应用修改器（默认 True）
- `props.exp_pinyin_safe`：拼音防呆（默认 True，导出时中文转拼音防前端报错）

---

## 四、完整流程脚本模板

```python
import bpy, sys, os, importlib

# === 环境准备 ===
if '1000MU_Map_Plugin' in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_disable(module='1000MU_Map_Plugin')
for k in list(sys.modules):
    if k.startswith('1000MU_Map_Plugin'):
        del sys.modules[k]
bpy.ops.preferences.addon_enable(module='1000MU_Map_Plugin')

# === 用户确认的参数 ===
svg_path = '/path/to/input.svg'        # 【需确认】SVG 文件路径
glb_path = '/path/to/output.glb'       # 【需确认】GLB 导出路径
ratio_px = 10.0                         # 【需确认】像素值
ratio_m = 1.0                           # 【需确认】对应米数
curve_res = 4                           # 【需确认】曲线精度（默认4）

# === 主流程 ===
props = bpy.context.scene.map_props
props.svg_filepath = svg_path
props.ratio_px = ratio_px
props.ratio_m = ratio_m
props.curve_res = curve_res

# 1. 导入 SVG
bpy.ops.map.import_svg()
meshes = [o for o in bpy.data.objects if o.type == 'MESH']

# 2. 刷新图层列表
bpy.ops.object.select_all(action='DESELECT')
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.map.refresh_layer_list()

# 3. 一键挤出
bpy.ops.map.generate_3d()

# 4. 生成色块贴图
bpy.ops.map.build_atlas()

# 5. 导出 GLB（含拼音防呆：改名 → 导出 → 同步还原）
if os.path.exists(glb_path):
    os.remove(glb_path)
bpy.ops.object.select_all(action='DESELECT')
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]

# 拼音防呆：复用插件的 chinese_to_safe_name 函数
_utils = importlib.import_module('1000MU_Map_Plugin.utils')
chinese_to_safe_name = _utils.chinese_to_safe_name

obj_restore = {}
mat_restore = {}
for o in meshes:
    obj_restore[o] = (o.name, o.data.name if o.data else None)
    new_name = chinese_to_safe_name(o.name)
    o.name = new_name
    if o.data:
        o.data.name = new_name
for o in meshes:
    for slot in o.material_slots:
        if slot.material and slot.material not in mat_restore:
            mat_restore[slot.material] = slot.material.name
            slot.material.name = 'Mat_' + chinese_to_safe_name(slot.material.name.removeprefix('Mat_'))

bpy.ops.export_scene.gltf(
    filepath=glb_path,
    export_format='GLB',
    use_visible=True,
    export_apply=True,
)

# 同步还原名称
for o, (obj_name, data_name) in obj_restore.items():
    o.name = obj_name
    if o.data and data_name:
        o.data.name = data_name
for mat, orig_name in mat_restore.items():
    mat.name = orig_name

# === 验证 ===
if os.path.exists(glb_path):
    print(f'成功: {glb_path} ({os.path.getsize(glb_path)/1024:.1f}KB)')
else:
    print('失败: GLB 未生成')
```

---

## 五、独立小工具（不在主流程中，按需单独调用）

以下三个工具位于插件「导出」标签页的「实用小工具」区域，**不在 SVG to 3D 的主流程中**，需单独测试或使用。

### 5.1 UVmap 批量清理

```python
# 选中网格后执行
bpy.ops.object.select_all(action='DESELECT')
for m in target_meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = target_meshes[0]
bpy.ops.map.clean_uvmap()
```

**作用：** 确保每个网格有且仅有一个名为 `UVMap` 的 UV 层。多 UV 时保留活动层、删除其余并改名。

### 5.2 自定义法向批量清理

```python
# 选中网格后执行（modal + timer，前台正常，后台不触发 timer）
bpy.ops.map.clear_split_normals()
```

**作用：** 批量移除选中网格的自定义拆边法向数据。

> 后台模式注意：此操作符使用 modal+timer 机制，后台模式不处理 timer 事件。AI 在后台模式需直接调用底层 API：
> ```python
> for m in target_meshes:
>     bpy.context.view_layer.objects.active = m
>     if m.data.has_custom_normals:
>         bpy.ops.mesh.customdata_custom_splitnormals_clear()
> ```

### 5.3 按所选面批量设置原点

```python
# 必须在编辑模式下，选中面后执行
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
# ... 用 bmesh 选中目标面 ...
bpy.ops.map.set_origin_to_face()
```

**作用：** 将每个网格的原点设置到其选中面的中心，旋转对齐完整面坐标系（X=切线, Y=法向×切线, Z=法向）。

---

## 六、关键参数说明

| 参数 | 属性路径 | 类型 | 默认值 | 说明 |
|------|---------|------|--------|------|
| SVG 文件 | `props.svg_filepath` | String | - | SVG 文件绝对路径 |
| 像素值 | `props.ratio_px` | Float | 10.0 | SVG 中像素对应的参考尺寸 |
| 米数 | `props.ratio_m` | Float | 1.0 | 上述像素对应的实际距离（米） |
| 曲线精度 | `props.curve_res` | Int | 4 | 曲线转网格采样精度（1~12） |
| 仅导出可见 | `props.exp_visible_only` | Bool | True | 仅导出视口可见物体 |
| 应用修改器 | `props.exp_apply_modifiers` | Bool | True | 导出前应用修改器 |
| 拼音防呆 | `props.exp_pinyin_safe` | Bool | True | 导出时中文转拼音 |

**比例换算公式：** `scale_factor = 3543.0 * (ratio_m / ratio_px)`
