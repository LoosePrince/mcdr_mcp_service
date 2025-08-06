"""
MCP工具定义和默认MCDR命令
包含所有MCP协议工具的定义和默认的MCDR命令列表
"""

from typing import Dict, Any, List


# 默认的MCDR命令列表
DEFAULT_MCDR_COMMANDS = [
    {"command": "!!MCDR status", "description": "查看MCDR状态"},
    {"command": "!!MCDR help", "description": "显示MCDR帮助"},
    {"command": "!!MCDR plugin list", "description": "列出所有插件"},
    {"command": "!!MCDR reload plugin", "description": "重载指定插件"},
    {"command": "!!MCDR reload config", "description": "重载配置文件"},
    {"command": "!!MCDR permission list", "description": "列出权限等级"}
]


# MCP工具定义
MCP_TOOLS = [
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
    },
    {
        "name": "get_recent_logs",
        "description": "获取最近的服务器日志（支持MCDR和Minecraft日志）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lines_count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 20,
                    "description": "要获取的日志行数，最大50行"
                }
            }
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "total_lines": {"type": "integer"},
                "requested_lines": {"type": "integer"},
                "returned_lines": {"type": "integer"},
                "logs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "line_number": {"type": "integer"},
                            "content": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "source": {"type": "string"},
                            "is_command": {"type": "boolean"}
                        }
                    }
                },
                "timestamp": {"type": "integer"}
            }
        }
    },
    {
        "name": "get_logs_range",
        "description": "获取指定范围的服务器日志（支持MCDR和Minecraft日志）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_line": {
                    "type": "integer",
                    "minimum": 0,
                    "default": 0,
                    "description": "起始行号（从0开始）"
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "结束行号（不包含），最多获取50行"
                }
            },
            "required": ["end_line"]
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "total_lines": {"type": "integer"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
                "requested_lines": {"type": "integer"},
                "returned_lines": {"type": "integer"},
                "logs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "line_number": {"type": "integer"},
                            "content": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "source": {"type": "string"},
                            "is_command": {"type": "boolean"}
                        }
                    }
                },
                "timestamp": {"type": "integer"}
            }
        }
    },
    {
        "name": "search_logs",
        "description": "搜索日志内容，支持文本搜索和正则表达式搜索",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询字符串"
                },
                "use_regex": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否使用正则表达式搜索"
                },
                "context_lines": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 0,
                    "description": "包含搜索结果的上下文行数"
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 5,
                    "description": "最大返回结果数"
                }
            },
            "required": ["query"]
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "query": {"type": "string"},
                "use_regex": {"type": "boolean"},
                "context_lines": {"type": "integer"},
                "total_matches": {"type": "integer"},
                "returned_results": {"type": "integer"},
                "remaining_results": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "search_id": {"type": "integer"},
                            "line_number": {"type": "integer"},
                            "content": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "is_command": {"type": "boolean"},
                            "context_before": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line_number": {"type": "integer"},
                                        "content": {"type": "string"}
                                    }
                                }
                            },
                            "context_after": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line_number": {"type": "integer"},
                                        "content": {"type": "string"}
                                    }
                                }
                            },
                            "match_index": {"type": "integer"}
                        }
                    }
                },
                "timestamp": {"type": "integer"}
            }
        }
    },
    {
        "name": "search_logs_by_ids",
        "description": "根据搜索ID范围查询日志",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_id": {
                    "type": "integer",
                    "description": "起始搜索ID"
                },
                "end_id": {
                    "type": "integer",
                    "description": "结束搜索ID"
                },
                "context_lines": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "default": 0,
                    "description": "包含搜索结果的上下文行数"
                }
            },
            "required": ["start_id", "end_id"]
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "start_id": {"type": "integer"},
                "end_id": {"type": "integer"},
                "context_lines": {"type": "integer"},
                "total_matches": {"type": "integer"},
                "returned_results": {"type": "integer"},
                "remaining_results": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "search_id": {"type": "integer"},
                            "line_number": {"type": "integer"},
                            "content": {"type": "string"},
                            "timestamp": {"type": "string"},
                            "is_command": {"type": "boolean"},
                            "context_before": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line_number": {"type": "integer"},
                                        "content": {"type": "string"}
                                    }
                                }
                            },
                            "context_after": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "line_number": {"type": "integer"},
                                        "content": {"type": "string"}
                                    }
                                }
                            },
                            "match_index": {"type": "integer"}
                        }
                    }
                },
                "timestamp": {"type": "integer"}
            }
        }
    }
]


def get_mcp_tools() -> List[Dict[str, Any]]:
    """获取MCP工具列表"""
    return MCP_TOOLS.copy()


def get_default_mcdr_commands() -> List[Dict[str, Any]]:
    """获取默认的MCDR命令列表"""
    return DEFAULT_MCDR_COMMANDS.copy()


def extract_mcdr_subcommand(command: str) -> str:
    """从MCDR命令中提取子命令部分"""
    if command.startswith("!!MCDR "):
        return command[7:]  # 移除 "!!MCDR " 前缀
    return ""


def create_mcdr_tool_definition(subcommand: str = "", description: str = "", subcommands: List[str] = None) -> Dict[str, Any]:
    """创建MCDR工具定义"""
    # 构建输入模式
    input_properties = {}
    
    if subcommand:
        # 如果有子命令，将其作为固定参数
        input_properties["subcommand"] = {
            "type": "string",
            "description": f"子命令: {subcommand}",
            "default": subcommand
        }
    
    if subcommands:
        # 如果有子命令列表，提供选择
        input_properties["subcommand"] = {
            "type": "string",
            "enum": subcommands,
            "description": "可用的子命令"
        }
    
    # 添加通用参数
    input_properties["args"] = {
        "type": "string",
        "description": "命令参数（可选）。根据子命令不同，参数也不同：\n- plugin: 插件名称\n- reload: plugin <插件名> 或 config\n- permission: list, q <玩家名>, query <玩家名>\n- debug: command_dump all, thread_dump\n- status: 无需参数\n- help: 无需参数",
        "default": ""
    }
    
    # 构建描述 - 直接使用传入的描述，不再添加额外信息
    full_description = description if description else "MCDR命令执行工具"
    
    return {
        "name": "mcdr",
        "description": full_description,
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
            "mcdr_subcommand": subcommand,
            "mcdr_subcommands": subcommands or []
        }
    }


def get_mcdr_tool_definition() -> Dict[str, Any]:
    """获取MCDR工具定义"""
    return create_mcdr_tool_definition()


def get_default_mcdr_tools() -> List[Dict[str, Any]]:
    """获取默认的MCDR命令工具列表"""
    # 现在只返回一个统一的MCDR工具
    return [get_mcdr_tool_definition()] 