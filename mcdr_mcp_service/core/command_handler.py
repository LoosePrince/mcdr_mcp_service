"""
命令处理器
处理MCP工具调用，包括命令执行、状态查询等功能
"""

import asyncio
import os
import time
import threading
import re
from typing import Dict, Any, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor

from mcdreforged.api.all import *


class LoggingCommandSource(CommandSource):
    """自定义命令源，用于捕获命令响应"""
    
    def __init__(self, server_interface: ServerInterface, command_id: str):
        self.server = server_interface
        self.command_id = command_id
        self.responses: List[str] = []
        # 不需要事件，直接同步收集响应
    
    def get_server(self):
        return self.server
    
    def get_permission_level(self) -> int:
        return 4  # 最高权限级别
    
    def reply(self, message, **kwargs) -> None:
        # 将响应转换为字符串并存储
        if isinstance(message, RTextBase):
            text = message.to_plain_text()
        else:
            text = str(message)
        
        self.responses.append(text)


class DirectCommandListener:
    """直接命令监听器，用于捕获MC命令输出"""
    
    def __init__(self, command_id: str, patterns: List[str], timeout: float, callback: Optional[Callable] = None):
        self.command_id = command_id
        self.patterns = [re.compile(pattern) for pattern in patterns]
        self.timeout = timeout
        self.callback = callback
        self.responses: List[str] = []
        self.start_time = time.time()
        self.completed = False
    
    def handle_server_output(self, server_output: str) -> bool:
        """处理服务器输出，如果匹配模式则返回True"""
        # 记录所有输出
        self.responses.append(server_output)
        
        # 检查是否超时
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout:
            self.completed = True
            if self.callback:
                self.callback(self.command_id, self.responses)
            return True
        
        # 检查是否匹配结束模式
        for pattern in self.patterns:
            if pattern.search(server_output):
                self.completed = True
                if self.callback:
                    self.callback(self.command_id, self.responses)
                return True
        
        return False
    
    def is_completed(self) -> bool:
        return self.completed


