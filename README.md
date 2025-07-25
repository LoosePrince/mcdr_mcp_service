# MCDR MCP Service Plugin

一个为MCDReforged (MCDR) 提供Model Context Protocol (MCP) 服务接口的插件，让AI可以通过标准化协议控制和监控MCDR服务器。

> 本插件目前仅为测试版本，我们无法保证其稳定性，请谨慎使用。

## 功能特性

- **🚀 基础MCP服务**: 支持标准MCP协议的WebSocket连接
- **⚡ 命令执行**: 支持MCDR命令和Minecraft服务器命令的执行
- **📊 状态监控**: 实时获取服务器和MCDR状态信息
- **🔍 命令树**: 获取完整的命令树和插件命令列表
- **📋 日志管理**: 获取、搜索和管理服务器日志
  - 获取最近日志和指定范围日志
  - 支持文本和正则表达式搜索
  - 智能上下文显示和结果排序
- **🛡️ 安全控制**: IP白名单、命令权限控制、危险命令拦截
- **🔧 智能工具**: 自动将MCDR命令转换为独立MCP工具

## 安装与配置

### 1. 获取插件源码

使用git克隆本仓库：

```bash
git clone https://github.com/LoosePrince/mcdr_mcp_service.git
```

### 2. 打包插件为MCDR可识别格式

将 `mcdreforged.plugin.json` 和 `mcdr_mcp_service` 文件夹一起打包为zip压缩包，并将后缀名改为 `.mcdr`，例如：

```bash
zip -r mcdr_mcp_service.mcdr mcdreforged.plugin.json mcdr_mcp_service
```

### 3. 安装插件

将生成的 `mcdr_mcp_service.mcdr` 文件放入你的MCDReforged插件目录（如 `plugins/` 文件夹）。

### 4. 安装依赖

进入Python环境，安装所需依赖：

```bash
pip install websockets>=10.0 aiohttp>=3.8.0 pydantic>=1.10.0
```

### 5. 加载插件

在MCDR控制台执行：

```
!!MCDR plugin load mcdr_mcp_service.mcdr
```

插件将在 `127.0.0.1:8765` 启动MCP服务器。

## AI客户端连接配置

### UVX格式连接配置

如果你使用支持MCP的AI客户端（如Claude Desktop），请在配置文件中添加以下配置：

#### 方法1：直接WebSocket连接（推荐）

```json
{
  "mcpServers": {
    "mcdr-mcp-service": {
      "command": "python",
      "args": [
        "-c", 
        "import asyncio,websockets,json,sys;exec('async def main():\\n  try:\\n    async with websockets.connect(\"ws://127.0.0.1:8765\") as ws:\\n      while True:\\n        try:\\n          line=input()\\n          if not line.strip():continue\\n          req=json.loads(line)\\n          await ws.send(json.dumps(req))\\n          resp=await ws.recv()\\n          print(resp)\\n          sys.stdout.flush()\\n        except EOFError:break\\n        except Exception as e:print(json.dumps({\"jsonrpc\":\"2.0\",\"id\":None,\"error\":{\"code\":-32603,\"message\":str(e)}}))\\n  except Exception as e:print(json.dumps({\"jsonrpc\":\"2.0\",\"id\":None,\"error\":{\"code\":-32603,\"message\":str(e)}}))\\nasyncio.run(main())')"
      ]
    }
  }
}
```

#### 方法2：使用npx和简单WebSocket客户端（如果安装了Node.js）

```json
{
  "mcpServers": {
    "mcdr-mcp-service": {
      "command": "node",
      "args": [
        "-e",
        "const WebSocket=require('ws');const readline=require('readline');const ws=new WebSocket('ws://127.0.0.1:8765');const rl=readline.createInterface({input:process.stdin,output:process.stdout});ws.on('open',()=>{rl.on('line',(line)=>{try{const req=JSON.parse(line);ws.send(JSON.stringify(req));}catch(e){console.log(JSON.stringify({jsonrpc:'2.0',id:null,error:{code:-32700,message:e.message}}));}});});ws.on('message',(data)=>{console.log(data.toString());});ws.on('error',(e)=>{console.log(JSON.stringify({jsonrpc:'2.0',id:null,error:{code:-32603,message:e.message}}));});"
      ]
    }
  }
}
```

#### 方法3：更简洁的Python版本

```json
{
  "mcpServers": {
    "mcdr-mcp-service": {
      "command": "python",
      "args": [
        "-u",
        "-c",
        "import asyncio,websockets,json,sys;async def main():async with websockets.connect('ws://127.0.0.1:8765')as ws:[print(await ws.recv())if await ws.send(json.dumps(json.loads(input())))is None else None for _ in iter(int,1)];asyncio.run(main())"
      ]
    }
  }
}
```

