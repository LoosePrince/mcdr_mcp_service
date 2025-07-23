"""
命令处理器
处理MCP工具调用，包括命令执行、状态查询等功能
"""

import asyncio
import re
import time
import threading
from typing import Dict, Any, List, Optional
from concurrent.futures import ThreadPoolExecutor

from mcdreforged.api.all import *


class ResponseCapturingSource(CommandSource):
    """自定义命令源，用于捕获MCDR命令的响应"""
    
    def __init__(self, server: PluginServerInterface):
        self.__server = server
        self.captured_responses = []  # 用于存储捕获的响应
        self.response_event = threading.Event()  # 用于等待响应完成
        self.response_timeout = 3.0  # 响应超时时间（秒）
    
    @property
    def server(self) -> PluginServerInterface:
        return self.__server
    
    def get_permission_level(self) -> int:
        return 4  # 设置为最高权限级别，确保能执行所有命令
    
    def reply(self, message: Any, **kwargs) -> None:
        """
        重写reply方法，捕获所有响应消息
        """
        message_str = str(message)
        
        # 过滤掉一些系统消息和格式化代码，但保留有用的信息
        if message_str and message_str.strip():
            # 移除MCDR的颜色代码（§开头的代码）
            cleaned_message = self._clean_message(message_str)
            if cleaned_message:
                self.captured_responses.append(cleaned_message)
        
        # 设置事件，表示收到了响应
        self.response_event.set()
    
    def _clean_message(self, message: str) -> str:
        """清理消息，移除颜色代码等格式化字符"""
        import re
        # 移除Minecraft颜色代码 (§后跟一个字符)
        cleaned = re.sub(r'§.', '', message)
        # 移除多余的空白字符
        cleaned = cleaned.strip()
        return cleaned
    
    def get_latest_response(self) -> str:
        """获取最后一条响应"""
        return self.captured_responses[-1] if self.captured_responses else ""
    
    def get_all_responses(self) -> List[str]:
        """获取所有响应"""
        return self.captured_responses.copy()
    
    def get_combined_response(self) -> str:
        """获取合并后的响应"""
        return "\n".join(self.captured_responses)
    
    def clear_responses(self) -> None:
        """清空捕获的响应"""
        self.captured_responses.clear()
        self.response_event.clear()
    
    def wait_for_response(self, timeout: float = None) -> bool:
        """等待响应完成"""
        if timeout is None:
            timeout = self.response_timeout
        return self.response_event.wait(timeout=timeout)