class CommandHandler:
    """命令处理器类"""
    
    def __init__(self, server_interface: ServerInterface, config: Dict[str, Any] = None):
        self.server = server_interface
        self.logger = server_interface.logger
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.command_responses = {}
        self.mc_command_listeners = {}  # 存储MC命令监听器
        self.lock = threading.Lock()
        self.max_history = 100
        self.default_timeout = 10.0
        
        # 配置
        self.config = config or {}
        self.command_tree_max_depth = self.config.get("features", {}).get("command_tree_max_depth", 3)
        
        # 注册服务器输出监听器
        self.server.register_event_listener(MCDRPluginEvents.GENERAL_INFO, self._on_server_output)
    
    def _on_server_output(self, server: ServerInterface, info: Info):
        """处理服务器输出，分发给相应的监听器"""
        # 只处理来自服务器的信息
        if not info.is_from_server:
            return
        
        output = info.raw_content
        
        with self.lock:
            # 创建副本以避免在迭代过程中修改字典
            listeners = list(self.mc_command_listeners.items())
        
        # 检查每个监听器
        for cmd_id, listener in listeners:
            if listener.handle_server_output(output):
                with self.lock:
                    if cmd_id in self.mc_command_listeners:
                        del self.mc_command_listeners[cmd_id]
    
    async def get_command_tree(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """获取命令树"""
        plugin_id = arguments.get("plugin_id")
        
        try:
            # 在线程池中执行同步操作
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor, 
                self._get_command_tree_sync, 
                plugin_id
            )
            return result
        except Exception as e:
            self.logger.error(f"获取命令树失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "commands": []
            }
    
    def _get_command_tree_sync(self, plugin_id: Optional[str]) -> Dict[str, Any]:
        """同步获取命令树"""
        commands = []
        
        try:
            # 获取MCDR命令管理器
            command_manager = self.server._mcdr_server.command_manager
            # 获取所有根节点
            root_nodes = command_manager.root_nodes
            
            # 遍历所有根命令
            for literal, holders in root_nodes.items():
                # 遍历根命令的所有注册指令
                for holder in holders:
                    holder_plugin_id = holder.plugin.get_id()
                    
                    # 如果指定了插件ID，则只返回该插件的命令
                    if plugin_id and holder_plugin_id != plugin_id:
                        continue
                    
                    # 获取命令节点
                    node = holder.node
                    
                    # 解析命令树，使用配置的最大深度
                    self._parse_command_node(commands, holder_plugin_id, literal, node, self.command_tree_max_depth)
            
            # 如果没有找到命令，可能是因为指定的插件ID不存在
            if plugin_id and not commands:
                # 添加一个基础的MCDR命令作为备选
                mcdr_commands = [
                    {
                        "plugin_id": "mcdr",
                        "plugin_name": "MCDReforged Core",
                        "command": "!!MCDR status",
                        "description": "查看MCDR状态",
                        "type": "builtin_command"
                    },
                    {
                        "plugin_id": "mcdr",
                        "plugin_name": "MCDReforged Core",
                        "command": "!!MCDR plugin list",
                        "description": "列出所有插件",
                        "type": "builtin_command"
                    }
                ]
                commands.extend(mcdr_commands)
            
            # 如果没有指定插件ID，添加一些Minecraft命令
            if not plugin_id:
                minecraft_commands = [
                    {
                        "plugin_id": "minecraft",
                        "plugin_name": "Minecraft Server",
                        "command": "/help",
                        "description": "显示帮助信息",
                        "type": "minecraft_command"
                    },
                    {
                        "plugin_id": "minecraft",
                        "plugin_name": "Minecraft Server",
                        "command": "/list",
                        "description": "列出在线玩家",
                        "type": "minecraft_command"
                    }
                ]
                commands.extend(minecraft_commands)
            
            return {
                "success": True,
                "total_commands": len(commands),
                "commands": commands,
                "timestamp": int(time.time())
            }
            
        except Exception as e:
            self.logger.error(f"获取命令树时出错: {e}")
            return {
                "success": False,
                "error": str(e),
                "commands": []
            }
    
    def _parse_command_node(self, commands: List[Dict[str, Any]], plugin_id: str, prefix: str, node, max_depth: int = 3, current_depth: int = 0):
        """递归解析命令节点"""
        # 避免过深的递归
        if current_depth > max_depth:
            return
        
        # 获取插件名称
        plugin_name = "Unknown Plugin"
        try:
            all_plugins = self.server.get_plugin_list()
            for plugin_info in all_plugins:
                if plugin_info.id == plugin_id:
                    plugin_name = plugin_info.name
                    break
        except Exception:
            pass
        
        # 判断节点类型
        from mcdreforged.command.builder.nodes.literal import Literal
        
        # 如果是字面量节点，添加到命令列表
        if isinstance(node, Literal):
            for literal in node.literals:
                command_path = f"{prefix} {literal}" if prefix else literal
                
                # 检查是否有回调函数（表示这是一个可执行命令）
                has_callback = hasattr(node, '_callback') and node._callback is not None
                
                if has_callback:
                    # 获取命令描述
                    description = ""
                    if hasattr(node, 'get_description'):
                        try:
                            description = node.get_description() or ""
                        except Exception:
                            pass
                    
                    # 添加到命令列表
                    commands.append({
                        "plugin_id": plugin_id,
                        "plugin_name": plugin_name,
                        "command": command_path,
                        "description": description,
                        "type": "mcdr_command" if command_path.startswith("!!") else "plugin_command"
                    })
                
                # 递归处理子节点
                for child in node.get_children():
                    self._parse_command_node(commands, plugin_id, command_path, child, max_depth, current_depth + 1)
        else:
            # 对于非字面量节点（如参数节点），直接处理其子节点
            for child in node.get_children():
                self._parse_command_node(commands, plugin_id, prefix, child, max_depth, current_depth + 1)
    
    async def execute_command(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行命令并返回响应"""
        command = arguments.get("command", "").strip()
        
        if not command:
            return {
                "success": False,
                "error": "命令不能为空",
                "output": ""
            }
        
        try:
            # 在线程池中执行命令
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self._execute_command_sync,
                command
            )
            return result
            
        except Exception as e:
            self.logger.error(f"执行命令失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "output": ""
            }
    
    def _execute_command_sync(self, command: str) -> Dict[str, Any]:
        """同步执行命令并捕获响应"""
        command_id = f"cmd_{int(time.time())}_{hash(command) % 10000}"
        
        try:
            # 执行命令 - 按照command_logger.py的方式
            if command.startswith("!!"):
                # MCDR命令，保持完整命令格式（包括!!前缀）
                self.logger.info(f"来自MCP客户端的MCDR命令: {command} (ID: {command_id})")
                
                # 创建自定义命令源
                cmd_source = LoggingCommandSource(self.server, command_id)
                
                # 存储命令源的响应列表引用
                with self.lock:
                    self.command_responses[command_id] = cmd_source.responses
                
                self.server.execute_command(command, source=cmd_source)
                
                # MCDR命令的响应处理 - 直接获取，不需要等待
                responses = cmd_source.responses.copy()
                combined_response = "\n".join(responses)
                
                # 清理过多的历史记录
                self._clean_old_history()
                
                return {
                    "success": True,
                    "command": command,
                    "command_id": command_id,
                    "output": combined_response,
                    "responses": responses,
                    "timestamp": int(time.time())
                }
            else:
                # Minecraft命令，去掉前导斜杠（如果有）
                if command.startswith("/"):
                    command = command[1:]
                
                # 为MC命令创建监听器来捕获输出
                return self._execute_mc_command_sync(command, command_id)
            
        except Exception as e:
            self.logger.error(f"执行命令时出错: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "command_id": command_id,
                "output": "",
                "timestamp": int(time.time())
            }
    
    def _execute_mc_command_sync(self, command: str, command_id: str) -> Dict[str, Any]:
        """同步执行MC命令并捕获响应"""
        try:
            self.logger.info(f"来自MCP客户端的MC命令: {command} (ID: {command_id})")
            
            # 创建默认的结束模式
            end_patterns = [
                r'\[Server\] \[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]',  # [Server] [21:07:42] [Server thread/INFO]:
                r'^\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]',  # 直接以时间开头的格式
                r'Done \(\d+\.\d+s\)!',  # 服务器启动完成消息
                r'Unknown command',  # 未知命令
                r'Usage:',  # 命令用法提示
                r'Syntax error',  # 语法错误
                r'Cannot execute command',  # 无法执行命令
                r'Permission level .* required',  # 权限不足
                r'Player .* not found',  # 玩家未找到
                r'There are \d+ of a max of \d+ players online',  # list命令的输出
            ]
            
            # 创建监听器来捕获MC命令的输出
            listener = DirectCommandListener(
                command_id,
                end_patterns,
                self.default_timeout
            )
            
            with self.lock:
                self.mc_command_listeners[command_id] = listener
                self.command_responses[command_id] = listener.responses
            
            # 执行命令
            self.server.execute(command)
            
            # 等待命令完成或超时
            start_time = time.time()
            while time.time() - start_time < self.default_timeout:
                if listener.is_completed():
                    break
                time.sleep(0.1)
            
            # 收集响应
            responses = listener.responses.copy()
            combined_response = "\n".join(responses)
            
            # 清理监听器
            with self.lock:
                if command_id in self.mc_command_listeners:
                    del self.mc_command_listeners[command_id]
            
            # 清理过多的历史记录
            self._clean_old_history()
            
            return {
                "success": True,
                "command": command,
                "command_id": command_id,
                "output": combined_response,
                "responses": responses,
                "timestamp": int(time.time())
            }
            
        except Exception as e:
            self.logger.error(f"执行MC命令时出错: {e}")
            # 清理监听器
            with self.lock:
                if command_id in self.mc_command_listeners:
                    del self.mc_command_listeners[command_id]
            
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "command_id": command_id,
                "output": "",
                "timestamp": int(time.time())
            }
    
    def _clean_old_history(self) -> None:
        """清理过多的历史记录，保持在最大限制以内"""
        with self.lock:
            if len(self.command_responses) > self.max_history:
                # 按时间排序，保留最新的记录
                sorted_keys = sorted(self.command_responses.keys(), 
                                    key=lambda x: int(x.split('_')[1]) if '_' in x and len(x.split('_')) > 1 else 0)
                # 删除最旧的记录
                to_remove = sorted_keys[:len(sorted_keys) - self.max_history]
                for key in to_remove:
                    del self.command_responses[key]
                    # 同时清理MC命令监听器
                    if key in self.mc_command_listeners:
                        del self.mc_command_listeners[key]
    
    def get_command_response(self, command_id: str) -> Optional[List[str]]:
        """获取命令执行结果"""
        with self.lock:
            return self.command_responses.get(command_id, []).copy() if command_id in self.command_responses else None
    
    async def get_server_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """获取服务器状态"""
        include_players = arguments.get("include_players", True)
        
        try:
            # 执行状态命令
            mcdr_status = await self.execute_command({"command": "!!MCDR status"})
            plugin_list = await self.execute_command({"command": "!!MCDR plugin list"})
            
            status_info = {
                "success": True,
                "timestamp": int(time.time()),
                "mcdr_status": "running",
                "mcdr_status_detail": mcdr_status.get("output", ""),
                "server_running": self.server.is_server_running(),
                "server_startup": self.server.is_server_startup(),
                "plugin_list_detail": plugin_list.get("output", "")
            }
            
            # 如果需要包含玩家信息
            if include_players:
                player_list = await self.execute_command({"command": "/list"})
                status_info["players"] = {
                    "list_command_result": player_list.get("output", "")
                }
            
            return status_info
            
        except Exception as e:
            self.logger.error(f"获取服务器状态失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "status": "unknown"
            }
    