#### 方法4：使用MCP桥接器

提供了一个桥接脚本 `mcp_bridge.py`：

然后在MCP配置中使用：

```json
{
  "mcpServers": {
    "mcdr-mcp-service": {
      "command": "python",
      "args": ["/path/to/mcp_bridge.py"]
    }
  }
}
```

## 可用工具

> 随更新，工具列表可能会有所变化

插件提供以下MCP工具：

- get_command_tree：获取MCDR可用命令列表和指令树
- execute_command：执行MCDR命令或Minecraft服务器命令，并捕获真实的命令响应
- get_server_status：获取MCDR服务器状态信息
- get_recent_logs：获取最近的服务器日志（支持MCDR和Minecraft日志）
- get_logs_range：获取指定范围的服务器日志（支持MCDR和Minecraft日志）
- search_logs：搜索日志内容，支持文本搜索和正则表达式搜索
- search_logs_by_ids：根据搜索ID范围查询日志
- MCDR自带命令工具：插件会自动将MCDR自带的命令（以`!!MCDR`开头）转换为独立的MCP工具，使AI可以直接调用这些命令，而无需使用`execute_command`工具。

详细的工具参数、示例和响应格式请参见 [docs](https://looseprince.github.io/mcdr_mcp_service/docs.html) 文档页面。

## 配置文件

插件会在 `config/mcdr_mcp_service/config.json` 创建配置文件。

### 主要配置选项

```json
{
  "mcp_server": {
    "enabled": true,
    "host": "127.0.0.1",
    "port": 8765,
    "max_connections": 5
  },
  "security": {
    "require_authentication": false,
    "api_key": "",
    "allowed_ips": [
      "127.0.0.1",
      "::1"
    ],
    "rate_limit": {
      "requests_per_minute": 60,
      "commands_per_minute": 30
    }
  },
  "features": {
    "command_execution": true,
    "server_status": true,
    "command_tree": true,
    "command_tree_max_depth": 3,
    "mcdr_command_tools": true,
    "log_access": true,
    "log_search": true,
    "log_max_lines": 50,
    "log_context_max_lines": 10
  },
  "dangerous_commands": [
    "stop",
    "restart",
    "reload",
    "exit",
    "!!MCDR stop"
  ]
}
```

### 配置项说明

#### MCP服务器配置
- `enabled`: 是否启用MCP服务器
- `host`: 服务器监听地址
- `port`: 服务器监听端口
- `max_connections`: 最大并发连接数

#### 安全配置
- `require_authentication`: 是否需要API密钥认证
- `api_key`: API密钥（如果启用认证）
- `allowed_ips`: 允许连接的IP白名单
- `rate_limit`: 请求频率限制

#### 功能配置
- `command_execution`: 是否允许执行命令
- `server_status`: 是否允许获取服务器状态
- `command_tree`: 是否允许获取命令树
- `command_tree_max_depth`: 命令树解析的最大深度（影响返回的命令数量）
- `mcdr_command_tools`: 是否启用MCDR自带命令工具（将MCDR命令转换为独立工具）
- `log_access`: 是否允许访问日志
- `log_search`: 是否允许搜索日志
- `log_max_lines`: 日志访问时返回的最大行数
- `log_context_max_lines`: 搜索结果上下文的最大行数

#### 危险命令
- 列表中的命令将被阻止执行，以保护服务器安全

## 安全注意事项

1. **IP白名单**: 默认只允许本地连接（127.0.0.1）
2. **命令权限**: 某些危险命令被限制执行
3. **连接限制**: 限制最大并发连接数
4. **本地使用**: 建议仅在本地环境使用，不要暴露到公网

## 故障排除

### 常见问题

1. **MCP服务器无法启动**
   - 检查端口8765是否被占用
   - 确认依赖包是否正确安装
   - 查看MCDR日志中的错误信息

2. **AI客户端无法连接**
   - 检查防火墙设置
   - 验证IP是否在白名单中
   - 确认WebSocket协议支持

3. **命令执行失败**
   - 检查命令语法是否正确
   - 确认是否有执行权限
   - 查看是否被危险命令列表阻止

## 许可证

本项目使用 MIT 许可证。详情请查看 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v1.1.0（2025年7月25日）
- 新增日志管理功能
  - `get_recent_logs`: 获取最近的服务器日志
  - `get_logs_range`: 获取指定范围的日志
  - `search_logs`: 智能日志搜索（支持正则表达式）
  - `search_logs_by_ids`: 根据搜索ID范围查询日志
- 集成LogWatcher日志监控系统
- 支持日志上下文显示和结果排序
- 增强配置项，添加日志相关安全控制

### v1.0.0（2025年7月24日）
- 初始版本发布
- 支持基础MCP协议
- 实现命令树获取和命令执行功能