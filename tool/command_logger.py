import os
import time
import threading
import re
import queue
from typing import List, Optional, Dict, Any, Callable, Tuple, Set

from mcdreforged.api.all import *
from mcdreforged.command.command_source import CommandSource
# 修复导入路径，使用mcdreforged.api.all中的ServerInterface
# from mcdreforged.plugin.server_interface import ServerInterface

PLUGIN_METADATA = {
    'id': 'command_logger',
    'version': '1.1.0',
    'name': 'Command Logger',
    'description': '提供接口执行指定的命令并记录响应到log.txt',
    'author': 'AI Assistant',
    'dependencies': {
        'mcdreforged': '>=2.0.0'
    }
}

# 存储命令响应的字典
command_responses: Dict[str, List[str]] = {}
# 存储等待响应的命令
waiting_commands: Dict[str, Dict[str, Any]] = {}
# 存储直接命令的响应监听器
direct_command_listeners: Dict[str, Dict[str, Any]] = {}
# 日志文件路径
log_file_path = os.path.join('test', 'log.txt')
# 最大保存的命令历史数量
MAX_HISTORY = 100
# 锁对象，用于线程安全操作
lock = threading.Lock()
# 默认超时时间(秒)
DEFAULT_TIMEOUT = 10

# 自定义命令源，用于捕获命令响应
class LoggingCommandSource(CommandSource):
    def __init__(self, server_interface: ServerInterface, command_id: str, callback: Optional[Callable] = None):
        self.server = server_interface
        self.command_id = command_id
        self.responses: List[str] = []
        self.callback = callback
        with lock:
            command_responses[command_id] = self.responses

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
        
        with lock:
            self.responses.append(text)
        
        # 记录到日志文件
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(f"[{self.command_id}] {text}\n")
        
        # 如果有回调函数，调用它
        if self.callback:
            self.callback(self.command_id, text)

# 直接命令执行器，用于直接执行MC命令并捕获输出
class DirectCommandListener:
    def __init__(self, command_id: str, patterns: List[str], timeout: float, callback: Optional[Callable] = None):
        self.command_id = command_id
        self.patterns = [re.compile(pattern) for pattern in patterns]
        self.timeout = timeout
        self.callback = callback
        self.responses: List[str] = []
        self.start_time = time.time()
        self.completed = False
        self.response_queue = queue.Queue()
        
        with lock:
            command_responses[command_id] = self.responses
            direct_command_listeners[command_id] = self
        
        # 记录监听器创建
        # with open(log_file_path, 'a', encoding='utf-8') as f:
        #     f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 创建监听器: {command_id}, 模式: {[p.pattern for p in self.patterns]}, 超时: {timeout}s\n")
    
    def handle_server_output(self, server_output: str) -> bool:
        """处理服务器输出，如果匹配模式则返回True"""
        # 记录所有输出
        self.responses.append(server_output)
        
        # 记录到日志文件
        with open(log_file_path, 'a', encoding='utf-8') as f:
            f.write(f"[{self.command_id}] 收到输出: {server_output}\n")
        
        # 检查是否超时
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout:
            self.completed = True
            with open(log_file_path, 'a', encoding='utf-8') as f:
                f.write(f"[{self.command_id}] 超时完成 ({elapsed:.2f}s)\n")
            if self.callback:
                self.callback(self.command_id, self.responses)
            return True
        
        # 检查是否匹配结束模式
        for i, pattern in enumerate(self.patterns):
            if pattern.search(server_output):
                self.completed = True
                # with open(log_file_path, 'a', encoding='utf-8') as f:
                #     f.write(f"[{self.command_id}] 模式匹配完成: 模式{i+1} '{pattern.pattern}' 匹配 '{server_output}'\n")
                if self.callback:
                    self.callback(self.command_id, self.responses)
                return True
        
        return False
    
    def is_completed(self) -> bool:
        return self.completed

