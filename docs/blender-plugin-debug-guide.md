# Blender 插件 BUG 调试经验：终端日志定位法

## 背景

在 v0.3.16 开发过程中，遇到一个诡异的 BUG：插件「清理未使用数据」功能在执行「导入 SVG → 一键挤出」之后，状态栏只显示红叉，不显示任何文案。经过多轮修复尝试未果，最终通过**终端启动 Blender 查看系统日志**精准定位到根因。

## 问题现象

- 清理功能本身正常，能清理掉孤立数据
- 但状态栏提示只显示红叉，不显示文案
- UVmap清理、自定义法向清理的提示正常
- 后台模式（`--background`）无法复现

## 错误的排查方向

1. **怀疑 `orphans_purge` 报 ERROR** → 改为手动 `bpy.data.X.remove()` → 未解决
2. **怀疑 `bl_options` 缺失** → 给所有 operator 补 `{'REGISTER', 'UNDO'}` → 未解决
3. **后台模式测试** → 全部正常，无法复现

## 正确的定位方法：终端启动 Blender

### 操作步骤

1. **从终端启动 Blender**（不要从 Dock/Finder 启动）：

```bash
/Applications/Blender\ 4.2\ LTS.app/Contents/MacOS/Blender
```

2. **执行问题操作流程**，本例是：导入 SVG → 一键挤出 → 点击清理

3. **查看终端输出的日志**，重点查找 `Traceback`、`Error`、`TypeError`

### 本案例定位到的根因

终端日志显示大量重复的 `TypeError`：

```
Traceback (most recent call last):
  File ".../1000MU_Map_Plugin/ui.py", line 97, in draw
    gen_row=layout.row(); gen_row.scale_y=1.2; gen_row.operator('map.generate_3d',icon='ROCKET',text='一键挤出')
TypeError: UILayout.operator(): error with keyword argument "icon" -  enum "ROCKET" not found in (...)
```

**根因**：`ui.py` 第97行使用了 `icon='ROCKET'`，但 Blender 4.2 的图标枚举中**没有 `ROCKET`**。

### 为什么会导致清理提示异常？

- `ROCKET` 图标在「一键挤出」按钮上，该按钮在 `layer_list` 有内容后（导入 SVG 后）显示
- 每次面板重绘（包括点击清理后触发状态栏更新导致重绘），`draw()` 方法都会抛出 `TypeError`
- 这些持续不断的异常**污染了 Blender 的报告显示系统**，导致后续 operator 的 INFO 报告无法正常显示，状态栏只显示红叉

### 为什么后台模式无法复现？

后台模式（`--background`）不执行 UI `draw()`，所以不会触发 `TypeError`，报告系统正常工作。

### 为什么其他功能（UVmap清理等）提示正常？

这些功能不在导入页，点击它们时不会触发导入页的 `draw()` 重绘（或重绘频率低），报告系统未被污染。

## 修复

将 `icon='ROCKET'` 改为 `icon='PLAY'`（Blender 4.2 有效图标）。

## 经验总结

### 1. 终端启动是定位 GUI 相关 BUG 的利器

当遇到以下情况时，**优先使用终端启动 Blender**：
- 后台模式测试正常，但 GUI 模式异常
- operator 功能正常但提示/状态异常
- 怀疑 UI `draw()` 方法有问题
- 状态栏报告显示异常

### 2. 无效图标是隐蔽的 BUG 来源

Blender 4.x 对图标枚举有严格检查，无效图标会导致 `draw()` 抛出 `TypeError`。这类问题：
- 不会在插件加载时报错
- 只在面板重绘时触发
- 后台模式完全不触发
- 异常会被 Blender 内部捕获，不影响其他功能，但会污染报告系统

### 3. UI 异常会影响 operator 报告显示

`draw()` 方法的异常会污染 Blender 的报告显示队列，导致后续 operator 的 `self.report()` 调用虽然成功，但报告无法正常显示在状态栏。

### 4. 图标命名要查证

Blender 4.x 的有效图标列表：
- 不会随版本增加新图标（`ROCKET` 在某些版本可能存在，4.2 中不存在）
- 完整列表见：[Blender Icon Assets](https://docs.blender.org/api/current/bpy.types.UILayout.html#bpy.types.UILayout.icon)
- 或在 Python Console 中执行：`[i for i in dir(bpy.types.UILayout) if 'icon' in i.lower()]`

### 5. 排查清单

遇到「功能正常但提示异常」时，按以下顺序排查：
1. **终端启动 Blender**，查看是否有 `Traceback`
2. 检查 `ui.py` 中的 `icon=` 参数是否都是有效图标
3. 检查 `draw()` 方法是否有其他可能的异常
4. 检查 operator 的 `bl_options` 是否包含 `REGISTER`
5. 检查是否有 `bpy.ops` 内层调用产生 ERROR 报告
