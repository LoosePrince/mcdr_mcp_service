"""
MCDR MCP Service Plugin
为AI提供MCP协议接口的MCDR控制服务
"""

import asyncio
import threading
import json
from pathlib import Path
from typing import Dict, Any

from mcdreforged.api.all import *

from .core.mcp_server import MCPServer
from .core.command_handler import CommandHandler

# 全局变量
mcp_server_instance = None
mcp_server_thread = None


def on_load(server: PluginServerInterface, old):
    """插件加载时的回调"""
    server.logger.info("正在加载 MCDR MCP Service 插件...")
    
    # 加载配置
    config_path = Path(server.get_data_folder()) / "config.json"
    config = load_config(server, config_path)
    
    # 启动MCP服务器
    start_mcp_server(server, config)
    
    server.logger.info("MCDR MCP Service 插件加载完成")


def on_unload(server: PluginServerInterface):
    """插件卸载时的回调"""
    server.logger.info("正在卸载 MCDR MCP Service 插件...")
    
    # 停止MCP服务器
    stop_mcp_server(server)
    
    server.logger.info("MCDR MCP Service 插件卸载完成")


def load_config(server: PluginServerInterface, config_path: Path) -> Dict[str, Any]:
    """加载配置文件"""
    default_config = {
        "mcp_server": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8765,
            "max_connections": 5
        },
        "security": {
            "require_authentication": False,
            "api_key": "",
            "allowed_ips": ["127.0.0.1"]
        },
        "logging": {
            "level": "INFO"
        }
    }
    
    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # 合并默认配置
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
        else:
            config = default_config
            # 创建默认配置文件
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            server.logger.info(f"已创建默认配置文件: {config_path}")
            
        return config
    except Exception as e:
        server.logger.error(f"加载配置文件失败: {e}")
        return default_config


def start_mcp_server(server: PluginServerInterface, config: Dict[str, Any]):
    """启动MCP服务器"""
    global mcp_server_instance, mcp_server_thread
    
    # 先停止现有的服务器实例（如果有）
    if mcp_server_instance is not None:
        try:
            mcp_server_instance.stop_sync()
        except:
            pass
        mcp_server_instance = None
        mcp_server_thread = None
    
    if not config["mcp_server"]["enabled"]:
        server.logger.info("MCP服务器已禁用")
        return
    
    try:
        # 创建命令处理器
        command_handler = CommandHandler(server)
        
        # 创建MCP服务器实例
        mcp_server_instance = MCPServer(server, command_handler, config)
        
        # 在新线程中启动服务器
        def run_server():
            asyncio.set_event_loop(asyncio.new_event_loop())
            loop = asyncio.get_event_loop()
            try:
                loop.run_until_complete(mcp_server_instance.start())
            except Exception as e:
                server.logger.error(f"MCP服务器运行时出错: {e}")
            finally:
                loop.close()
        
        mcp_server_thread = threading.Thread(target=run_server, daemon=True)
        mcp_server_thread.start()
        
        host = config["mcp_server"]["host"]
        port = config["mcp_server"]["port"]
        server.logger.info(f"MCP服务器已启动在 {host}:{port}")
        
    except Exception as e:
        server.logger.error(f"启动MCP服务器失败: {e}")


def stop_mcp_server(server: PluginServerInterface):
    """停止MCP服务器"""
    global mcp_server_instance, mcp_server_thread
    
    if mcp_server_instance:
        try:
            # 使用同步方法停止服务器
            mcp_server_instance.stop_sync()
        except Exception as e:
            server.logger.error(f"停止MCP服务器失败: {e}")
        finally:
            mcp_server_instance = None
            mcp_server_thread = None 