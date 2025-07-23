# MCDR MCP Service Plugin

一个为MCDReforged (MCDR) 提供Model Context Protocol (MCP) 服务接口的插件，让AI可以通过标准化协议控制和监控MCDR服务器。

> 本插件目前仅为测试版本，我们无法保证其稳定性，请谨慎使用。

## 功能特性

- **🚀 基础MCP服务**: 支持标准MCP协议的WebSocket连接
- 暂无

## 安装与配置

### 1. 安装依赖

确保你已经安装了必要的Python包：

```bash
pip install websockets>=10.0 aiohttp>=3.8.0 pydantic>=1.10.0
```

### 2. 安装插件

将 `mcdr_mcp_service` 文件夹复制到你的MCDR插件目录中：

```bash
cp -r mcdr_mcp_service /path/to/your/mcdr/plugins/
```

### 3. 重载插件

在MCDR控制台中执行：

```
!!MCDR reload plugin mcdr_mcp_service
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

#### 方法2：使用MCP桥接器

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

### 1. get_command_tree
获取MCDR可用命令列表和指令树

**参数：**
- `plugin_id` (可选): 指定插件ID以获取特定插件的命令

**示例：**
```json
{
  "name": "get_command_tree",
  "arguments": {}
}
```

### 2. execute_command
执行MCDR命令或Minecraft服务器命令，并捕获真实的命令响应


**参数：**
- `command` (必需): 要执行的命令
- `source_type` (可选): 命令来源类型 ("console" 或 "player")

**示例：**
```json
{
  "name": "execute_command", 
  "arguments": {
    "command": "!!MCDR status",
    "source_type": "console"
  }
}
```

**响应格式：**
```json
{
  "success": true,
  "command": "!!MCDR status",
  "output": "MCDR 服务器状态信息的完整响应内容...",
  "response_type": "captured",
  "timestamp": 1753261523
}
```

### 3. get_server_status
获取MCDR服务器状态信息

**参数：**
- `include_players` (可选): 是否包含在线玩家信息

**示例：**
```json
{
  "name": "get_server_status",
  "arguments": {
    "include_players": true
  }
}
```

### 4. test_command_execution
测试命令执行功能，验证MCDR和Minecraft命令是否能正常执行并捕获响应

**用途：**
- 🧪 测试MCP服务的命令执行功能是否正常
- 📊 获取命令执行的测试报告
- 🔍 调试命令响应捕获问题

**参数：** 无

**示例：**
```json
{
  "name": "test_command_execution",
  "arguments": {}
}
```

**测试命令：**
- `!!MCDR status` - 测试MCDR状态命令
- `!!MCDR plugin list` - 测试插件列表命令  
- `/list` - 测试Minecraft玩家列表命令

## 配置文件

插件会在 `config/mcdr_mcp_service/config.json` 创建配置文件。


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

### 日志查看

检查MCDR日志以获取详细的错误信息：

```bash
tail -f logs/latest.log | grep "mcdr_mcp_service"
```


## 许可证

本项目使用 MIT 许可证。详情请查看 LICENSE 文件。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 更新日志

### v1.0.0
- 初始版本发布
- 支持基础MCP协议
- 实现命令树获取和命令执行功能