class CommandHandler:
    """命令处理器类"""
    
    def __init__(self, server_interface: PluginServerInterface):
        self.server = server_interface
        self.logger = server_interface.logger
        self.executor = ThreadPoolExecutor(max_workers=2)
    
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
            # 使用MCDR文档中推荐的方式获取命令树
            try:
                # 获取CommandManager和根节点
                command_manager = self.server._mcdr_server.command_manager
                root_nodes = command_manager.root_nodes
                
                # 遍历所有根命令
                for literal, holders in root_nodes.items():
                    for holder in holders:
                        holder_plugin_id = holder.plugin.get_id()
                        
                        # 如果指定了插件ID，只获取该插件的命令
                        if plugin_id and holder_plugin_id != plugin_id:
                            continue
                        
                        commands.append({
                            "plugin_id": holder_plugin_id,
                            "plugin_name": holder.plugin.get_name(),
                            "command": literal,
                            "description": f"{holder.plugin.get_name()}插件的命令",
                            "type": "plugin_command",
                            "has_callback": hasattr(holder.node, '_callback') and holder.node._callback is not None,
                            "has_children": holder.node.has_children()
                        })
                        
                        # 递归获取子命令
                        self._extract_child_commands(holder.node, literal, holder_plugin_id, holder.plugin.get_name(), commands)
                
            except AttributeError:
                # 如果无法访问内部API，使用插件管理器的方式
                self.logger.warning("无法访问命令管理器内部API，使用插件管理器获取插件信息")
                commands = self._get_commands_from_plugins(plugin_id)
            
            # 添加内置MCDR命令
            if not plugin_id or plugin_id == "mcdr":
                builtin_commands = self._get_builtin_commands()
                commands.extend(builtin_commands)
            
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
    
    def _extract_child_commands(self, node, parent_command: str, plugin_id: str, plugin_name: str, commands: List[Dict[str, Any]], depth: int = 1):
        """递归提取子命令"""
        if depth > 3:  # 限制递归深度，避免过深
            return
            
        try:
            children = node.get_children()
            for child in children:
                child_name = str(child)
                full_command = f"{parent_command} {child_name}"
                
                commands.append({
                    "plugin_id": plugin_id,
                    "plugin_name": plugin_name,
                    "command": full_command,
                    "description": f"{plugin_name}插件的子命令",
                    "type": f"plugin_subcommand_level_{depth}",
                    "has_callback": hasattr(child, '_callback') and child._callback is not None,
                    "has_children": child.has_children() if hasattr(child, 'has_children') else False
                })
                
                # 递归处理子命令
                if hasattr(child, 'get_children'):
                    self._extract_child_commands(child, full_command, plugin_id, plugin_name, commands, depth + 1)
        except Exception as e:
            self.logger.debug(f"提取子命令时出错: {e}")
    
    def _get_commands_from_plugins(self, plugin_id: Optional[str]) -> List[Dict[str, Any]]:
        """从插件管理器获取插件命令（备用方法）"""
        commands = []
        
        try:
            # 尝试通过服务器接口获取插件信息
            # 这是一个备用方法，当无法访问内部API时使用
            if hasattr(self.server, 'get_all_plugins'):
                plugins = self.server.get_all_plugins()
            else:
                # 如果没有这个方法，返回基本的插件管理命令
                return self._get_basic_plugin_commands(plugin_id)
                
            for plugin in plugins:
                if plugin_id and plugin.get_id() != plugin_id:
                    continue
                    
                commands.extend(self._extract_plugin_commands(plugin))
                
        except Exception as e:
            self.logger.debug(f"从插件管理器获取命令失败: {e}")
            return self._get_basic_plugin_commands(plugin_id)
            
        return commands
    
    def _get_basic_plugin_commands(self, plugin_id: Optional[str]) -> List[Dict[str, Any]]:
        """获取基本的插件管理命令"""
        if plugin_id and plugin_id != "mcdr":
            return []
            
        return [
            {
                "plugin_id": "mcdr",
                "plugin_name": "MCDReforged Core",
                "command": f"!!MCDR plugin load {plugin_id}" if plugin_id else "!!MCDR plugin load <plugin_id>",
                "description": "加载插件",
                "type": "mcdr_command"
            },
            {
                "plugin_id": "mcdr",
                "plugin_name": "MCDReforged Core", 
                "command": f"!!MCDR plugin unload {plugin_id}" if plugin_id else "!!MCDR plugin unload <plugin_id>",
                "description": "卸载插件",
                "type": "mcdr_command"
            }
        ]

    def _extract_plugin_commands(self, plugin) -> List[Dict[str, Any]]:
        """从插件中提取命令信息"""
        commands = []
        
        try:
            plugin_id = plugin.get_id()
            plugin_name = plugin.get_name()
            
            # 尝试获取插件的命令注册信息
            if hasattr(plugin, 'get_command_root'):
                # 如果插件有命令根节点
                try:
                    command_root = plugin.get_command_root()
                    if command_root:
                        commands.append({
                            "plugin_id": plugin_id,
                            "plugin_name": plugin_name,
                            "command": f"!!{plugin_id}",
                            "description": f"{plugin_name}插件的主命令",
                            "type": "plugin_command"
                        })
                except:
                    pass
            
            # 添加通用插件命令格式
            commands.append({
                "plugin_id": plugin_id,
                "plugin_name": plugin_name,
                "command": f"!!MCDR plugin load {plugin_id}",
                "description": f"加载{plugin_name}插件",
                "type": "mcdr_command"
            })
            
            commands.append({
                "plugin_id": plugin_id,
                "plugin_name": plugin_name,
                "command": f"!!MCDR plugin unload {plugin_id}",
                "description": f"卸载{plugin_name}插件",
                "type": "mcdr_command"
            })
            
            commands.append({
                "plugin_id": plugin_id,
                "plugin_name": plugin_name,
                "command": f"!!MCDR plugin reload {plugin_id}",
                "description": f"重载{plugin_name}插件",
                "type": "mcdr_command"
            })
            
        except Exception as e:
            self.logger.debug(f"提取插件 {plugin} 命令时出错: {e}")
        
        return commands
    
    def _get_builtin_commands(self) -> List[Dict[str, Any]]:
        """获取内置MCDR命令"""
        builtin_commands = [
            {
                "plugin_id": "mcdr",
                "plugin_name": "MCDReforged Core",
                "command": "!!MCDR",
                "description": "MCDReforged主命令",
                "type": "builtin_command"
            },
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
            },
            {
                "plugin_id": "mcdr",
                "plugin_name": "MCDReforged Core",
                "command": "!!MCDR reload",
                "description": "重载MCDR配置",
                "type": "builtin_command"
            },
            {
                "plugin_id": "mcdr",
                "plugin_name": "MCDReforged Core",
                "command": "!!MCDR stop",
                "description": "停止MCDR",
                "type": "builtin_command"
            },
            # Minecraft原版命令示例
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
            },
            {
                "plugin_id": "minecraft",
                "plugin_name": "Minecraft Server",
                "command": "/stop",
                "description": "停止服务器",
                "type": "minecraft_command"
            },
            {
                "plugin_id": "minecraft",
                "plugin_name": "Minecraft Server",
                "command": "/save-all",
                "description": "保存所有世界数据",
                "type": "minecraft_command"
            }
        ]
        
        return builtin_commands
    
    async def execute_command(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行命令"""
        command = arguments.get("command", "").strip()
        source_type = arguments.get("source_type", "console")
        
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
                command,
                source_type
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
    
    def _execute_command_sync(self, command: str, source_type: str) -> Dict[str, Any]:
        """同步执行命令"""
        try:
            self.logger.info(f"执行命令: {command}")
            
            # 根据命令类型分类处理
            if command.startswith("!!"):
                # MCDR命令 - 使用响应捕获功能
                result = self._execute_mcdr_command(command, source_type)
            elif command.startswith("/"):
                # Minecraft命令
                result = self._execute_minecraft_command(command)
            else:
                # 尝试作为Minecraft命令执行
                if not command.startswith("/"):
                    command = "/" + command
                result = self._execute_minecraft_command(command)
            
            return {
                "success": True,
                "command": command,
                "output": result,
                "response_type": "captured" if command.startswith("!!") else "execution_log",
                "timestamp": int(time.time())
            }
            
        except Exception as e:
            self.logger.error(f"执行命令时出错: {e}")
            return {
                "success": False,
                "error": str(e),
                "command": command,
                "output": "",
                "timestamp": int(time.time())
            }
    
    def _execute_mcdr_command(self, command: str, source_type: str) -> str:
        """执行MCDR命令并捕获响应"""
        try:
            # 移除命令前缀
            cmd_content = command[2:].strip()  # 移除 "!!"
            
            # 创建响应捕获源
            capture_source = ResponseCapturingSource(self.server)
            
            self.logger.info(f"执行MCDR命令: !!{cmd_content}")
            
            # 执行MCDR命令
            try:
                self.server.execute_command(cmd_content, capture_source)
            except AttributeError:
                # 如果execute_command方法不存在，尝试备用方法
                self.logger.warning("execute_command方法不可用，尝试备用执行方法")
                # 这里可能需要根据具体MCDR版本调整
                raise Exception("无法找到合适的命令执行方法")
            
            # 等待响应（最多等待3秒）
            response_received = capture_source.wait_for_response(timeout=3.0)
            
            if response_received and capture_source.captured_responses:
                # 获取所有响应
                all_responses = capture_source.get_all_responses()
                combined_response = capture_source.get_combined_response()
                
                self.logger.debug(f"捕获到 {len(all_responses)} 条响应")
                
                return combined_response
            else:
                # 如果没有捕获到响应，返回基本确认信息
                self.logger.warning(f"未能捕获到命令 '{command}' 的响应")
                return f"MCDR命令已执行: {command} (未捕获到响应内容)"
            
        except Exception as e:
            error_msg = f"执行MCDR命令失败: {e}"
            self.logger.error(error_msg)
            raise Exception(error_msg)
    
    def _execute_minecraft_command(self, command: str) -> str:
        """执行Minecraft命令"""
        try:
            # 移除前导斜杠（如果有）
            if command.startswith("/"):
                command = command[1:]
            
            # 通过MCDR执行Minecraft命令
            self.server.execute(command)
            
            return f"Minecraft命令已执行: /{command}"
            
        except Exception as e:
            raise Exception(f"执行Minecraft命令失败: {e}")
    
    async def get_server_status(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """获取服务器状态"""
        include_players = arguments.get("include_players", True)
        
        try:
            # 在线程池中执行同步操作
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                self.executor,
                self._get_server_status_sync,
                include_players
            )
            return result
            
        except Exception as e:
            self.logger.error(f"获取服务器状态失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "status": "unknown"
            }
    
    def _get_server_status_sync(self, include_players: bool) -> Dict[str, Any]:
        """同步获取服务器状态"""
        try:
            # 尝试使用MCDR命令获取详细状态信息
            try:
                status_command_result = self._execute_mcdr_command("!!MCDR status", "console")
                mcdr_status_detail = status_command_result
            except Exception as e:
                self.logger.debug(f"无法通过命令获取MCDR状态: {e}")
                mcdr_status_detail = "无法获取详细状态"

            status_info = {
                "success": True,
                "timestamp": int(time.time()),
                "mcdr_status": "running",
                "mcdr_status_detail": mcdr_status_detail,
                "server_running": self.server.is_server_running(),
                "server_startup": self.server.is_server_startup()
            }
            
            # 尝试获取插件信息
            try:
                # 使用命令获取插件列表
                plugin_list_result = self._execute_mcdr_command("!!MCDR plugin list", "console")
                status_info["plugin_list_detail"] = plugin_list_result
                status_info["plugins_loaded"] = "参见plugin_list_detail"
            except Exception as e:
                self.logger.debug(f"无法通过命令获取插件列表: {e}")
                status_info["plugins_loaded"] = "unknown"
                status_info["plugin_list_detail"] = "无法获取插件列表"
            
            # 如果需要包含玩家信息，尝试使用list命令获取
            if include_players:
                try:
                    # 尝试执行/list命令获取在线玩家
                    list_result = self._execute_minecraft_command("/list")
                    status_info["players"] = {
                        "list_command_result": list_result
                    }
                except Exception as e:
                    self.logger.debug(f"无法获取玩家列表: {e}")
                    status_info["players"] = {
                        "online": "unknown",
                        "max": "unknown",
                        "list": [],
                        "error": str(e)
                    }
            
            return status_info
            
        except Exception as e:
            self.logger.error(f"获取服务器状态时出错: {e}")
            return {
                "success": False,
                "error": str(e),
                "status": "error"
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
                if cmd.startswith("!!"):
                    result = self._execute_mcdr_command(cmd, "console")
                    test_type = "mcdr_command"
                else:
                    result = self._execute_minecraft_command(cmd)
                    test_type = "minecraft_command"
                
                test_results["tests"].append({
                    "command": cmd,
                    "type": test_type,
                    "success": True,
                    "output": result[:200] + "..." if len(result) > 200 else result
                })
            except Exception as e:
                test_results["tests"].append({
                    "command": cmd,
                    "type": test_type if 'test_type' in locals() else "unknown",
                    "success": False,
                    "error": str(e)
                })
        
        return test_results 