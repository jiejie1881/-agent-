# 司机小程序

使用微信原生 WXML、WXSS、JavaScript。包含登录、今日任务、任务详情、到店、签收、配送异常、回单上传、历史、个人中心及请假页面。访问权限仍由后端 DRIVER 角色和任务归属校验控制。

## 本地导入

1. 首次使用时复制 `project.config.example.json` 为 `project.config.json`，已有配置不要覆盖。
2. 在微信开发者工具中导入本目录。填写自己的 AppID；游客模式的可用能力以开发者工具实际提示为准。
3. 在 `utils/config.js` 中配置 API 环境。模拟器可以使用本机地址，真机必须使用手机可访问的局域网地址或已部署的 HTTPS 服务。
4. 本地调试可在开发设置中关闭合法域名检查；正式部署必须配置合法 request、uploadFile、downloadFile 域名。
5. 使用本地创建且绑定车辆的 DRIVER 账号登录，不要将实际密码加入仓库。

`project.config.json` 和 `project.private.config.json` 为本地配置，均不提交。不会在导入时自动创建账号或改变数据库。

## 静态检查

在本目录执行：

```powershell
node --test tests/*.test.js
```

Node 测试不是微信实际编译。人工验收需检查：编译、登录、任务列表、开始配送、到店、签收与图片上传、异常上报、所有停靠点处理后完成任务、历史、个人中心和退出登录。真机还需验证网络地址、合法域名、图片预览以及 JWT 上传请求。