def on_load(server: ServerInterface, old):
    # 确保日志文件存在
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 插件已加载\n")
    
    # 注册事件监听器，用于捕获服务器输出
    server.register_event_listener(MCDRPluginEvents.GENERAL_INFO, on_server_output)
    
    # 注册命令
    server.register_command(
        Literal('!!cmdlog')
        .requires(lambda src: src.has_permission(3))  # 需要管理员权限
        .then(
            Literal('exec')
            .then(
                GreedyText('command')
                .runs(lambda src, ctx: execute_command_and_reply(src, server, ctx['command']))
            )
        )
        .then(
            Literal('mc')
            .then(
                GreedyText('command')
                .runs(lambda src, ctx: execute_mc_command_and_reply(src, server, ctx['command']))
            )
        )
        .then(
            Literal('get')
            .then(
                Text('command_id')
                .runs(lambda src, ctx: get_command_response(src, ctx['command_id']))
            )
        )
        .then(
            Literal('list')
            .runs(lambda src: list_commands(src))
        )
        .then(
            Literal('clear')
            .runs(lambda src: clear_history(src))
        )
        .then(
            Literal('help')
            .runs(lambda src: show_help(src))
        )
    )

def on_server_output(server: ServerInterface, info: Info):
    """处理服务器输出，分发给相应的监听器"""
    # 只处理来自服务器的信息
    if not info.is_from_server:
        return
    
    output = info.raw_content
    
    with lock:
        # 创建副本以避免在迭代过程中修改字典
        listeners = list(direct_command_listeners.items())
    
    # 检查每个监听器
    for cmd_id, listener in listeners:
        if listener.handle_server_output(output):
            with lock:
                if cmd_id in direct_command_listeners:
                    del direct_command_listeners[cmd_id]

def execute_command_and_reply(source: CommandSource, server: ServerInterface, command: str):
    """
    执行命令并向源发送命令ID
    """
    cmd_id = execute_command(server, command)
    source.reply(f"命令已执行，ID: {cmd_id}")
    return cmd_id

def execute_mc_command_and_reply(source: CommandSource, server: ServerInterface, command: str):
    """
    执行MC命令并向源发送命令ID
    """
    cmd_id = execute_mc_command(server, command)
    source.reply(f"MC命令已执行，ID: {cmd_id}")
    return cmd_id

def execute_command(server: ServerInterface, command: str, callback: Optional[Callable] = None) -> str:
    """
    执行命令并返回命令ID
    """
    command_id = f"cmd_{int(time.time())}_{hash(command) % 10000}"
    
    # 创建自定义命令源
    cmd_source = LoggingCommandSource(server, command_id, callback)
    
    # 记录命令执行
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 执行命令: {command} (ID: {command_id})\n")
    
    # 执行命令
    server.execute_command(command, source=cmd_source)
    
    # 清理过多的历史记录
    clean_old_history()
    
    return command_id

def execute_mc_command(server: ServerInterface, command: str, 
                      end_patterns: Optional[List[str]] = None, 
                      timeout: float = DEFAULT_TIMEOUT,
                      callback: Optional[Callable] = None) -> str:
    """
    直接执行MC命令并返回命令ID
    
    :param server: ServerInterface实例
    :param command: 要执行的MC命令
    :param end_patterns: 结束模式列表，匹配到任一模式则认为命令执行完成
    :param timeout: 超时时间(秒)
    :param callback: 回调函数，格式: callback(command_id: str, responses: List[str])
    :return: 命令ID
    """
    command_id = f"mc_{int(time.time())}_{hash(command) % 10000}"
    
    # 如果没有提供结束模式，使用默认模式
    if end_patterns is None:
        # 修改默认模式以匹配实际的服务器输出格式
        end_patterns = [
            r'\[Server\] \[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]',  # [Server] [21:07:42] [Server thread/INFO]:
            r'^\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]',  # 直接以时间开头的格式
            r'Done \(\d+\.\d+s\)!',  # 服务器启动完成消息
            r'Unknown command',  # 未知命令
            r'Usage:',  # 命令用法提示
            r'Syntax error',  # 语法错误
            r'Cannot execute command',  # 无法执行命令
        ]
    
    # 创建监听器
    listener = DirectCommandListener(command_id, end_patterns, timeout, callback)
    
    # 记录命令执行
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 执行MC命令: {command} (ID: {command_id})\n")
    
    # 执行命令
    server.execute(command)
    
    # 清理过多的历史记录
    clean_old_history()
    
    return command_id

