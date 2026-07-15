# AI 使用 1000MU 3D MAP 插件的导出流程

本文件供 AI 读取，用于在 Blender 4.2+ 中通过「1000MU 3D MAP 插件」将 SVG 矢量地图转换为 3D GLB 模型。

---

> ## ⛔ 致命警告：禁止使用默认参数值直接执行
>
> **`ratio_px` 和 `ratio_m` 是控制整个模型物理比例的核心参数。**
>
> - 代码示例中的 `ratio_px=10.0, ratio_m=1.0` 是**占位符**，不是合理默认值
> - 不同 SVG 的像素跨度差异巨大（可能是 100px 也可能是 100000px），`10px=1m` 的默认值几乎必定导致模型尺寸严重错误
> - **每个 SVG 都有自己正确的 px→m 换算关系**，这是只有用户知道的业务信息，AI 不可能自行推算
> - 如果用户没有提供像素转物理单位，**必须停止流程并追问**，而不是使用占位符值直接执行
> - 用错了比例 = 整个模型作废，GLB 文件毫无意义
>
> **`curve_res` 影响模型精度和面数：**
> - 默认值 4 对大多数场景是合理的折中，但仍应确认用户是否有特殊要求

---

## 一、前置确认（⚡ 强制步骤，禁止跳过）

<font color="red">**此步骤不是"建议"，是强制性要求。确认完成后才能进入后续流程。**</font>

当用户要求 AI 使用某个 `.svg` 文件生成 3D map 时，AI **必须先确认以下 3 项关键补充信息**。如果用户没有提供其中任何一项，AI 必须使用 `AskUserQuestion` 工具主动询问，**禁止使用文档中的示例值或默认值直接执行**：

| 确认项 | 对应插件属性 | 严重程度 | 说明 |
|--------|-------------|---------|------|
| **像素转换物理单位** | `ratio_px` + `ratio_m` | 🔴 **致命** | SVG 中的像素与实际距离的换算关系。必须问用户：「SVG 中多少像素对应实际多少米？」例如 `100px = 10m`。**此参数无通用默认值，每个 SVG 都不同。** |
| **曲线精度** | `curve_res` | 🟡 重要 | 曲线转网格的采样精度（1~12）。数值越高边缘越平滑，但面数更多。需问用户是否有特殊要求，无则使用默认值 4。 |
| **导出位置** | GLB 文件保存路径 | 🔴 **致命** | 必须使用绝对路径。需问用户：「GLB 导出到哪个目录？文件名是什么？」 |

### 为什么像素转物理单位不能有默认值？

SVG 的视口（viewBox）尺寸取决于设计工具导出时的画布设置。例如：
- 一张规划总图的导出画布可能是 5000×3000 px，对应实际 500×300 m
- 一张区域详图可能是 800×600 px，对应实际 80×60 m
- 两个场景的正确 `ratio_px / ratio_m` 完全不同

**插件内部换算公式：** `scale_factor = 3543.0 * (ratio_m / ratio_px)`

### 确认话术（第一步：导入前确认）

> 开始将 SVG 转换为 3D 地图模型前，需要确认以下关键参数：
> 1. **像素转物理单位**（必须）：SVG 中多少 px 对应实际多少 m？例如你上次用 `100px = 10m`
> 2. **曲线精度**：默认 4，是否需要调整？（1~12，越高边缘越平滑但面数更多）
> 3. **GLB 导出路径**（必须）：请提供完整绝对路径

### 确认话术（第二步：刷新图层列表后确认随机高度）

刷新图层列表后，将读取到的图层名列表展示给用户，询问是否需要开启某些图层的随机高度：

> 以下是刷新到的 **N 个图层** 及其预设高度：
> | 图层名 | 高度(m) |
> |--------|---------|
> | 绿化 | 10 |
> | 中色box | 40 |
> | ... | ... |
>
> 是否需要为某些图层开启**随机高度**？
> - 开启后，每个该图层的物体在挤出时会随机分配高度（区间 = 基础高度 × 0.5 ~ 基础高度 × 1.5），产生错落感
> - 例如：中色box 基础高度 40m，随机区间为 20~60m
> - 如果不需要，直接回复"不需要"
> - 如果需要，请告知哪些图层要开启随机高度

### 随机高度算法（插件内置，了解即可）

