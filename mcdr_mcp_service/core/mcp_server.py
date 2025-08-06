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
from .tool_definitions import (
    get_mcp_tools, 
    get_default_mcdr_commands, 
    extract_mcdr_subcommand,
    create_mcdr_tool_definition,
    get_default_mcdr_tools
)


class MCPServer:
    """MCP服务器主类"""
    
    def __init__(self, server_interface: PluginServerInterface, command_handler, config: Dict[str, Any]):
        self.server = server_interface
        self.command_handler = command_handler
        self.config = config
        
        # 设置日志
        self.logger = server_interface.logger
        
    async def handle_client(self, websocket: WebSocketServerProtocol, path: str = None):
        """处理客户端连接"""
        client_address = websocket.remote_address
        self.logger.info(f"新的MCP客户端连接: {client_address}")
        
        # 检查IP白名单
        if not self._check_ip_allowed(client_address[0]):
            self.logger.warning(f"拒绝来自 {client_address} 的连接：IP不在白名单中")
            await websocket.close(code=1008, reason="IP not allowed")
            return
        
        # 将客户端添加到全局连接集合中
        import mcdr_mcp_service
        mcdr_mcp_service.connected_clients.add(websocket)
        
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
            # 从全局连接集合中移除客户端
            import mcdr_mcp_service
            mcdr_mcp_service.connected_clients.discard(websocket)
    
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
        # 从工具定义文件获取基础工具列表
        tools = get_mcp_tools()
        
        # 获取所有命令并添加为工具
        command_tools = await self._get_all_command_tools()
        tools.extend(command_tools)
        
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": tools
            }
        }
    
    async def _get_all_command_tools(self) -> List[Dict[str, Any]]:
        """获取所有命令并将它们转换为MCP工具"""
        # 检查是否启用命令工具功能
        if not self.config.get("features", {}).get("command_tools", True):
            self.logger.info("命令工具功能已禁用")
            return []
            
        try:
            # 获取所有命令树
            self.logger.debug("正在获取所有命令树...")
            all_commands = await self.command_handler.get_command_tree({})
            
            # 按命令前缀分组
            command_groups = {}
            
            # 如果获取成功，处理命令
            if all_commands.get("success", False):
                self.logger.debug(f"成功获取命令树，共 {len(all_commands.get('commands', []))} 个命令")
                
                # 处理所有命令
                for cmd in all_commands.get("commands", []):
                    try:
                        command = cmd.get("command", "")
                        description = cmd.get("description", "命令")
                        plugin_id = cmd.get("plugin_id", "unknown")
                        
                        # 提取命令前缀（第一个部分）
                        parts = command.split()
                        if len(parts) >= 1:
                            prefix = parts[0]  # 第一个部分作为前缀
                            
                            # 按前缀分组
                            if prefix not in command_groups:
                                command_groups[prefix] = {
                                    'commands': [],
                                    'descriptions': [],
                                    'subcommands': set()
                                }
                            
                            # 添加到对应分组
                            command_groups[prefix]['commands'].append(command)
                            
                            # 构建描述 - 只显示子命令部分，避免重复前缀
                            if len(parts) >= 2:
                                # 有子命令，显示子命令部分
                                subcommand_part = " ".join(parts[1:])  # 移除前缀，保留其余部分
                                command_groups[prefix]['descriptions'].append(f"{subcommand_part} - {description}")
                            else:
                                # 没有子命令，只显示前缀
                                command_groups[prefix]['descriptions'].append(f"{prefix} - {description}")
                            
                            # 提取子命令（除前缀外的所有部分）
                            if len(parts) >= 2:
                                # 提取除前缀外的所有部分作为子命令
                                subcommand_parts = parts[1:]
                                subcommand = " ".join(subcommand_parts)
                                command_groups[prefix]['subcommands'].add(subcommand)
                            else:
                                # 如果没有子命令，使用前缀本身作为子命令
                                command_groups[prefix]['subcommands'].add(prefix)
                            
                            self.logger.debug(f"收集命令: {command} (插件: {plugin_id})")
                    except Exception as e:
                        self.logger.error(f"处理命令时出错: {e}")
            
            # 为每个命令前缀创建工具
            tools = []
            for prefix, group_data in command_groups.items():
                if group_data['commands']:
                    # 构建工具描述
                    full_description = f"{prefix}命令执行工具，以下是支持的指令：\n"
                    full_description += "\n".join(group_data['descriptions'])
                    full_description += "\n\n参数说明："
                    full_description += "\n- subcommand: 选择要执行的子命令"
                    full_description += "\n- args: 命令参数"
                    
                    # 创建工具定义
                    tool = self._create_command_tool_definition(
                        prefix=prefix,
                        subcommands=list(group_data['subcommands']),
                        description=full_description
                    )
                    
                    tools.append(tool)
                    self.logger.debug(f"已创建 {prefix} 命令工具，包含 {len(group_data['subcommands'])} 个子命令")
            
            # 缓存工具信息以便后续使用
            self._command_tools_cache = tools
            
            if not tools:
                self.logger.warning("未找到任何命令")
                # 使用默认MCDR命令作为备用
                return self._get_default_mcdr_commands()
            
            return tools
            
        except Exception as e:
            self.logger.error(f"获取命令工具失败: {e}", exc_info=True)
            # 使用备用方法
            self.logger.debug("使用备用方法获取命令")
            return self._get_default_mcdr_commands()
    
    def _create_command_tool_definition(self, prefix: str, subcommands: List[str], description: str) -> Dict[str, Any]:
        """创建通用命令工具定义"""
        # 构建输入模式
        input_properties = {}
        
        if subcommands:
            # 如果有子命令列表，提供选择
            input_properties["subcommand"] = {
                "type": "string",
                "enum": subcommands,
                "description": f"可用的{prefix}子命令"
            }
        
        # 添加通用参数
        input_properties["args"] = {
            "type": "string",
            "description": "命令参数（可选）",
            "default": ""
        }
        
        return {
            "name": self._generate_tool_name(prefix),
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": input_properties
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
                "command_prefix": prefix,
                "command_subcommands": subcommands or []
            }
        }
    
    def _generate_tool_name(self, prefix: str) -> str:
        """生成工具名称"""
        # 移除特殊字符并转换为小写
        clean_prefix = prefix.lower()
        clean_prefix = clean_prefix.replace('!!', '').replace('!', '').replace(' ', '_')
        
        # 处理特殊情况
        if clean_prefix == 'mcdr':
            return 'command_mcdr'
        elif clean_prefix.startswith('mcdr'):
            return f'command_{clean_prefix}'
        else:
            return f'command_{clean_prefix}'
    
    def _get_default_mcdr_commands(self) -> List[Dict[str, Any]]:
        """获取默认的MCDR命令工具列表"""
        mcdr_tools = get_default_mcdr_tools()
        self.logger.info(f"已创建 {len(mcdr_tools)} 个默认MCDR命令工具")
        return mcdr_tools
    

        
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
        elif tool_name == "get_recent_logs":
            result = await self.command_handler.get_recent_logs(arguments)
        elif tool_name == "get_logs_range":
            result = await self.command_handler.get_logs_range(arguments)
        elif tool_name == "search_logs":
            result = await self.command_handler.search_logs(arguments)
        elif tool_name == "search_logs_by_ids":
            result = await self.command_handler.search_logs_by_ids(arguments)
        elif tool_name.startswith("command_"):
            # 处理通用命令工具
            result = await self._handle_generic_command_tool(tool_name, arguments)
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
    
    async def _handle_generic_command_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """处理通用命令工具调用"""
        try:
            self.logger.info(f"处理通用命令工具: {tool_name}")
            
            # 从工具名称中提取命令前缀
            # tool_name 格式: command_mcdr, command_plugin, 等
            prefix_part = tool_name.replace("command_", "")
            
            # 从参数中获取子命令和参数
            subcommand = arguments.get("subcommand", "")
            args = arguments.get("args", "")
            
            # 从缓存中获取原始前缀
            original_prefix = None
            if hasattr(self, '_command_tools_cache'):
                for tool in self._command_tools_cache:
                    if tool.get('name') == tool_name:
                        original_prefix = tool.get('metadata', {}).get('command_prefix')
                        break
            
            # 构建完整的命令
            if original_prefix:
                command_to_execute = f"{original_prefix} {subcommand}"
            else:
                # 备用方案：尝试重建前缀
                if prefix_part == "mcdr":
                    command_to_execute = f"!!MCDR {subcommand}"
                elif prefix_part.startswith("!"):
                    command_to_execute = f"{prefix_part} {subcommand}"
                else:
                    command_to_execute = f"!!{prefix_part.upper()} {subcommand}"
            
            if args:
                command_to_execute += f" {args}"
            
            self.logger.info(f"执行命令: {command_to_execute}")
            result = await self.command_handler.execute_command({"command": command_to_execute})
            
            # 检查是否为"未知命令"情况
            output = result.get("output", "")
            if output and ("未知命令" in output or "Unknown command" in output):
                self.logger.info(f"工具 {tool_name} 执行的命令 {command_to_execute} 返回未知命令")
                
                # 尝试获取更多信息
                if "responses" in result:
                    responses = result["responses"]
                    if "当前命令没有返回值，以下是它的子命令" not in output:
                        responses.append(f"工具 {tool_name} 可能需要更多参数，请尝试使用 help 命令获取帮助")
                        result["output"] = "\n".join(responses)
            
            return result
                
        except Exception as e:
            self.logger.error(f"执行通用命令工具失败: {e}", exc_info=True)
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