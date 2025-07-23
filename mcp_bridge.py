#!/usr/bin/env python3
"""
MCDR MCP Service 桥接器
连接到MCDR MCP WebSocket服务器，提供标准MCP协议接口
"""

import asyncio
import websockets
import json
import sys
import signal
from typing import Dict, Any, Optional

class MCPBridge:
    def __init__(self, uri: str = "ws://127.0.0.1:8765"):
        self.uri = uri
        self.websocket = None
        self.running = True
        
    async def connect_and_bridge(self):
        """连接到MCDR MCP服务器并开始桥接"""
        try:
            async with websockets.connect(self.uri) as websocket:
                self.websocket = websocket
                print(json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {}
                }), file=sys.stderr)
                
                # 启动消息处理循环
                await self.message_loop()
                
        except websockets.exceptions.ConnectionRefused:
            await self.send_error(None, -32603, "Connection refused", 
                                "无法连接到MCDR MCP服务器。请确保MCDR正在运行且插件已加载。")
        except Exception as e:
            await self.send_error(None, -32603, "Connection error", str(e))
    
    async def message_loop(self):
        """消息处理循环"""
        # 创建读取stdin和WebSocket的任务
        stdin_task = asyncio.create_task(self.read_stdin())
        websocket_task = asyncio.create_task(self.read_websocket())
        
        try:
            # 等待任一任务完成
            done, pending = await asyncio.wait(
                [stdin_task, websocket_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # 取消未完成的任务
            for task in pending:
                task.cancel()
                
        except Exception as e:
            await self.send_error(None, -32603, "Message loop error", str(e))
    
    async def read_stdin(self):
        """从stdin读取MCP请求"""
        loop = asyncio.get_event_loop()
        
        while self.running:
            try:
                # 异步读取一行
                line = await loop.run_in_executor(None, sys.stdin.readline)
                
                if not line:  # EOF
                    break
                    
                line = line.strip()
                if not line:
                    continue
                
                # 解析JSON请求
                try:
                    request = json.loads(line)
                    await self.handle_request(request)
                except json.JSONDecodeError as e:
                    await self.send_error(None, -32700, "Parse error", str(e))
                    
            except Exception as e:
                await self.send_error(None, -32603, "Input error", str(e))
                break
    
    async def read_websocket(self):
        """从WebSocket读取响应"""
        try:
            async for message in self.websocket:
                try:
                    response = json.loads(message)
                    await self.send_response(response)
                except json.JSONDecodeError as e:
                    await self.send_error(None, -32700, "WebSocket parse error", str(e))
        except websockets.exceptions.ConnectionClosed:
            await self.send_error(None, -32603, "Connection closed", 
                                "与MCDR MCP服务器的连接已断开")
        except Exception as e:
            await self.send_error(None, -32603, "WebSocket error", str(e))
    
    async def handle_request(self, request: Dict[str, Any]):
        """处理MCP请求"""
        try:
            if self.websocket and not self.websocket.closed:
                await self.websocket.send(json.dumps(request))
            else:
                await self.send_error(
                    request.get("id"), 
                    -32603, 
                    "Connection lost", 
                    "与MCDR MCP服务器的连接已丢失"
                )
        except Exception as e:
            await self.send_error(
                request.get("id"), 
                -32603, 
                "Send error", 
                str(e)
            )
    
    async def send_response(self, response: Dict[str, Any]):
        """发送响应到stdout"""
        try:
            print(json.dumps(response, ensure_ascii=False))
            sys.stdout.flush()
        except Exception as e:
            print(json.dumps({
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32603,
                    "message": "Output error",
                    "data": str(e)
                }
            }), file=sys.stderr)
    
    async def send_error(self, request_id: Optional[str], code: int, 
                        message: str, data: Any = None):
        """发送错误响应"""
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
        
        await self.send_response(error_response)
    
    def stop(self):
        """停止桥接器"""
        self.running = False

def signal_handler(signum, frame):
    """信号处理器"""
    print(json.dumps({
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {}
    }), file=sys.stderr)
    sys.exit(0)

async def main():
    """主函数"""
    # 设置信号处理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 创建并启动桥接器
    bridge = MCPBridge()
    
    try:
        await bridge.connect_and_bridge()
    except KeyboardInterrupt:
        bridge.stop()
        print(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled", 
            "params": {}
        }), file=sys.stderr)
    except Exception as e:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32603,
                "message": "Bridge error",
                "data": str(e)
            }
        }), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 