开启 `use_rand_height` 时，插件自动计算：[utils.py `_on_use_rand_height`](file:///Users/liuhao/works/TRAE/trae0707/1000mu-map-plugin/src/1000MU_Map_Plugin/utils.py#L144-L146)

```
rand_height_min = 基础高度 × 0.5
rand_height_max = 基础高度 × 1.5
```

用户也可在脚本中手动覆盖 `rand_height_min` / `rand_height_max` 自定义区间。

### 禁止行为

<font color="red">以下行为会导致生成**完全错误的模型**，必须避免：</font>

| ❌ 禁止行为 | 后果 | 正确做法 |
|------------|------|----------|
| 用户没给 `ratio_px/ratio_m` 就用示例值跑流程 | 模型比例错误，GLB 作废 | 用 AskUserQuestion 追问用户 |
| 假设"上次的配置应该适用这个新 SVG" | 每个 SVG 的像素跨度不同 | 重新确认每一个新 SVG 的参数 |
| 只确认了"导出路径"就以为参数齐全 | 缺少最关键的比例参数 | 检查清单：ratio + curve_res + glb_path 三项齐全 |

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

# === 用户确认的参数（以下值均为占位符，必须替换） ===
props.svg_filepath = '/absolute/path/to/input.svg'   # SVG 文件绝对路径
props.ratio_px = 0.0                                   # ⚠️ 必须由用户确认后填入
props.ratio_m = 0.0                                   # ⚠️ 必须由用户确认后填入
props.curve_res = 4                                    # 曲线精度（确认后填入）

# === 参数校验 ===
assert props.ratio_px > 0 and props.ratio_m > 0, (
    f"致命错误: ratio_px({props.ratio_px}) 和 ratio_m({props.ratio_m}) 未设置有效值。"
    f"必须先向用户确认 SVG 的像素→米换算关系。"
)

# 执行导入
bpy.ops.map.import_svg()
```

> ⚠️ **执行前必须确保 `ratio_px` 和 `ratio_m` 已被替换为用户确认的真实值**。代码中的 `0.0` 会触发 assert 报错，这是有意为之——防止 AI 忘记替换占位符直接执行。

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

**刷新后必须执行的步骤：确认随机高度**

<font color="red">刷新图层列表后，必须将图层名和预设高度展示给用户，询问是否需要开启随机高度。此步骤不可跳过。</font>

```python
# 刷新后，遍历 layer_list 展示给用户
print("图层列表:")
for i, item in enumerate(props.layer_list):
    print(f"  [{i}] {item.layer_name}: height={item.height:.1f}m")

# 用户选择哪些图层需要随机高度后，在脚本中设置：
rand_layers = {"中色box", "浅色box"}  # 用户确认的图层名
for item in props.layer_list:
    if item.layer_name in rand_layers:
        item.use_rand_height = True
        # item.rand_height_min = 10.0   # 可选：自定义下限
        # item.rand_height_max = 60.0   # 可选：自定义上限
        print(f"  开启随机高度: {item.layer_name} (区间 {item.rand_height_min}~{item.rand_height_max}m)")
```

**内置高度预设（constants.py）：**

| 图层关键词 | 高度(m) |
|-----------|---------|
| 路名_主路 | 20.10 |
| 路名_支路 | 15.10 |
| 商场边框 | 60.0 |
| 商场 | 80.0 |
| 深色box | 30.0 |
| 中色box | 40.0 |
| 浅色box | 50.0 |
| 主路 | 20.0 |
| 支路 | 15.0 |
| 绿化 | 10.0 |
| 水 | 5.0 |

**查看/修改图层配置：**
```python
props = bpy.context.scene.map_props
for item in props.layer_list:
    print(f'{item.layer_name}: height={item.height}, color={list(item.color)}')

# 可修改高度或颜色
# props.layer_list[0].height = 15.0
# props.layer_list[0].color = (0.9, 0.1, 0.1, 1.0)  # RGBA 线性值
# props.layer_list[0].use_rand_height = True   # 开启随机高度
# props.layer_list[0].rand_height_min = 5.0     # 随机高度下限
# props.layer_list[0].rand_height_max = 20.0    # 随机高度上限
```

**图层列表属性名速查表（props.py 定义，脚本中必须使用精确名称）：**

| 属性名 | 类型 | 说明 |
|--------|------|------|
| `layer_name` | String | 图层名（只读） |
| `height` | Float | 挤出高度(m) |
| `color` | FloatVector(4) | RGBA 线性颜色值 |
| `use_rand_height` | Bool | 随机高度开关 |
| `rand_height_min` | Float | 随机高度下限 |
| `rand_height_max` | Float | 随机高度上限 |

> ⚠️ **常见错误**：属性名是 `use_rand_height`（非 `use_random_height`），脚本中写错会导致 `AttributeError` 崩溃。

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

# ============================================================
# ⚠️ 用户确认的参数 —— 以下占位符值必须替换为真实值
# ============================================================
svg_path = '/absolute/path/to/input.svg'       # 【必须】SVG 文件绝对路径
glb_path = '/absolute/path/to/output.glb'      # 【必须】GLB 导出绝对路径
ratio_px = 0.0                                  # ⚠️ 【必须确认】像素值，禁止用占位符 0.0 执行
ratio_m = 0.0                                  # ⚠️ 【必须确认】对应米数，禁止用占位符 0.0 执行
curve_res = 4                                   # 【需确认】曲线精度（1~12），确认后方可使用

# === 致命参数校验：不通过则中止 ===
assert ratio_px > 0 and ratio_m > 0, (
    f"致命错误: ratio_px={ratio_px} ratio_m={ratio_m}。"
    f"这些参数控制模型的物理比例，必须先向用户确认 SVG 的 px→m 换算关系。"
    f"每个 SVG 的比例都不同，不可复用其他 SVG 的值。"
)
assert os.path.exists(svg_path), f"SVG 文件不存在: {svg_path}"

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

# 2b. 展示图层列表 + 确认随机高度（不可跳过）
print("图层列表:")
for i, item in enumerate(props.layer_list):
    print(f"  [{i}] {item.layer_name}: height={item.height:.1f}m")
#  -- 此时必须将图层列表展示给用户，等待确认哪些图层需要随机高度 --
#  -- 用户确认后，设置 use_rand_height --
# rand_layers = {"中色box", "浅色box"}  # 示例：用户确认的图层
# for item in props.layer_list:
#     if item.layer_name in rand_layers:
#         item.use_rand_height = True

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

## 五、网格平面优化（导入后、挤出前执行）

位于插件「挤出」标签页的「网格平面优化」区块。**导入 SVG 后、一键挤出前**，可对网格执行0面积面检查和重新拓扑。

### 5.0 检查0面积的面

```python
# 选中网格后执行
bpy.ops.map.check_zero_area()
```

**作用：** 遍历选中网格，面积 < 0.0001 的面视为0面积面，将问题物体**移动至**集合「0面积的面」并报告。

### 5.0b 重新拓扑

```python
# 选中网格后执行
bpy.ops.map.retopology()
```

**作用：** 前置优化（按距离合并 0.0001m + 有限融并 0.1°）→ bmesh 提取边界轮廓线 → 转曲线 → 几何节点 FillCurve 填充 → 转网格，消除0面积面。

> ⚠️ **重要经验：文字层不需要执行重新拓扑**
> - 插件导入 SVG 时已用几何节点 FillCurve 填充，导入后的网格是干净的 N-gon，通常没有0面积面
> - 重新拓扑的 bmesh 删面→提取轮廓→FillCurve 重建流程，对复杂文字形状可能**引入新的0面积面**
> - **正确做法**：检查0面积面后，仅对有问题的物体执行重新拓扑，不要无差别对全部网格执行
> - 如果文字层不挤出（仅平面放置在道路上方），完全不需要参与重新拓扑

---

## 六、独立小工具（不在主流程中，按需单独调用）

以下三个工具位于插件「导出」标签页的「实用小工具」区域，**不在 SVG to 3D 的主流程中**，需单独测试或使用。

### 6.1 UVmap 批量清理

```python
# 选中网格后执行
bpy.ops.object.select_all(action='DESELECT')
for m in target_meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = target_meshes[0]
bpy.ops.map.clean_uvmap()
```

**作用：** 确保每个网格有且仅有一个名为 `UVMap` 的 UV 层。多 UV 时保留活动层、删除其余并改名。

### 6.2 自定义法向批量清理

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

### 6.3 按所选面批量设置原点

```python
# 必须在编辑模式下，选中面后执行
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='DESELECT')
# ... 用 bmesh 选中目标面 ...
bpy.ops.map.set_origin_to_face()
```

**作用：** 将每个网格的原点设置到其选中面的中心，旋转对齐完整面坐标系（X=切线, Y=法向×切线, Z=法向）。

---

## 七、关键参数说明

| 参数 | 属性路径 | 类型 | 默认值 | 必确认 | 说明 |
|------|---------|------|--------|--------|------|
| SVG 文件 | `props.svg_filepath` | String | - | 🔴 必须 | SVG 文件绝对路径，由用户提供 |
| 像素值 | `props.ratio_px` | Float | 0.0 | 🔴 **必须** | SVG 中多少像素。**无默认值，必须由用户确认。示例：100px** |
| 米数 | `props.ratio_m` | Float | 0.0 | 🔴 **必须** | 上述像素对应的实际距离。**无默认值，必须由用户确认。示例：10m** |
| 曲线精度 | `props.curve_res` | Int | 4 | 🟡 建议 | 曲线转网格采样精度（1~12）。默认 4 对多数场景合理 |
| 仅导出可见 | `props.exp_visible_only` | Bool | True | ⬜ 可选 | 仅导出视口可见物体 |
| 应用修改器 | `props.exp_apply_modifiers` | Bool | True | ⬜ 可选 | 导出前应用修改器 |
| 拼音防呆 | `props.exp_pinyin_safe` | Bool | True | ⬜ 可选 | 导出时中文转拼音 |

**比例换算公式（插件内部，了解即可）：** `scale_factor = 3543.0 * (ratio_m / ratio_px)`

> 🔴 **ratio_px 和 ratio_m 是最容易出错的参数**。每次处理新的 SVG 都必须重新确认。不可复用之前 SVG 的比例值。
