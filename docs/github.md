# GitHub建仓设置

## 名称与描述

- 仓库名称：`astrbot_plugin_keyword_reply`，与插件标识一致。
- 描述：`简洁易用的 AstrBot 群聊关键词与句式回复插件，支持随机文字、变量替换、适用群和 @ 触发（QQ / OneBot v11）`。
- 建议公开仓库，便于通过GitHub地址安装。
- 推送后把默认分支设为 `mian`，保留现有分支名。

本地已有Git提交、README和`.gitignore`。在GitHub创建**空仓库**，不要再勾选初始化README、添加`.gitignore`或许可证，避免多出独立历史。许可证可选定后在本地新增LICENSE，再一同推送。

来源：[AstrBot插件命名指南](https://docs.astrbot.app/dev/star/plugin-new.html)、[GitHub：推送已有本地代码](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

## .gitignore

直接使用仓库已有的[.gitignore](../.gitignore)，无需GitHub额外模板。它覆盖Python环境和缓存、构建包、测试运行目录、集成框架源码、本地凭据、运行数据、编辑器和系统文件。

`examples/rules.json`、`_conf_schema.json`、`metadata.yaml`、`requirements.txt`、测试及文档都需要提交。安装ZIP放到GitHub Release附件，不提交`dist/`。不要用`*.json`忽略规则，否则会遗漏插件配置表单与示例。

## 许可证建议

推荐 **MIT License**：适合希望别人方便使用和修改的小型插件，允许商业使用和闭源分发，要求保留版权与许可声明。版权人建议填写 `Rainfrost`，年份 `2026`。这是建议，仓库当前尚未添加LICENSE，也未正式选定开源许可。

如果你的目的包括要求公开分发的修改版保持开源，且网络服务使用修改版时向用户提供对应源码，可以改选 **GNU AGPLv3**；它允许商业使用，并非“禁止商用”。

AstrBot本体使用AGPLv3。本仓库未打包本体，独立插件许可不替代AstrBot的许可；若今后复制或改编本体及其他项目代码，需遵守其许可并保留相应声明。

来源：[MIT](https://choosealicense.com/licenses/mit/)、[AGPLv3](https://choosealicense.com/licenses/agpl-3.0/)、[AstrBot开发原则](https://docs.astrbot.app/dev/star/plugin-new.html)。

## 仓库建好之后

取得真实地址后，在`metadata.yaml`补充`repo: https://github.com/<账号>/astrbot_plugin_keyword_reply`。当前未填写虚构地址。确认LICENSE选择和版本后，将现有`mian`分支推送到该地址；本次仅提交本地，未创建远程仓库或推送。
