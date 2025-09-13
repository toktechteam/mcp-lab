#!/usr/bin/env python3
"""
agent.py - MCP-Compatible AI Agent (Updated for OpenAI 1.52+)
Educational Lab 6.1: Agent Protocols and Standards

Compatible with:
- Python 3.11-3.12
- openai>=1.52.0
- Works with simplified MCP protocol

This implements an AI agent that connects to MCP servers
and demonstrates agent protocol patterns and safety controls.
"""

import asyncio
import json
import logging
import sys
from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
import uuid
from datetime import datetime
import os
from pathlib import Path

# Check and import dependencies
def check_dependencies():
    """Check and import required dependencies"""
    missing_deps = []
    
    try:
        import openai
        # Check for client class (new API structure in 1.52+)
        if not hasattr(openai, 'OpenAI'):
            missing_deps.append("openai>=1.52.0 (current version is too old)")
    except ImportError:
        missing_deps.append("openai>=1.52.0")
    
    if missing_deps:
        print("❌ Missing required dependencies:")
        for dep in missing_deps:
            print(f"   pip install {dep}")
        sys.exit(1)
    
    return openai

# Check dependencies and import
openai = check_dependencies()
from openai import OpenAI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class AgentContext:
    """Agent conversation context and state"""
    session_id: str
    user: str
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    current_namespace: str = "default"
    tools_used: List[str] = field(default_factory=list)

class SimpleMCPClient:
    """
    Simplified MCP client that communicates via subprocess stdio
    This avoids complex MCP SDK dependencies while demonstrating the protocol
    """
    
    def __init__(self, server_command: List[str]):
        self.server_command = server_command
        self.process = None
        self.request_id = 0
    
    async def start(self):
        """Start the MCP server subprocess"""
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.server_command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            logger.info(f"Started MCP server: {' '.join(self.server_command)}")
            
            # Initialize the MCP session
            await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "DevOps-Agent",
                    "version": "2.0.0"
                }
            })
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False
    
    async def _send_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server"""
        if not self.process:
            raise RuntimeError("MCP server not started")
        
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": str(self.request_id)
        }
        
        if params:
            request["params"] = params
        
        # Send request
        request_json = json.dumps(request) + "\n"
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()
        
        # Read response
        response_line = await self.process.stdout.readline()
        if not response_line:
            raise RuntimeError("No response from MCP server")
        
        try:
            response = json.loads(response_line.decode().strip())
            if "error" in response:
                raise RuntimeError(f"MCP error: {response['error']}")
            
            return response.get("result", {})
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response: {response_line}")
            raise RuntimeError(f"Invalid response from server: {e}")
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools"""
        result = await self._send_request("tools/list")
        return result.get("tools", [])
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Call a tool"""
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        return result.get("content", [])
    
    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources"""
        try:
            result = await self._send_request("resources/list")
            return result.get("resources", [])
        except:
            return []  # Resources are optional
    
    async def stop(self):
        """Stop the MCP server"""
        if self.process:
            self.process.terminate()
            await self.process.wait()