def execute_command_async(server: ServerInterface, command: str, callback: Optional[Callable] = None) -> str:
    """
    异步执行命令，避免阻塞主线程
    """
    command_id = f"async_{int(time.time())}_{hash(command) % 10000}"
    
    # 记录命令执行
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 异步执行命令: {command} (ID: {command_id})\n")
    
    # 创建一个线程来执行命令
    def run_command():
        cmd_source = LoggingCommandSource(server, command_id, callback)
        server.execute_command(command, source=cmd_source)
    
    thread = threading.Thread(target=run_command, name=f"CommandExec-{command_id}")
    thread.daemon = True
    thread.start()
    
    return command_id

def execute_mc_command_async(server: ServerInterface, command: str, 
                           end_patterns: Optional[List[str]] = None,
                           timeout: float = DEFAULT_TIMEOUT,
                           callback: Optional[Callable] = None) -> str:
    """
    异步执行MC命令，避免阻塞主线程
    
    :param server: ServerInterface实例
    :param command: 要执行的MC命令
    :param end_patterns: 结束模式列表，匹配到任一模式则认为命令执行完成
    :param timeout: 超时时间(秒)
    :param callback: 回调函数，格式: callback(command_id: str, responses: List[str])
    :return: 命令ID
    """
    command_id = f"async_mc_{int(time.time())}_{hash(command) % 10000}"
    
    # 记录命令执行
    with open(log_file_path, 'a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 异步执行MC命令: {command} (ID: {command_id})\n")
    
    # 如果没有提供结束模式，使用默认模式
    if end_patterns is None:
        # 修改默认模式以匹配实际的服务器输出格式
        end_patterns = [
            r'\[Server\] \[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]',  # [Server] [21:07:42] [Server thread/INFO]:
            r'^\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]',  # 直接以时间开头的格式
            r'Done \(\d+\.\d+s\)!',  # 服务器启动完成消息
            r'Unknown command',  # 未知命令
            r'Usage:',  # 命令用法提示
            r'Syntax error',  # 语法错误
            r'Cannot execute command',  # 无法执行命令
        ]
    
    # 创建一个线程来执行命令
    def run_command():
        # 创建监听器
        listener = DirectCommandListener(command_id, end_patterns, timeout, callback)
        # 执行命令
        server.execute(command)
    
    thread = threading.Thread(target=run_command, name=f"MCCommandExec-{command_id}")
    thread.daemon = True
    thread.start()
    
    return command_id

def get_command_response(source: CommandSource, command_id: str) -> None:
    """
    获取命令响应并发送给请求者
    """
    with lock:
        if command_id in command_responses:
            responses = command_responses[command_id].copy()
            source.reply(f"命令 {command_id} 的响应:")
            for line in responses:
                source.reply(line)
        else:
            source.reply(f"找不到命令ID: {command_id}")

def list_commands(source: CommandSource) -> None:
    """
    列出所有已执行的命令
    """
    with lock:
        if not command_responses:
            source.reply("没有命令历史记录")
            return
        
        source.reply("命令历史记录:")
        for cmd_id in command_responses.keys():
            resp_count = len(command_responses[cmd_id])
            source.reply(f"- {cmd_id}: {resp_count} 条响应")

def clear_history(source: CommandSource) -> None:
    """
    清除命令历史记录
    """
    with lock:
        command_responses.clear()
        direct_command_listeners.clear()
    source.reply("命令历史记录已清除")

def clean_old_history() -> None:
    """
    清理过多的历史记录，保持在最大限制以内
    """
    with lock:
        if len(command_responses) > MAX_HISTORY:
            # 按时间排序，保留最新的记录
            sorted_keys = sorted(command_responses.keys(), 
                                key=lambda x: int(x.split('_')[1]) if '_' in x and len(x.split('_')) > 1 else 0)
            # 删除最旧的记录
            to_remove = sorted_keys[:len(sorted_keys) - MAX_HISTORY]
            for key in to_remove:
                del command_responses[key]
                if key in direct_command_listeners:
                    del direct_command_listeners[key]

def show_help(source: CommandSource) -> None:
    """
    显示帮助信息
    """
    source.reply("§6CommandLogger 帮助：")
    source.reply("§7!!cmdlog exec <命令> §f- 执行MCDR命令并记录响应")
    source.reply("§7!!cmdlog mc <命令> §f- 执行MC命令并记录响应")
    source.reply("§7!!cmdlog get <命令ID> §f- 获取命令响应")
    source.reply("§7!!cmdlog list §f- 列出所有命令历史")
    source.reply("§7!!cmdlog clear §f- 清除命令历史")
    source.reply("§7!!cmdlog help §f- 显示此帮助信息")

# API接口，供其他插件使用
def execute_command_and_log(server: ServerInterface, command: str, callback: Optional[Callable] = None) -> str:
    """
    执行MCDR命令并记录响应，返回命令ID
    回调函数格式: callback(command_id: str, response: str)
    """
    return execute_command(server, command, callback)

def execute_command_async_and_log(server: ServerInterface, command: str, callback: Optional[Callable] = None) -> str:
    """
    异步执行MCDR命令并记录响应，返回命令ID
    回调函数格式: callback(command_id: str, response: str)
    """
    return execute_command_async(server, command, callback)

def execute_mc_command_and_log(server: ServerInterface, command: str, 
                             end_patterns: Optional[List[str]] = None,
                             timeout: float = DEFAULT_TIMEOUT,
                             callback: Optional[Callable] = None) -> str:
    """
    执行MC命令并记录响应，返回命令ID
    
    :param server: ServerInterface实例
    :param command: 要执行的MC命令
    :param end_patterns: 结束模式列表，匹配到任一模式则认为命令执行完成
    :param timeout: 超时时间(秒)
    :param callback: 回调函数，格式: callback(command_id: str, responses: List[str])
    :return: 命令ID
    """
    return execute_mc_command(server, command, end_patterns, timeout, callback)

def execute_mc_command_async_and_log(server: ServerInterface, command: str, 
                                  end_patterns: Optional[List[str]] = None,
                                  timeout: float = DEFAULT_TIMEOUT,
                                  callback: Optional[Callable] = None) -> str:
    """
    异步执行MC命令并记录响应，返回命令ID
    
    :param server: ServerInterface实例
    :param command: 要执行的MC命令
    :param end_patterns: 结束模式列表，匹配到任一模式则认为命令执行完成
    :param timeout: 超时时间(秒)
    :param callback: 回调函数，格式: callback(command_id: str, responses: List[str])
    :return: 命令ID
    """
    return execute_mc_command_async(server, command, end_patterns, timeout, callback)

def get_command_result(command_id: str) -> Optional[List[str]]:
    """
    获取命令执行结果
    """
    with lock:
        return command_responses.get(command_id, []).copy() if command_id in command_responses else None 

def wait_for_command_result(command_id: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[List[str]]:
    """
    等待并获取命令执行结果
    
    :param command_id: 命令ID
    :param timeout: 超时时间(秒)
    :return: 命令执行结果，如果超时或命令不存在则返回None
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        with lock:
            if command_id in command_responses:
                if command_id not in direct_command_listeners or direct_command_listeners[command_id].is_completed():
                    return command_responses[command_id].copy()
        time.sleep(0.1)
    return None 