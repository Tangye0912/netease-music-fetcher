# Contributing

## 提交信息规范（推荐）

为了让新同学快速看懂变更，建议每次提交都包含“文件级说明”。

### 模板

```text
<type>: <本次目标>

- <file-1>: <主要改动点>
- <file-2>: <主要改动点>
- <file-3>: <主要改动点>
```

### 例子

```text
feat: 优化登录与启动体验

- main.py: 登录窗口改为扫码优先，并在退出时清理内嵌网页登录态
- ui_texts.py: 更新登录与输入区提示文案
- start_mac.command: 新增 macOS 双击启动入口
- start_windows.bat: 新增 Windows 双击启动入口
- README.md: 更新启动方式、默认格式与流程说明
```

## 开发检查

提交前建议执行：

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```