class MCPAgent:
    """
    AI Agent that demonstrates MCP protocol usage for DevOps operations.
    Updated for OpenAI 1.52+ API
    
    This agent showcases:
    - MCP tool discovery and capability negotiation
    - Safe tool execution with context management
    - LLM integration with structured tool calls
    - Agent protocol patterns and best practices
    """
    
    def __init__(self, llm_provider: str = "openai", model: str = "gpt-4"):
        self.llm_provider = llm_provider
        self.model = model
        self.mcp_client: Optional[SimpleMCPClient] = None
        self.available_tools = {}
        self.available_resources = {}
        self.context = AgentContext(
            session_id=str(uuid.uuid4()),
            user="default"
        )
        
        # Initialize LLM client with new API structure for OpenAI 1.52+
        if llm_provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable required")
            
            # Use the new client initialization for OpenAI 1.52+
            self.llm_client = OpenAI(api_key=api_key)
        else:
            raise ValueError(f"Unsupported LLM provider: {llm_provider}")
        
        logger.info(f"Initialized MCP Agent with {llm_provider}/{model}")
    
    async def connect_to_server(self, server_command: List[str]):
        """Connect to MCP server and initialize capabilities"""
        try:
            # Start MCP client
            self.mcp_client = SimpleMCPClient(server_command)
            success = await self.mcp_client.start()
            
            if not success:
                raise RuntimeError("Failed to start MCP server")
            
            logger.info("Connected to MCP server and initialized session")
            
            # Discover available tools and resources
            await self._discover_capabilities()
            
            # Start interactive session
            await self._run_interactive_session()
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
            raise
        finally:
            if self.mcp_client:
                await self.mcp_client.stop()
    
    async def _discover_capabilities(self):
        """Discover and catalog MCP server capabilities"""
        try:
            # Discover tools
            tools = await self.mcp_client.list_tools()
            for tool in tools:
                self.available_tools[tool["name"]] = {
                    "description": tool["description"],
                    "schema": tool["inputSchema"],
                    "tool_object": tool
                }
            
            logger.info(f"Discovered {len(self.available_tools)} tools: {list(self.available_tools.keys())}")
            
            # Discover resources
            try:
                resources = await self.mcp_client.list_resources()
                for resource in resources:
                    self.available_resources[resource["uri"]] = {
                        "name": resource["name"],
                        "description": resource["description"],
                        "mimeType": resource.get("mimeType"),
                        "resource_object": resource
                    }
                
                logger.info(f"Discovered {len(self.available_resources)} resources")
                
            except Exception as e:
                logger.warning(f"Could not discover resources: {e}")
                
        except Exception as e:
            logger.error(f"Failed to discover capabilities: {e}")
            raise
    
    async def _run_interactive_session(self):
        """Run interactive agent session"""
        print("\n" + "="*80)
        print("🤖 MCP DevOps Agent v2.0 - Interactive Mode")
        print("="*80)
        print("Running on: Python 3.12 | OpenAI 1.52+ | Kubernetes 1.30")
        print("="*80)
        print("Available commands:")
        print("  help     - Show this help")
        print("  tools    - List available tools")
        print("  resources - List available resources") 
        print("  user <name> <role> - Set user context (roles: viewer, operator, admin)")
        print("  namespace <name>    - Set Kubernetes namespace")
        print("  context  - Show current context")
        print("  demo     - Run demo scenario")
        print("  <message> - Send message to AI agent")
        print("  quit     - Exit")
        print("="*80)
        
        while True:
            try:
                user_input = input(f"\n[{self.context.user}@{self.context.current_namespace}] > ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() == "quit":
                    break
                elif user_input.lower() == "help":
                    await self._show_help()
                elif user_input.lower() == "tools":
                    await self._show_tools()
                elif user_input.lower() == "resources":
                    await self._show_resources()
                elif user_input.startswith("user "):
                    await self._set_user_context(user_input)
                elif user_input.startswith("namespace "):
                    await self._set_namespace(user_input)
                elif user_input.lower() == "context":
                    await self._show_context()
                elif user_input.lower() == "demo":
                    await self._run_demo()
                else:
                    # Process as AI agent message
                    await self._process_agent_message(user_input)
                    
            except KeyboardInterrupt:
                print("\nExiting...")
                break
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error in interactive session: {e}")
                print(f"❌ Error: {e}")
    
    async def _show_help(self):
        """Show help information"""
        print("\n📚 MCP Agent Help:")
        print("\nThis agent demonstrates MCP (Model Context Protocol) patterns:")
        print("• Tool discovery and capability negotiation")
        print("• Safe tool execution with RBAC controls")  
        print("• Context management across conversations")
        print("• Resource access and caching")
        print("• Agent protocol safety patterns")
        
        print(f"\nCurrent context: User '{self.context.user}' in namespace '{self.context.current_namespace}'")
        print(f"Tools used this session: {len(self.context.tools_used)}")
        print(f"Available tools: {len(self.available_tools)}")
        print(f"Available resources: {len(self.available_resources)}")
        print(f"\nUsing: OpenAI {self.model} with API version 1.52+")
    
    async def _show_tools(self):
        """Show available MCP tools"""
        print(f"\n🔧 Available Tools ({len(self.available_tools)}):")
        for name, info in self.available_tools.items():
            print(f"  • {name}: {info['description']}")
            if 'required' in info['schema']:
                print(f"    Required params: {info['schema']['required']}")
        
        if self.context.tools_used:
            print(f"\n📊 Tools used this session: {', '.join(set(self.context.tools_used))}")
    
    async def _show_resources(self):
        """Show available MCP resources"""
        print(f"\n📄 Available Resources ({len(self.available_resources)}):")
        if self.available_resources:
            for uri, info in self.available_resources.items():
                print(f"  • {info['name']}: {info['description']}")
                print(f"    URI: {uri}")
                if info['mimeType']:
                    print(f"    Type: {info['mimeType']}")
        else:
            print("  No resources discovered")
    
    async def _set_user_context(self, command: str):
        """Set user context for RBAC demonstration"""
        parts = command.split()
        if len(parts) >= 3:
            username = parts[1]
            role = parts[2]
            
            old_user = self.context.user
            self.context.user = username
            
            print(f"👤 Changed user from '{old_user}' to '{username}' with role '{role}'")
            print(f"   Note: Role-based access will be enforced by MCP server")
        else:
            print("Usage: user <username> <role>")
            print("Roles: viewer, operator, admin")
    
    async def _set_namespace(self, command: str):
        """Set Kubernetes namespace context"""
        parts = command.split()
        if len(parts) >= 2:
            namespace = parts[1]
            old_ns = self.context.current_namespace
            self.context.current_namespace = namespace
            print(f"🏠 Changed namespace from '{old_ns}' to '{namespace}'")
        else:
            print("Usage: namespace <namespace-name>")
    
    async def _show_context(self):
        """Show current agent context"""
        print(f"\n🎯 Current Context:")
        print(f"  Session ID: {self.context.session_id}")
        print(f"  User: {self.context.user}")
        print(f"  Namespace: {self.context.current_namespace}")
        print(f"  Conversation turns: {len(self.context.conversation_history)}")
        print(f"  Tools used: {len(set(self.context.tools_used))}")
        
        # Get system context from MCP server
        try:
            if "system_context" in self.available_tools:
                result = await self._call_tool("system_context", {
                    "session_id": self.context.session_id
                })
                
                if result and result[0].get("text"):
                    context_data = json.loads(result[0]["text"])
                    if context_data.get("success"):
                        server_stats = context_data.get("server_stats", {})
                        print(f"\n📊 Server Context:")
                        print(f"  Cache size: {server_stats.get('cache_size', 0)}")
                        print(f"  Active users: {len(server_stats.get('active_users', []))}")
                        print(f"  RBAC users: {server_stats.get('rbac_users', 0)}")
                        print(f"  Server version: {context_data.get('server_version', '1.0.0')}")
                        print(f"  Protocol: {context_data.get('protocol_version', '2024-11-05')}")
                    
        except Exception as e:
            logger.debug(f"Could not get server context: {e}")
    
    async def _run_demo(self):
        """Run a demo scenario"""
        print("\n🎬 Demo Scenarios:")
        scenarios = {
            "1": ("Cluster Health Check", "Check the overall health of our Kubernetes cluster"),
            "2": ("Pod Status", "Show status of all pods in default namespace"),
            "3": ("System Metrics", "Display current system metrics"),
            "4": ("RBAC Demo", "Demonstrate role-based access controls"),
            "5": ("Tool Discovery", "Show MCP tool discovery process")
        }
        
        for key, (name, desc) in scenarios.items():
            print(f"  {key}. {name}: {desc}")
        
        choice = input("\nSelect demo (1-5): ").strip()
        
        if choice == "1":
            await self._demo_cluster_health()
        elif choice == "2":
            await self._demo_pod_status()
        elif choice == "3":
            await self._demo_system_metrics()
        elif choice == "4":
            await self._demo_rbac()
        elif choice == "5":
            await self._demo_tool_discovery()
        else:
            print("Invalid choice")
    
    async def _demo_cluster_health(self):
        """Demo: Cluster health check"""
        print("\n🏥 Cluster Health Check Demo")
        print("=" * 40)
        
        try:
            # Get nodes
            print("Checking cluster nodes...")
            result = await self._call_tool("kubernetes_get", {
                "resource_type": "nodes",
                "user": self.context.user
            })
            
            if result and result[0].get("text"):
                data = json.loads(result[0]["text"])
                if data.get("success"):
                    print("✅ Cluster nodes retrieved successfully")
                    print(f"📊 Kubernetes 1.30 cluster is running")
                    if "item_count" in data:
                        print(f"   Nodes: {data['item_count']}")
                else:
                    print(f"❌ Error: {data.get('error', 'Unknown error')}")
            
            # Get system context
            print("\nChecking system context...")
            result = await self._call_tool("system_context", {
                "session_id": self.context.session_id
            })
            
            if result and result[0].get("text"):
                data = json.loads(result[0]["text"])
                if data.get("success"):
                    print("✅ System context retrieved")
                    
        except Exception as e:
            print(f"❌ Demo failed: {e}")
    
    async def _demo_pod_status(self):
        """Demo: Pod status check"""
        print("\n📦 Pod Status Demo")
        print("=" * 30)
        
        try:
            result = await self._call_tool("kubernetes_get", {
                "resource_type": "pods",
                "namespace": self.context.current_namespace,
                "user": self.context.user
            })
            
            if result and result[0].get("text"):
                data = json.loads(result[0]["text"])
                if data.get("success"):
                    print("✅ Pod information retrieved successfully")
                    print(f"🔍 Namespace: {data.get('namespace', 'unknown')}")
                    print(f"📊 Pod count: {data.get('item_count', 0)}")
                    print(f"🕐 Timestamp: {data.get('timestamp', 'unknown')}")
                    if data.get("cached"):
                        print("💾 Result was cached")
                else:
                    print(f"❌ Error: {data.get('error', 'Unknown error')}")
            
        except Exception as e:
            print(f"❌ Demo failed: {e}")
    
    async def _demo_system_metrics(self):
        """Demo: System metrics"""
        print("\n📊 System Metrics Demo")
        print("=" * 35)
        
        try:
            # Query CPU metrics
            result = await self._call_tool("prometheus_query", {
                "query": "cpu_usage_percent",
                "time_range": "5m",
                "user": self.context.user
            })
            
            if result and result[0].get("text"):
                data = json.loads(result[0]["text"])
                if data.get("success"):
                    print("✅ CPU metrics retrieved")
                    print(f"📈 Query: {data.get('query')}")
                    print(f"⏰ Time range: {data.get('time_range')}")
                    if data.get("cached"):
                        print("💾 Result was cached (demonstrating MCP caching)")
                
        except Exception as e:
            print(f"❌ Demo failed: {e}")
    
    async def _demo_rbac(self):
        """Demo: RBAC controls"""
        print("\n🔐 RBAC Demo")
        print("=" * 20)
        
        original_user = self.context.user
        
        # Test with viewer role
        self.context.user = "viewer_demo"
        print(f"\n👤 Testing as user: {self.context.user} (viewer role)")
        
        try:
            result = await self._call_tool("kubernetes_get", {
                "resource_type": "pods",
                "user": self.context.user
            })
            
            if result and result[0].get("text"):
                data = json.loads(result[0]["text"])
                if data.get("success"):
                    print("✅ Viewer can read pods (allowed)")
                elif "Access denied" in data.get("error", ""):
                    print("🚫 Access denied (RBAC working)")
                    
        except Exception as e:
            print(f"❌ RBAC test failed: {e}")
        
        # Test with admin role
        self.context.user = "admin_demo"
        print(f"\n👤 Testing as user: {self.context.user} (admin role)")
        
        try:
            result = await self._call_tool("kubernetes_get", {
                "resource_type": "nodes",
                "user": self.context.user
            })
            
            if result and result[0].get("text"):
                data = json.loads(result[0]["text"])
                if data.get("success"):
                    print("✅ Admin can read nodes (allowed)")
                elif "Access denied" in data.get("error", ""):
                    print("🚫 Access denied")
                    
        except Exception as e:
            print(f"❌ RBAC test failed: {e}")
        
        # Restore original user
        self.context.user = original_user
        print(f"\n👤 Restored user: {self.context.user}")
    
    async def _demo_tool_discovery(self):
        """Demo: Tool discovery process"""
        print("\n🔍 MCP Tool Discovery Demo")
        print("=" * 40)
        
        print("MCP Protocol enables automatic tool discovery:")
        print("\n1. Agent connects to MCP server")
        print("2. Agent calls tools/list to discover capabilities")
        print("3. Server returns tool descriptions with JSON schemas")
        print("4. Agent can now call any discovered tool")
        
        print(f"\n📋 This session discovered {len(self.available_tools)} tools:")
        for i, (name, info) in enumerate(self.available_tools.items(), 1):
            print(f"  {i}. {name}")
            print(f"     {info['description']}")
            
            # Show schema sample
            schema = info['schema']
            if 'properties' in schema:
                params = list(schema['properties'].keys())[:3]  # Show first 3 params
                print(f"     Parameters: {', '.join(params)}")
                if len(schema['properties']) > 3:
                    print(f"     ... and {len(schema['properties']) - 3} more")
            print()
        
        print("🎯 This is the power of MCP: Agents can dynamically discover")
        print("   and use tools without hardcoded knowledge!")
        print(f"\n📌 Using OpenAI {self.model} with 1.52+ API for tool calling")
    
    async def _process_agent_message(self, message: str):
        """Process user message through AI agent with MCP tool access"""
        try:
            # Add message to conversation history
            self.context.conversation_history.append({
                "role": "user",
                "content": message,
                "timestamp": datetime.now().isoformat()
            })
            
            print(f"\n🤔 Thinking...")
            
            # Create system prompt that explains MCP context
            system_prompt = self._create_system_prompt()
            
            # Prepare messages for LLM
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            
            # Add relevant conversation history
            for msg in self.context.conversation_history[-3:]:  # Last 3 messages
                if msg["role"] in ["user", "assistant"]:
                    messages.append({
                        "role": msg["role"], 
                        "content": msg["content"]
                    })
            
            # Call LLM with tools
            response = await self._call_llm_with_tools(messages)
            
            # Process response and execute any tool calls
            agent_response = await self._process_llm_response(response)
            
            print(f"\n🤖 Agent: {agent_response}")
            
            # Add response to conversation history
            self.context.conversation_history.append({
                "role": "assistant",
                "content": agent_response,
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            print(f"❌ Error processing message: {e}")
    
    def _create_system_prompt(self) -> str:
        """Create system prompt explaining MCP context and available tools"""
        tools_desc = "\n".join([
            f"- {name}: {info['description']}"
            for name, info in self.available_tools.items()
        ])
        
        resources_desc = "\n".join([
            f"- {info['name']}: {info['description']}"
            for info in self.available_resources.values()
        ]) if self.available_resources else "None discovered"
        
        return f"""You are a DevOps AI Agent connected to a Kubernetes cluster via MCP (Model Context Protocol).

CURRENT CONTEXT:
- User: {self.context.user}
- Kubernetes Namespace: {self.context.current_namespace}
- Session: {self.context.session_id}
- Kubernetes Version: 1.30.0
- Kind Version: 0.23.0

AVAILABLE MCP TOOLS:
{tools_desc}

AVAILABLE MCP RESOURCES:
{resources_desc}

MCP PROTOCOL CAPABILITIES:
- All tool calls use proper MCP protocol with JSON-RPC 2.0
- RBAC controls limit tool access based on user role
- Caching improves performance for expensive operations
- Context is managed across conversation turns
- Safety controls prevent dangerous operations

IMPORTANT GUIDELINES:
1. Always include 'user': '{self.context.user}' in tool call arguments for RBAC
2. Use 'namespace': '{self.context.current_namespace}' for Kubernetes operations
3. Start with dry_run: true for any apply operations
4. Explain MCP protocol benefits when relevant
5. Show how agent protocols improve safety and efficiency
6. Demonstrate context management and tool usage patterns

When users ask DevOps questions, use the MCP tools to provide accurate, real-time information while explaining how the MCP protocol enables safe agent operations."""
    
    async def _call_llm_with_tools(self, messages: List[Dict[str, Any]]) -> Any:
        """Call LLM with MCP tool descriptions - Updated for OpenAI 1.52+"""
        try:
            # Convert MCP tools to OpenAI function format
            tools = []
            for name, info in self.available_tools.items():
                tools.append({
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": info["description"],
                        "parameters": info["schema"]
                    }
                })
            
            # Call OpenAI with function calling (OpenAI 1.52+ API)
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools else None,  # Only pass tools if available
                tool_choice="auto" if tools else None,
                temperature=0.7,
                max_tokens=2000
            )
            
            return response
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise
    
    async def _process_llm_response(self, response: Any) -> str:
        """Process LLM response and execute any tool calls - Updated for OpenAI 1.52+"""
        try:
            choice = response.choices[0]
            message = choice.message
            
            # Check if LLM wants to call a function
            if hasattr(message, 'tool_calls') and message.tool_calls:
                tool_call = message.tool_calls[0]
                function = tool_call.function
                function_name = function.name
                
                try:
                    function_args = json.loads(function.arguments)
                except json.JSONDecodeError:
                    return f"❌ Invalid function arguments: {function.arguments}"
                
                # Add user and namespace context if not provided
                if 'user' not in function_args:
                    function_args['user'] = self.context.user
                if 'namespace' not in function_args and function_name.startswith('kubernetes'):
                    function_args['namespace'] = self.context.current_namespace
                
                print(f"\n🔧 Executing MCP tool: {function_name}")
                print(f"   Arguments: {json.dumps(function_args, indent=2)}")
                
                # Execute MCP tool call
                tool_result = await self._call_tool(function_name, function_args)
                
                if tool_result:
                    # Track tool usage
                    self.context.tools_used.append(function_name)
                    
                    # Parse tool result
                    result_text = tool_result[0].get("text", "No result") if tool_result else "No result"
                    
                    try:
                        result_data = json.loads(result_text)
                        
                        # Create follow-up message to LLM with tool result
                        follow_up_messages = [
                            {"role": "system", "content": self._create_system_prompt()},
                            {"role": "user", "content": f"Tool {function_name} returned: {result_text}. Please interpret and explain the results clearly and concisely."}
                        ]
                        
                        follow_up_response = self.llm_client.chat.completions.create(
                            model=self.model,
                            messages=follow_up_messages,
                            temperature=0.7,
                            max_tokens=1500
                        )
                        
                        interpretation = follow_up_response.choices[0].message.content
                        
                        # Show appropriate response based on success
                        if result_data.get("error") or not result_data.get("success", True):
                            return f"❌ Tool execution issue:\n{interpretation}"
                        
                        return f"✅ Tool executed successfully!\n\n{interpretation}"
                        
                    except json.JSONDecodeError:
                        return f"✅ Tool result:\n{result_text}"
                else:
                    return f"❌ Tool {function_name} returned no result"
            
            else:
                # Regular response without tool calls
                return message.content or "No response from assistant"
                
        except Exception as e:
            logger.error(f"Error processing LLM response: {e}")
            return f"❌ Error processing response: {e}"
    
    async def _call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Execute MCP tool call"""
        try:
            if tool_name not in self.available_tools:
                raise ValueError(f"Unknown tool: {tool_name}")
            
            # Call tool via simplified MCP client
            result = await self.mcp_client.call_tool(tool_name, arguments)
            
            return result
            
        except Exception as e:
            logger.error(f"Tool call failed: {e}")
            # Return error as content for LLM to process
            return [{
                "type": "text", 
                "text": json.dumps({
                    "error": str(e),
                    "tool": tool_name,
                    "arguments": arguments
                })
            }]

async def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python agent.py <path-to-server.py> [additional server args...]")
        print("\nExamples:")
        print("  python agent.py python server.py")
        print("  python agent.py ./server.py --verbose")
        print("\nMake sure you have set OPENAI_API_KEY environment variable!")
        sys.exit(1)
    
    # Check for required environment variables
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY environment variable required")
        print("   Set it with: export OPENAI_API_KEY=your_key_here")
        print("   Get your API key from: https://platform.openai.com/api-keys")
        sys.exit(1)
    
    # Get server command from arguments
    server_command = sys.argv[1:]
    
    # Create and run agent
    try:
        agent = MCPAgent(
            llm_provider="openai",
            model="gpt-4"  # Use gpt-3.5-turbo if you don't have gpt-4 access
        )
        
        print("🚀 Starting MCP DevOps Agent v2.0...")
        print(f"   Server command: {' '.join(server_command)}")
        print(f"   LLM Model: {agent.model}")
        print(f"   OpenAI API: v1.52+")
        
        await agent.connect_to_server(server_command)
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        logger.error(f"Agent failed: {e}")
        print(f"❌ Agent failed: {e}")
        
        # Provide helpful error messages
        if "OPENAI_API_KEY" in str(e):
            print("\n💡 Tip: Make sure your OpenAI API key is set correctly")
        elif "server" in str(e).lower():
            print(f"\n💡 Tip: Make sure the MCP server is working:")
            print(f"   Try running: {' '.join(server_command)}")
        
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
