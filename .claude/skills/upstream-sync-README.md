# Upstream Sync - 上游代码同步工具

一键安全地将 LmeSzinc/StarRailCopilot 的上游更新合并到你的自定义分支，并生成详细的变更报告。

## 快速开始

### 方法 1: 使用斜杠命令（推荐）

在 Claude Code 对话中直接输入：

```
/upstream-sync
```

Claude 会自动：
1. ✅ 检查当前分支和工作区状态
2. ✅ 安全地切换到 master 分支并拉取更新
3. ✅ 合并到 my-relic-tools 分支
4. ✅ 处理冲突（如果有）
5. ✅ 生成详细的中文变更报告

### 方法 2: 自然语言调用

也可以直接说：

```
检测到上游更新，请安全合并
同步上游代码
更新 master 分支
```

## 工作原理

### 分支结构

```
master (跟踪上游)
  ↓ 合并
my-relic-tools (自定义开发)
```

- **master**: 只用于同步上游，**NEVER** 提交自定义代码
- **my-relic-tools**: 包含你的遗器强化系统、深渊导航等自定义功能

### 安全流程

```bash
# 1. 检查状态
git status  # 确保没有未提交的重要更改

# 2. 更新 master
git checkout master
git pull origin master

# 3. 合并到自定义分支
git checkout my-relic-tools
git merge master --no-edit

# 4. 检查结果
git status
```

### 冲突处理

如果出现合并冲突，Claude 会：
- 📋 列出所有冲突文件
- 🔍 显示冲突标记（`<<<<<<< HEAD`）
- 💡 提供解决建议
- ✅ 指导你完成解决流程

## 输出示例

成功同步后，你会看到详细报告：

```markdown
## 📦 上游更新报告

### 📊 更新概览
- 更新时间: 2025-12-24
- 新增提交: 1 个
- 修改文件: 1 个
- 合并状态: 成功

### 📝 提交历史
5983da4a4 - Fix: ocr scan chinese wrong '明辉日珥' and '灭流绝溢的缄默'
作者: AkagiYui
时间: 2025-12-24 00:49

### 📄 文件变更
tasks/planner/scan.py | 4 ++++

### 🔍 详细变更内容
+        # 明辉日珥
+        result = re.sub('明辉日.?', '明辉日珥', result)
+        # 灭流绝溢的缄默
+        result = re.sub('灭流绝溢的.?默', '灭流绝溢的缄默', result)

### 💡 影响分析
- 是否影响自定义代码: 否
- 潜在冲突风险: 低
- 建议操作: 纯bug修复，可安全使用

### ✅ 下一步
- [ ] 测试遗器强化功能是否正常
- [ ] 测试深渊导航功能是否正常
- [ ] 提交未跟踪的自定义代码（如有）
```

## 自定义代码保护

Skill 会特别关注以下自定义代码位置，确保它们不受影响：

```
📁 tools/relics_recognizer/         (遗器识别与强化，~3900行)
📁 tools/forgotten_hall_navigator/  (深渊导航模块)
📁 tasks/relics/                    (遗器任务)
📁 tasks/forgotten_hall/            (深渊任务)
📄 module/webui/relic_plans.py      (方案管理)
📄 module/webui/components/relic_widgets.py
📁 .claude/                         (项目文档和技能)
```

如果这些文件在合并时被修改，Claude 会**特别提醒**并仔细检查冲突。

## 安全原则

1. ✅ **只读 master** - master 分支只镜像上游，不提交自定义代码
2. ✅ **单向合并** - 始终是 master → my-relic-tools，从不反向
3. ✅ **检查再行动** - 切换分支前检查未提交更改
4. ✅ **详细报告** - 每次同步都生成完整变更说明
5. ❌ **禁止强推** - 除非你明确要求，否则绝不使用 force push

## 常见场景

### 场景 1: 正常更新（无冲突）

```
你: /upstream-sync
Claude: ✅ 成功同步，修改了1个文件，无冲突
```

### 场景 2: 有未提交的自定义代码

```
你: /upstream-sync
Claude: ⚠️ 发现7个未跟踪文件（自定义代码）
       建议先提交保护数据，是否继续？
你: 继续
Claude: ✅ 已合并，自定义代码安全
```

### 场景 3: 发生冲突

```
你: /upstream-sync
Claude: ⚠️ 合并冲突: module/webui/app.py
       请手动解决以下冲突...
       [显示冲突内容和解决建议]
```

### 场景 4: 正在自定义分支上工作

```
你: /upstream-sync
Claude: 📍 当前在 my-relic-tools 分支
       切换到 master 拉取更新...
       ✅ 已合并回 my-relic-tools
```

## 高级用法

### 预览更新内容（不实际合并）

在对话中问：

```
上游有哪些新提交？
master 分支有什么更新？
```

Claude 会执行：
```bash
git fetch origin master
git log --oneline master..origin/master
git diff --stat master..origin/master
```

### 查看特定提交详情

```
详细显示 commit 5983da4a4 的内容
```

Claude 会执行：
```bash
git show 5983da4a4
git diff 5983da4a4^ 5983da4a4
```

## 与原版区别

| 手动操作 | 使用 /upstream-sync |
|---------|-------------------|
| 需要记住分支名称 | ✅ 自动识别 |
| 需要手动检查状态 | ✅ 自动检查 |
| 合并后不知道改了什么 | ✅ 详细中文报告 |
| 容易忘记切回工作分支 | ✅ 自动切回 |
| 冲突时不知所措 | ✅ 提供解决指导 |
| 可能误操作丢失代码 | ✅ 多重安全检查 |

## 故障排查

### Q: Skill 找不到？

A: 确保文件路径正确：
```bash
ls .claude/skills/upstream-sync.yaml
```

如果不存在，重新创建或检查文件权限。

### Q: 提示"当前分支有未提交更改"？

A: 这是安全检查，你可以：
1. `git add . && git commit -m "保存工作"` （推荐）
2. `git stash` （临时存储）
3. 告诉 Claude "忽略未提交更改继续"（不推荐）

### Q: 合并后自定义功能不工作了？

A:
1. 检查冲突文件是否正确解决
2. 查看变更报告，确认是否影响自定义代码
3. 运行 `git diff HEAD~1` 查看具体改动
4. 必要时回滚: `git reset --hard HEAD~1`（谨慎！）

### Q: 想要撤销合并？

A:
```bash
# 如果还没推送，可以回滚
git reset --hard HEAD~1

# 如果已推送，需要创建反向提交
git revert -m 1 HEAD
```

## 相关文档

- 项目笔记: `.claude/CLAUDE.md`
- 日志规范: `.claude/LOGGING_STYLE.md`
- 模板处理: `.claude/skills/template-processor-README.md`

## 贡献

如果你发现 skill 有改进空间，欢迎编辑 `upstream-sync.yaml` 并提交到 my-relic-tools 分支。
