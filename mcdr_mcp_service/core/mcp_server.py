"""
MCP服务器实现
提供WebSocket接口和MCP协议支持
"""

import asyncio
import json
import re
import websockets
import logging
from typing import Dict, Any, List, Optional
from websockets.server import WebSocketServerProtocol

from mcdreforged.api.all import PluginServerInterface


class MCPServer:
    """MCP服务器主类"""
    
    def __init__(self, server_interface: PluginServerInterface, command_handler, config: Dict[str, Any]):
        self.server = server_interface
        self.command_handler = command_handler
        self.config = config
        self.websocket_server = None
        self.connected_clients = set()
        
        # 设置日志
        self.logger = server_interface.logger
        
    async def start(self):
        """启动MCP服务器"""
        host = self.config["mcp_server"]["host"]
        port = self.config["mcp_server"]["port"]
        
        try:
            # 临时抑制一些 websockets 的日志
            import logging
            websockets_logger = logging.getLogger('websockets.server')
            original_ws_level = websockets_logger.level
            
            self.websocket_server = await websockets.serve(
                self.handle_client,
                host,
                port,
                max_size=1024*1024,  # 1MB max message size
                ping_interval=20,
                ping_timeout=10
            )
            
            self.logger.info(f"MCP WebSocket服务器启动成功，监听 {host}:{port}")
            
            # 保持服务器运行
            await self.websocket_server.wait_closed()
            
        except Exception as e:
            self.logger.error(f"MCP服务器启动失败: {e}")
            raise
    
    async def stop(self):
        """停止MCP服务器"""
        if self.websocket_server:
            try:
                # 关闭所有连接的客户端
                if self.connected_clients:
                    await asyncio.gather(
                        *[client.close() for client in self.connected_clients.copy()],
                        return_exceptions=True
                    )
                    self.connected_clients.clear()
                
                # 关闭服务器
                self.websocket_server.close()
                await self.websocket_server.wait_closed()
                self.websocket_server = None
                self.logger.info("MCP服务器已停止")
            except Exception as e:
                self.logger.error(f"停止MCP服务器时出错: {e}")
    
    def stop_sync(self):
        """同步停止MCP服务器（用于插件卸载）"""
        if self.websocket_server:
            try:
                # 清空客户端连接（不尝试异步关闭）
                self.connected_clients.clear()
                
                # 关闭服务器
                self.websocket_server.close()
                
                # 等待端口真正释放
                import socket
                import time
                host = self.config["mcp_server"]["host"]
                port = self.config["mcp_server"]["port"]
                
                # 检查端口是否释放的函数
                def is_port_free():
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                            s.settimeout(0.1)
                            result = s.connect_ex((host, port))
                            return result != 0  # 如果连接失败，说明端口已释放
                    except Exception:
                        return True  # 如果出现异常，假设端口已释放
                
                # 等待端口释放，最多等待5秒
                max_wait_time = 5.0
                wait_interval = 0.1
                total_waited = 0.0
                
                while total_waited < max_wait_time:
                    if is_port_free():
                        break
                    time.sleep(wait_interval)
                    total_waited += wait_interval
                
                if not is_port_free():
                    self.logger.warning(f"端口 {port} 可能仍被占用，但继续执行卸载")
                
                # 标记为已关闭
                self.websocket_server = None
                
                self.logger.info("MCP服务器已同步停止")
            except Exception as e:
                self.logger.error(f"同步停止MCP服务器时出错: {e}")
                # 即使出错也要清理状态
                self.websocket_server = None
                self.connected_clients.clear()
                
            # 确保所有资源都被释放
            try:
                import gc
                gc.collect()
            except Exception:
                pass
    
    async def handle_client(self, websocket: WebSocketServerProtocol, path: str = None):
        """处理客户端连接"""
        client_address = websocket.remote_address
        self.logger.info(f"新的MCP客户端连接: {client_address}")
        
        # 检查IP白名单
        if not self._check_ip_allowed(client_address[0]):
            self.logger.warning(f"拒绝来自 {client_address} 的连接：IP不在白名单中")
            await websocket.close(code=1008, reason="IP not allowed")
            return
        
        self.connected_clients.add(websocket)
        
        try:
            async for message in websocket:
                try:
                    # 解析MCP消息
                    mcp_request = json.loads(message)
                    self.logger.debug(f"收到MCP请求: {mcp_request}")
                    
                    # 处理请求
                    response = await self.handle_mcp_request(mcp_request)
                    
                    # 发送响应
                    if response:
                        await websocket.send(json.dumps(response))
                        
                except json.JSONDecodeError as e:
                    self.logger.error(f"无效的JSON消息: {e}")
                    error_response = self._create_error_response(
                        None, -32700, "Parse error", str(e)
                    )
                    await websocket.send(json.dumps(error_response))
                    
                except Exception as e:
                    self.logger.error(f"处理MCP请求时出错: {e}")
                    error_response = self._create_error_response(
                        None, -32603, "Internal error", str(e)
                    )
                    await websocket.send(json.dumps(error_response))
                    
        except websockets.exceptions.ConnectionClosed:
            self.logger.info(f"MCP客户端断开连接: {client_address}")
        except Exception as e:
            self.logger.error(f"处理客户端连接时出错: {e}")
        finally:
            self.connected_clients.discard(websocket)
    
    def _check_ip_allowed(self, ip: str) -> bool:
        """检查IP是否在白名单中"""
        allowed_ips = self.config.get("security", {}).get("allowed_ips", ["127.0.0.1"])
        return ip in allowed_ips or "0.0.0.0" in allowed_ips
    
    async def handle_mcp_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理MCP协议请求"""
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})
        
        self.logger.debug(f"处理MCP方法: {method}")
        
        try:
            if method == "initialize":
                return await self._handle_initialize(request_id, params)
            elif method == "tools/list":
                return await self._handle_tools_list(request_id, params)
            elif method == "tools/call":
                return await self._handle_tools_call(request_id, params)
            elif method == "resources/list":
                return await self._handle_resources_list(request_id, params)
            elif method == "resources/read":
                return await self._handle_resources_read(request_id, params)
            else:
                return self._create_error_response(
                    request_id, -32601, "Method not found", f"Unknown method: {method}"
                )
        except Exception as e:
            self.logger.error(f"处理MCP方法 {method} 时出错: {e}")
            return self._create_error_response(
                request_id, -32603, "Internal error", str(e)
            )
    
    async def _handle_initialize(self, request_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理initialize请求"""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {}
                },
                "serverInfo": {
                    "name": "MCDR MCP Service",
                    "version": "1.0.0"
                }
            }
        }
    
    async def _handle_tools_list(self, request_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理tools/list请求"""
        tools = [
            {
                "name": "get_command_tree",
                "description": "获取MCDR可用命令列表和指令树",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "plugin_id": {
                            "type": "string",
                            "description": "指定插件ID以获取特定插件的命令（可选）"
                        }
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "total_commands": {"type": "integer"},
                        "commands": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "plugin_id": {"type": "string"},
                                    "plugin_name": {"type": "string"},
                                    "command": {"type": "string"},
                                    "description": {"type": "string"},
                                    "type": {"type": "string"}
                                }
                            }
                        },
                        "timestamp": {"type": "integer"}
                    }
                }
            },
            {
                "name": "execute_command",
                "description": "执行MCDR命令或Minecraft服务器命令，并捕获真实的命令响应",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "要执行的命令，支持MCDR命令(!!开头)或Minecraft命令(可带/前缀)"
                        },
                        "source_type": {
                            "type": "string",
                            "enum": ["console", "player"],
                            "default": "console",
                            "description": "命令来源类型"
                        }
                    },
                    "required": ["command"]
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "command": {"type": "string"},
                        "command_id": {"type": "string"},
                        "output": {"type": "string"},
                        "responses": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "timestamp": {"type": "integer"}
                    }
                }
            },
            {
                "name": "get_server_status",
                "description": "获取MCDR服务器状态信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "include_players": {
                            "type": "boolean",
                            "default": True,
                            "description": "是否包含在线玩家信息"
                        }
                    }
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "timestamp": {"type": "integer"},
                        "mcdr_status": {"type": "string"},
                        "mcdr_status_detail": {"type": "string"},
                        "server_running": {"type": "boolean"},
                        "server_startup": {"type": "boolean"},
                        "plugin_list_detail": {"type": "string"},
                        "players": {
                            "type": "object",
                            "properties": {
                                "list_command_result": {"type": "string"}
                            }
                        }
                    }
                }
            }
        ]
        
        # 获取MCDR自带命令并添加为工具
        mcdr_command_tools = await self._get_mcdr_command_tools()
        tools.extend(mcdr_command_tools)
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools
            }
        }
    
    async def _get_mcdr_command_tools(self) -> List[Dict[str, Any]]:
        """获取MCDR自带命令并将它们转换为MCP工具"""
        # 检查是否启用MCDR命令工具
        if not self.config.get("features", {}).get("mcdr_command_tools", True):
            self.logger.info("MCDR命令工具功能已禁用")
            return []
            
        mcdr_tools = []
        
        try:
            # 获取MCDR命令树
            self.logger.debug("正在获取MCDR命令树...")
            mcdr_commands = await self.command_handler.get_command_tree({"plugin_id": "mcdr"})
            
            # 如果获取成功，处理命令
            if mcdr_commands.get("success", False):
                self.logger.debug(f"成功获取MCDR命令树，共 {len(mcdr_commands.get('commands', []))} 个命令")
                for cmd in mcdr_commands.get("commands", []):
                    try:
                        command = cmd.get("command", "")
                        # 只处理以!!MCDR开头的命令
                        if command.startswith("!!MCDR "):
                            description = cmd.get("description", "MCDR命令")
                            
                            # 创建工具名称
                            tool_name = f"mcdr_{self._command_to_tool_name(command)}"
                            self.logger.debug(f"处理MCDR命令: {command} -> 工具名称: {tool_name}")
                            
                            # 创建一个工具
                            tool = {
                                "name": tool_name,
                                "description": f"{description} (MCDR自带命令)",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                },
                                "outputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean"},
                                        "command": {"type": "string"},
                                        "output": {"type": "string"},
                                        "timestamp": {"type": "integer"}
                                    }
                                },
                                "metadata": {
                                    "mcdr_command": command
                                }
                            }
                            
                            # 添加到工具列表
                            mcdr_tools.append(tool)
                            self.logger.debug(f"添加MCDR命令工具: {tool_name}")
                    except Exception as e:
                        self.logger.error(f"处理MCDR命令时出错: {e}")
            else:
                error = mcdr_commands.get("error", "未知错误")
                self.logger.error(f"获取MCDR命令树失败: {error}")
                
                # 如果主要方法失败，使用备用方法
                self.logger.debug("使用备用方法获取MCDR命令")
                mcdr_tools = self._get_default_mcdr_commands()
            
            # 如果没有找到任何命令，使用备用方法
            if not mcdr_tools:
                self.logger.debug("未找到MCDR命令，使用备用方法")
                mcdr_tools = self._get_default_mcdr_commands()
            
            self.logger.debug(f"已动态添加 {len(mcdr_tools)} 个MCDR命令工具")
            return mcdr_tools
            
        except Exception as e:
            self.logger.error(f"获取MCDR命令工具失败: {e}", exc_info=True)
            # 使用备用方法
            self.logger.debug("使用备用方法获取MCDR命令")
            return self._get_default_mcdr_commands()
    
    def _get_default_mcdr_commands(self) -> List[Dict[str, Any]]:
        """获取默认的MCDR命令工具列表"""
        default_commands = [
            {"command": "!!MCDR status", "description": "查看MCDR状态"},
            {"command": "!!MCDR help", "description": "显示MCDR帮助"},
            {"command": "!!MCDR plugin list", "description": "列出所有插件"},
            {"command": "!!MCDR reload plugin", "description": "重载指定插件"},
            {"command": "!!MCDR reload config", "description": "重载配置文件"},
            {"command": "!!MCDR permission list", "description": "列出权限等级"}
        ]
        
        mcdr_tools = []
        for cmd in default_commands:
            command = cmd["command"]
            description = cmd["description"]
            tool_name = f"mcdr_{self._command_to_tool_name(command)}"
            
            tool = {
                "name": tool_name,
                "description": f"{description} (MCDR自带命令)",
                "inputSchema": {
                    "type": "object",
                    "properties": {}
                },
                "outputSchema": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"},
                        "command": {"type": "string"},
                        "output": {"type": "string"},
                        "timestamp": {"type": "integer"}
                    }
                },
                "metadata": {
                    "mcdr_command": command
                }
            }
            
            mcdr_tools.append(tool)
            
        self.logger.info(f"已创建 {len(mcdr_tools)} 个默认MCDR命令工具")
        return mcdr_tools
    
    def _command_to_tool_name(self, command: str) -> str:
        """将MCDR命令转换为工具名称"""
        # 移除!!MCDR前缀
        name = command.replace("!!MCDR ", "")
        # 替换空格为下划线
        name = name.replace(" ", "_")
        # 移除特殊字符
        name = re.sub(r'[^\w_]', '', name)
        # 确保名称不为空
        if not name:
            name = "command"
        return name
        
    async def _handle_tools_call(self, request_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理tools/call请求"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        
        if tool_name == "get_command_tree":
            result = await self.command_handler.get_command_tree(arguments)
        elif tool_name == "execute_command":
            result = await self.command_handler.execute_command(arguments)
        elif tool_name == "get_server_status":
            result = await self.command_handler.get_server_status(arguments)
        elif tool_name.startswith("mcdr_"):
            # 处理动态MCDR命令工具
            result = await self._handle_mcdr_command_tool(tool_name, arguments)
        else:
            return self._create_error_response(
                request_id, -32601, "Unknown tool", f"Tool '{tool_name}' not found"
            )
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False, indent=2)
                    }
                ]
            }
        }
    
    async def _handle_mcdr_command_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """处理动态MCDR命令工具调用"""
        try:
            self.logger.info(f"处理MCDR命令工具: {tool_name}")
            
            # 尝试从工具名称中提取命令
            command_to_execute = None
            
            # 1. 首先检查是否有缓存的命令映射
            if hasattr(self, '_mcdr_command_mapping') and tool_name in self._mcdr_command_mapping:
                command_to_execute = self._mcdr_command_mapping[tool_name]
                self.logger.debug(f"从缓存中找到命令: {command_to_execute}")
            
            # 2. 如果没有缓存，尝试从MCDR命令树中查找
            if not command_to_execute:
                # 获取MCDR命令树以找到对应的命令
                mcdr_commands = await self.command_handler.get_command_tree({"plugin_id": "mcdr"})
                
                # 创建命令映射缓存（如果不存在）
                if not hasattr(self, '_mcdr_command_mapping'):
                    self._mcdr_command_mapping = {}
                
                # 查找匹配的命令
                for cmd in mcdr_commands.get("commands", []):
                    if cmd.get("command", "").startswith("!!MCDR "):
                        command = cmd.get("command")
                        mapped_tool_name = f"mcdr_{self._command_to_tool_name(command)}"
                        
                        # 添加到缓存
                        self._mcdr_command_mapping[mapped_tool_name] = command
                        
                        if tool_name == mapped_tool_name:
                            command_to_execute = command
                            self.logger.debug(f"从命令树中找到命令: {command_to_execute}")
                            break
            
            # 3. 如果仍然没有找到，尝试从工具名称反向推导命令
            if not command_to_execute:
                # 移除前缀"mcdr_"
                if tool_name.startswith("mcdr_"):
                    command_part = tool_name[5:]
                    # 将下划线替换回空格
                    command_part = command_part.replace("_", " ")
                    # 添加MCDR前缀
                    command_to_execute = f"!!MCDR {command_part}"
                    self.logger.debug(f"从工具名称推导命令: {command_to_execute}")
            
            # 如果找到命令，执行它
            if command_to_execute:
                self.logger.info(f"执行MCDR命令: {command_to_execute}")
                result = await self.command_handler.execute_command({"command": command_to_execute})
                
                # 检查是否为"未知命令"情况
                output = result.get("output", "")
                if output and ("未知命令" in output or "Unknown command" in output):
                    # 如果是工具调用，我们可以提供更友好的错误信息
                    self.logger.info(f"工具 {tool_name} 执行的命令 {command_to_execute} 返回未知命令")
                    
                    # 尝试获取更多信息
                    if "responses" in result:
                        responses = result["responses"]
                        if "当前命令没有返回值，以下是它的子命令" not in output:
                            # 如果没有子命令信息，添加一个友好的提示
                            responses.append(f"工具 {tool_name} 可能需要更多参数，请尝试使用 !!MCDR help 获取帮助")
                            result["output"] = "\n".join(responses)
                
                return result
            else:
                self.logger.error(f"找不到与工具 {tool_name} 对应的MCDR命令")
                return {
                    "success": False,
                    "error": f"找不到与工具 {tool_name} 对应的MCDR命令",
                    "output": ""
                }
                
        except Exception as e:
            self.logger.error(f"执行MCDR命令工具失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "output": ""
            }
    
    async def _handle_resources_list(self, request_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理resources/list请求"""
        resources = [
            {
                "uri": "mcdr://server/status",
                "name": "服务器状态",
                "description": "MCDR服务器的当前状态信息",
                "mimeType": "application/json"
            },
            {
                "uri": "mcdr://commands/tree",
                "name": "命令树",
                "description": "可用命令的完整列表",
                "mimeType": "application/json"
            }
        ]
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": resources
            }
        }
    
    async def _handle_resources_read(self, request_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """处理resources/read请求"""
        uri = params.get("uri", "")
        
        if uri == "mcdr://server/status":
            content = await self.command_handler.get_server_status({})
        elif uri == "mcdr://commands/tree":
            content = await self.command_handler.get_command_tree({})
        else:
            return self._create_error_response(
                request_id, -32601, "Resource not found", f"Resource '{uri}' not found"
            )
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(content, ensure_ascii=False, indent=2)
                    }
                ]
            }
        }
    
    def _create_error_response(self, request_id: Optional[str], code: int, 
                              message: str, data: Any = None) -> Dict[str, Any]:
        """创建错误响应"""
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        
        if data is not None:
            error_response["error"]["data"] = data
            
        return error_response 