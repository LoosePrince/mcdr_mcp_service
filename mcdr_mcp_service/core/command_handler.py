"""
命令处理器
处理MCP工具调用，包括命令执行、状态查询等功能
"""

import asyncio
import os
import time
import threading
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


class CommandHandler:
    """命令处理器类"""
    
    def __init__(self, server_interface: ServerInterface):
        self.server = server_interface
        self.logger = server_interface.logger
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.command_responses = {}
        self.lock = threading.Lock()
        self.max_history = 100
    
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
            # 获取MCDR命令
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
            
            # 获取Minecraft命令
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
            self.logger.info(f"执行命令: {command} (ID: {command_id})")
            
            # 创建自定义命令源
            cmd_source = LoggingCommandSource(self.server, command_id)
            
            # 存储命令源的响应列表引用
            with self.lock:
                self.command_responses[command_id] = cmd_source.responses
            
            # 执行命令 - 按照command_logger.py的方式
            if command.startswith("!!"):
                # MCDR命令，保持完整命令格式（包括!!前缀）
                self.logger.debug(f"执行MCDR命令: {command}")
                self.server.execute_command(command, source=cmd_source)
            else:
                # Minecraft命令，去掉前导斜杠（如果有）
                if command.startswith("/"):
                    command = command[1:]
                self.server.execute(command)
                cmd_source.responses.append(f"Minecraft命令已执行: {command}")
            
            # 获取响应 - 直接获取，不需要等待
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
    
    def test_command_execution(self) -> Dict[str, Any]:
        """测试命令执行功能"""
        test_results = {
            "timestamp": int(time.time()),
            "tests": []
        }
        
        # 测试MCDR命令
        test_commands = [
            "!!MCDR status",
            "!!MCDR plugin list",
            "/list"
        ]
        
        for cmd in test_commands:
            try:
                result = self._execute_command_sync(cmd)
                test_type = "mcdr_command" if cmd.startswith("!!") else "minecraft_command"
                
                test_results["tests"].append({
                    "command": cmd,
                    "type": test_type,
                    "success": True,
                    "output": result.get("output", "")[:200] + "..." if result.get("output") and len(result.get("output")) > 200 else result.get("output", "")
                })
            except Exception as e:
                test_results["tests"].append({
                    "command": cmd,
                    "type": "mcdr_command" if cmd.startswith("!!") else "minecraft_command",
                    "success": False,
                    "error": str(e)
                })
        
        return test_results 