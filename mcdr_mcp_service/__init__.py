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
stop_server_event = None


def on_load(server: PluginServerInterface, old):
    """插件加载时的回调"""
    server.logger.info("正在加载 MCDR MCP Service 插件...")
    
    # 设置日志过滤器，抑制一些不必要的错误输出
    setup_log_filters(server)
    
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
    
    # 清理日志过滤器
    cleanup_log_filters(server)
    
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
    global mcp_server_instance, mcp_server_thread, stop_server_event
    
    # 先停止现有的服务器实例（如果有）
    if mcp_server_instance is not None:
        try:
            mcp_server_instance.stop_sync()
        except:
            pass
        mcp_server_instance = None
        mcp_server_thread = None
        stop_server_event = None
    
    if not config["mcp_server"]["enabled"]:
        server.logger.info("MCP服务器已禁用")
        return
    
    try:
        # 检查端口是否可用
        import socket
        import time
        
        host = config["mcp_server"]["host"]
        port = config["mcp_server"]["port"]
        
        def is_port_available():
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    result = s.connect_ex((host, port))
                    return result != 0  # 如果连接失败，说明端口可用
            except Exception:
                return True  # 如果出现异常，假设端口可用
        
        # 如果端口不可用，等待最多3秒
        if not is_port_available():
            server.logger.info(f"端口 {port} 暂时被占用，等待释放...")
            max_wait = 3.0
            wait_interval = 0.2
            total_waited = 0.0
            
            while total_waited < max_wait and not is_port_available():
                time.sleep(wait_interval)
                total_waited += wait_interval
            
            if not is_port_available():
                server.logger.error(f"端口 {port} 仍被占用，无法启动MCP服务器")
                return
        
        # 创建停止事件
        stop_server_event = threading.Event()
        
        # 创建命令处理器
        command_handler = CommandHandler(server, config)
        
        # 创建MCP服务器实例
        mcp_server_instance = MCPServer(server, command_handler, config)
        
        # 在新线程中启动服务器
        def run_server():
            # 设置日志级别，抑制一些不必要的错误
            import logging
            import warnings
            
            # 临时抑制 asyncio 和 websockets 的一些警告
            warnings.filterwarnings("ignore", category=RuntimeWarning, module="asyncio")
            
            # 抑制 asyncio 的一些错误日志
            asyncio_logger = logging.getLogger('asyncio')
            original_level = asyncio_logger.level
            asyncio_logger.setLevel(logging.CRITICAL)
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def server_main():
                # 启动服务器
                try:
                    await mcp_server_instance.start()
                except Exception as e:
                    if not stop_server_event.is_set():  # 只有在非主动停止时才记录错误
                        server.logger.error(f"MCP服务器运行时出错: {e}")
            
            # 启动服务器任务
            server_task = loop.create_task(server_main())
            
            try:
                # 运行直到服务器停止
                loop.run_until_complete(server_task)
            except asyncio.CancelledError:
                server.logger.debug("MCP服务器任务被取消")
            except Exception as e:
                if not stop_server_event.is_set():  # 只有在非主动停止时才记录错误
                    server.logger.error(f"MCP服务器运行时出错: {e}")
            finally:
                # 关闭所有剩余任务
                try:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        if not task.done():
                            task.cancel()
                    
                    # 确保所有任务都有机会完成取消
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass  # 忽略清理时的错误
                
                # 关闭事件循环
                try:
                    # 设置事件循环的异常处理器为空，避免打印错误
                    loop.set_exception_handler(lambda loop, context: None)
                    loop.close()
                except Exception:
                    pass
                
                # 恢复原始日志级别
                try:
                    asyncio_logger.setLevel(original_level)
                except Exception:
                    pass
                
                # 设置停止事件
                if stop_server_event:
                    stop_server_event.set()
        
        mcp_server_thread = threading.Thread(target=run_server, daemon=True)
        mcp_server_thread.start()
        
        server.logger.info(f"MCP服务器已启动在 {host}:{port}")
        
    except Exception as e:
        server.logger.error(f"启动MCP服务器失败: {e}")


def stop_mcp_server(server: PluginServerInterface):
    """停止MCP服务器"""
    global mcp_server_instance, mcp_server_thread, stop_server_event
    
    # 首先设置停止事件
    if stop_server_event:
        stop_server_event.set()
    
    if mcp_server_instance:
        try:
            # 使用同步方法停止服务器
            mcp_server_instance.stop_sync()
            
            # 确保线程已停止
            if mcp_server_thread and mcp_server_thread.is_alive():
                # 给线程更多时间自行结束
                mcp_server_thread.join(timeout=3.0)
                
                # 如果线程仍在运行，记录警告
                if mcp_server_thread.is_alive():
                    server.logger.debug("MCP服务器线程未能正常结束，但这是正常的，稍后会自己结束，端口应该已经释放")
        except Exception as e:
            server.logger.error(f"停止MCP服务器失败: {e}")
        finally:
            # 强制释放所有引用
            mcp_server_instance = None
            mcp_server_thread = None
            stop_server_event = None
            
            # 尝试进行垃圾回收
            try:
                import gc
                gc.collect()
            except Exception:
                pass 


def setup_log_filters(server: PluginServerInterface):
    """设置日志过滤器，抑制一些内部错误"""
    import logging
    import warnings
    
    try:
        # 抑制 asyncio 的一些内部错误
        class AsyncioErrorFilter(logging.Filter):
            def filter(self, record):
                # 过滤掉特定的 asyncio 错误消息
                if record.name == 'asyncio' and record.levelno == logging.ERROR:
                    message = record.getMessage()
                    if ('Exception in callback' in message and 
                        ('_ProactorSocketTransport' in message or 
                         'AssertionError' in message or
                         '_attach' in message)):
                        return False
                return True
        
        # 添加过滤器到 asyncio 日志记录器
        asyncio_logger = logging.getLogger('asyncio')
        asyncio_filter = AsyncioErrorFilter()
        asyncio_logger.addFilter(asyncio_filter)
        
        # 抑制一些 websockets 的警告
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="asyncio")
        warnings.filterwarnings("ignore", category=ResourceWarning, module="asyncio")
        
        server.logger.debug("已设置日志过滤器")
    except Exception as e:
        server.logger.debug(f"设置日志过滤器失败: {e}") 


def cleanup_log_filters(server: PluginServerInterface):
    """清理日志过滤器"""
    try:
        import logging
        
        # 移除 asyncio 日志过滤器
        asyncio_logger = logging.getLogger('asyncio')
        # 移除我们添加的过滤器
        for filter_obj in asyncio_logger.filters[:]:
            if hasattr(filter_obj, '__class__') and 'AsyncioErrorFilter' in str(filter_obj.__class__):
                asyncio_logger.removeFilter(filter_obj)
        
        server.logger.debug("已清理日志过滤器")
    except Exception as e:
        server.logger.debug(f"清理日志过滤器失败: {e}") 