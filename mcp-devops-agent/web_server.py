#!/usr/bin/env python3
"""
web_server.py - Web Backend for MCP Interface (Updated for OpenAI 1.52)
Educational Lab 6.1: Agent Protocols and Standards

This creates a web server that connects the HTML frontend
to the MCP server, replacing the CLI interface.

Compatible with:
- Python 3.11-3.12
- flask>=3.0.3
- flask-socketio>=5.3.6
- openai>=1.52.0

Run with: python web_server.py
Then open: http://localhost:8082
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    from flask import Flask, render_template_string, request, jsonify
    from flask_socketio import SocketIO, emit
except ImportError:
    print("❌ Missing required dependencies. Install with:")
    print("   pip install flask==3.0.3 flask-socketio==5.3.6")
    sys.exit(1)

try:
    import openai
    from openai import OpenAI
    # Verify we have the new client structure (1.52+)
    if not hasattr(openai, 'OpenAI'):
        print("❌ OpenAI library too old. Install with:")
        print("   pip install openai==1.52.0")
        sys.exit(1)
except ImportError:
    print("❌ OpenAI library not installed. Install with:")
    print("   pip install openai==1.52.0")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mcp-devops-lab-2024'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class MCPWebServer:
    """Web server that bridges the HTML frontend to MCP server and AI agent"""
    
    def __init__(self):
        self.mcp_process = None
        self.mcp_connected = False
        self.agent_client = None
        self.session_stats = {
            'start_time': datetime.now(),
            'tools_used': 0,
            'cache_hits': 0,
            'error_count': 0,
            'messages': 0
        }
        self.available_tools = []
        self.user_contexts = {}
        
        # Initialize OpenAI client with new API structure (1.52+)
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            self.llm_client = OpenAI(api_key=api_key)
            logger.info("OpenAI client initialized with v1.52+ API")
        else:
            self.llm_client = None
            logger.warning("OPENAI_API_KEY not set - using mock responses")
    
    def get_user_context(self, session_id: str) -> Dict[str, Any]:
        """Get or create user context"""
        if session_id not in self.user_contexts:
            self.user_contexts[session_id] = {
                'user': 'student',
                'namespace': 'default',
                'conversation_history': [],
                'tools_used': []
            }
        return self.user_contexts[session_id]
    
    async def start_mcp_server(self) -> bool:
        """Start the MCP server subprocess"""
        try:
            # Check if server.py exists
            server_path = Path('server.py')
            if not server_path.exists():
                logger.error("server.py not found in current directory")
                return False
            
            # Start MCP server
            self.mcp_process = await asyncio.create_subprocess_exec(
                sys.executable, 'server.py',
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            logger.info("MCP server started successfully")
            
            # Initialize connection
            await self.initialize_mcp_connection()
            
            # Discover tools
            await self.discover_tools()
            
            self.mcp_connected = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            return False
    
    async def initialize_mcp_connection(self):
        """Initialize MCP connection"""
        init_request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "1",
            "params": {
                "protocolVersion": "2024-11-05",
                "clientInfo": {
                    "name": "MCP-Web-Interface",
                    "version": "2.0.0"
                }
            }
        }
        
        await self.send_mcp_request(json.dumps(init_request))
    
    async def discover_tools(self):
        """Discover available tools from MCP server"""
        try:
            tools_request = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": "2"
            }
            
            response = await self.send_mcp_request(json.dumps(tools_request))
            
            if response and 'result' in response and 'tools' in response['result']:
                self.available_tools = response['result']['tools']
                logger.info(f"Discovered {len(self.available_tools)} tools")
            
        except Exception as e:
            logger.error(f"Failed to discover tools: {e}")
    
    async def send_mcp_request(self, request_json: str) -> Optional[Dict[str, Any]]:
        """Send request to MCP server and get response"""
        if not self.mcp_process:
            return None
        
        try:
            # Send request
            self.mcp_process.stdin.write((request_json + '\n').encode())
            await self.mcp_process.stdin.drain()
            
            # Read response
            response_line = await self.mcp_process.stdout.readline()
            if response_line:
                return json.loads(response_line.decode().strip())
            
        except Exception as e:
            logger.error(f"MCP request failed: {e}")
            return None
    
    async def execute_tool_via_mcp(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tool via MCP protocol"""
        try:
            tool_request = {
                "jsonrpc": "2.0", 
                "method": "tools/call",
                "id": f"tool_{int(time.time())}",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            response = await self.send_mcp_request(json.dumps(tool_request))
            
            if response and 'result' in response:
                self.session_stats['tools_used'] += 1
                
                result_content = response['result'].get('content', [])
                if result_content and result_content[0].get('text'):
                    return json.loads(result_content[0]['text'])
                    
            return {"error": "No result from MCP server"}
            
        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"error": str(e)}
    
    def generate_mock_response(self, message: str, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate mock response when LLM is not available"""
        msg = message.lower()
        user = user_context['user']
        namespace = user_context['namespace']
        
        responses = {
            'health': {
                'text': f"✅ **Cluster Health Check** (Mock Response)\n\nUser: {user} | Namespace: {namespace}\n\n📊 **Status:**\n- 3 nodes Ready (Kubernetes 1.30)\n- All pods running\n- No alerts\n\n🔧 **MCP Protocol:** This would normally execute `kubernetes_get` tool via MCP server with proper RBAC validation.",
                'tool_used': 'kubernetes_get',
                'cached': False
            },
            'pod': {
                'text': f"📦 **Pod Status** (Mock Response)\n\nNamespace: {namespace}\n\n✅ **Running:** 8 pods\n⏳ **Pending:** 1 pod\n❌ **Failed:** 0 pods\n\n**Recent Events:**\n- nginx-deployment scaled\n- api-server healthy\n\n🔐 **RBAC:** User '{user}' has read access verified via MCP.",
                'tool_used': 'kubernetes_get',
                'cached': True
            },
            'metrics': {
                'text': "📊 **System Metrics** (Mock Response)\n\n**CPU Usage:**\n- Node-1: 45%\n- Node-2: 52%\n- Node-3: 38%\n\n**Memory Usage:**\n- Node-1: 68%\n- Node-2: 71%\n- Node-3: 63%\n\n💾 **Cache Hit:** Retrieved from MCP cache layer",
                'tool_used': 'prometheus_query',
                'cached': True
            },
            'logs': {
                'text': f"📋 **Log Search** (Mock Response)\n\nSearching in namespace: {namespace}\n\n```\n2024-01-15 10:23:45 ERROR [api-server] Connection timeout\n2024-01-15 10:22:12 WARN  [scheduler] Resource pressure\n2024-01-15 10:21:33 INFO  [kubelet] Pod started\n```\n\n⚠️ **Resource Limit:** 100 lines max (MCP safety control)",
                'tool_used': 'logs_search',
                'cached': False
            }
        }
        
        # Find matching response
        for key, response in responses.items():
            if key in msg:
                if response['cached']:
                    self.session_stats['cache_hits'] += 1
                return response
        
        # Default response
        return {
            'text': f"I can help with Kubernetes operations using MCP protocol.\n\nCurrent context:\n- User: {user}\n- Namespace: {namespace}\n- Kubernetes: v1.30.0\n- Kind: v0.23.0\n\nTry asking:\n• \"Check cluster health\"\n• \"Show pod status\"\n• \"Get system metrics\"\n• \"Search logs\"\n\nAll operations use MCP protocol with RBAC controls.",
            'tool_used': None,
            'cached': False
        }
    
    async def process_message(self, message: str, session_id: str) -> Dict[str, Any]:
        """Process user message with LLM + MCP integration"""
        try:
            user_context = self.get_user_context(session_id)
            self.session_stats['messages'] += 1
            
            # Add to conversation history
            user_context['conversation_history'].append({
                'role': 'user',
                'content': message,
                'timestamp': datetime.now().isoformat()
            })
            
            # If LLM is available, use it
            if self.llm_client and self.mcp_connected:
                response = await self.process_with_llm(message, user_context)
            else:
                # Use mock response
                response = self.generate_mock_response(message, user_context)
            
            # Add assistant response to history
            user_context['conversation_history'].append({
                'role': 'assistant',
                'content': response['text'],
                'timestamp': datetime.now().isoformat()
            })
            
            # Track tool usage
            if response.get('tool_used'):
                user_context['tools_used'].append(response['tool_used'])
                self.session_stats['tools_used'] += 1
            
            return response
            
        except Exception as e:
            logger.error(f"Message processing failed: {e}")
            self.session_stats['error_count'] += 1
            return {
                'text': f"❌ Error processing message: {str(e)}",
                'tool_used': None,
                'cached': False,
                'error': True
            }
    
    async def process_with_llm(self, message: str, user_context: Dict[str, Any]) -> Dict[str, Any]:
        """Process message using LLM with MCP tool integration - Updated for OpenAI 1.52+"""
        try:
            # Create system prompt
            system_prompt = f"""You are a DevOps AI Agent with access to MCP tools.

Current Context:
- User: {user_context['user']}
- Namespace: {user_context['namespace']}
- Available Tools: {', '.join([t['name'] for t in self.available_tools])}
- Kubernetes Version: 1.30.0
- Kind Version: 0.23.0

Available MCP Tools:
{chr(10).join([f"- {t['name']}: {t['description']}" for t in self.available_tools])}

Guidelines:
1. Use MCP tools when needed by calling the appropriate function
2. Always include user context in tool calls
3. Explain MCP protocol benefits
4. Be concise but informative
5. Highlight security and safety features

When you need to use a tool, I'll execute it via MCP protocol and return results."""

            # Prepare messages
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ]
            
            # Add recent conversation history
            for msg in user_context['conversation_history'][-4:]:
                if msg['role'] in ['user', 'assistant']:
                    messages.append({
                        'role': msg['role'],
                        'content': msg['content']
                    })
            
            # Convert MCP tools to OpenAI format
            tools = []
            for tool in self.available_tools:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": tool["inputSchema"]
                    }
                })
            
            # Call LLM with updated OpenAI 1.52+ API
            response = self.llm_client.chat.completions.create(
                model="gpt-4",
                messages=messages,
                tools=tools if tools else None,
                tool_choice="auto" if tools else None,
                temperature=0.7,
                max_tokens=1500
            )
            
            choice = response.choices[0]
            message_obj = choice.message
            
            # Check if LLM wants to use tools
            if hasattr(message_obj, 'tool_calls') and message_obj.tool_calls:
                tool_call = message_obj.tool_calls[0]
                function = tool_call.function
                tool_name = function.name
                
                try:
                    tool_args = json.loads(function.arguments)
                    
                    # Add user context to tool args
                    tool_args['user'] = user_context['user']
                    if 'namespace' not in tool_args:
                        tool_args['namespace'] = user_context['namespace']
                    
                    # Execute tool via MCP
                    tool_result = await self.execute_tool_via_mcp(tool_name, tool_args)
                    
                    # Get LLM to interpret results
                    interpretation_messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Tool {tool_name} returned: {json.dumps(tool_result)}. Please interpret and explain the results clearly."}
                    ]
                    
                    interpretation_response = self.llm_client.chat.completions.create(
                        model="gpt-4",
                        messages=interpretation_messages,
                        temperature=0.7,
                        max_tokens=1000
                    )
                    
                    return {
                        'text': interpretation_response.choices[0].message.content,
                        'tool_used': tool_name,
                        'cached': tool_result.get('cached', False),
                        'raw_result': tool_result
                    }
                    
                except Exception as e:
                    return {
                        'text': f"❌ Tool execution failed: {str(e)}",
                        'tool_used': tool_name,
                        'cached': False,
                        'error': True
                    }
            else:
                # Regular response without tools
                return {
                    'text': message_obj.content or "No response generated",
                    'tool_used': None,
                    'cached': False
                }
                
        except Exception as e:
            logger.error(f"LLM processing failed: {e}")
            return self.generate_mock_response(message, user_context)

# Global server instance
web_server = MCPWebServer()

# Flask routes
@app.route('/')
def index():
    """Serve the main web interface"""
    # Read the HTML file content
    html_path = Path('web_interface.html')
    if html_path.exists():
        return html_path.read_text()
    else:
        return """
        <!DOCTYPE html>
        <html>
        <head><title>MCP DevOps Agent</title></head>
        <body>
            <h1>MCP DevOps Agent v2.0</h1>
            <p>⚠️ web_interface.html not found. Please ensure all files are in the same directory.</p>
            <p>Expected files:</p>
            <ul>
                <li>web_server.py (this file)</li>
                <li>web_interface.html</li>
                <li>server.py</li>
                <li>agent.py</li>
            </ul>
        </body>
        </html>
        """

@app.route("/rpc", methods=["POST"])
def rpc_handler():
    """Proxy JSON-RPC requests from frontend to server.py"""
    try:
        body = request.json

        process = subprocess.Popen(
            [sys.executable, "server.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=json.dumps(body))

        if process.returncode != 0:
            return jsonify({"error": "server.py failed", "stderr": stderr}), 500

        return jsonify(json.loads(stdout))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/status')
def api_status():
    """API endpoint for server status"""
    return jsonify({
        'mcp_connected': web_server.mcp_connected,
        'tools_available': len(web_server.available_tools),
        'session_stats': web_server.session_stats,
        'llm_available': web_server.llm_client is not None,
        'versions': {
            'kubernetes': '1.30.0',
            'kind': '0.23.0',
            'python': '3.12',
            'openai': '1.52.0'
        }
    })

@app.route('/api/tools')
def api_tools():
    """API endpoint for available tools"""
    return jsonify({
        'tools': web_server.available_tools,
        'count': len(web_server.available_tools)
    })

# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('status', {
        'connected': web_server.mcp_connected,
        'tools': web_server.available_tools,
        'stats': web_server.session_stats
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('connect_mcp')
def handle_connect_mcp():
    """Handle MCP server connection request"""
    async def connect():
        success = await web_server.start_mcp_server()
        socketio.emit('mcp_status', {
            'connected': success,
            'tools': web_server.available_tools if success else [],
            'message': 'Connected successfully' if success else 'Connection failed'
        }, room=request.sid)
    
    # Run async function in thread
    def run_connect():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(connect())
        loop.close()
    
    threading.Thread(target=run_connect).start()

@socketio.on('send_message')
def handle_message(data):
    """Handle user message"""
    message = data.get('message', '').strip()
    session_id = request.sid
    user = data.get('user', 'student')
    namespace = data.get('namespace', 'default')
    
    if not message:
        return
    
    # Update user context
    user_context = web_server.get_user_context(session_id)
    user_context['user'] = user
    user_context['namespace'] = namespace
    
    logger.info(f"Processing message from {user}: {message}")
    
    async def process():
        response = await web_server.process_message(message, session_id)
        socketio.emit('message_response', {
            'response': response,
            'stats': web_server.session_stats
        }, room=session_id)
    
    def run_process():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process())
        loop.close()
    
    threading.Thread(target=run_process).start()

@socketio.on('update_context')
def handle_context_update(data):
    """Handle context updates (user, namespace changes)"""
    session_id = request.sid
    user_context = web_server.get_user_context(session_id)
    
    if 'user' in data:
        user_context['user'] = data['user']
    if 'namespace' in data:
        user_context['namespace'] = data['namespace']
    
    emit('context_updated', {
        'user': user_context['user'],
        'namespace': user_context['namespace']
    })

@socketio.on('get_stats')
def handle_get_stats():
    """Handle stats request"""
    stats = web_server.session_stats.copy()
    stats['uptime'] = str(datetime.now() - stats['start_time'])
    stats['tools_available'] = len(web_server.available_tools)
    
    emit('stats_update', stats)

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

def main():
    """Main entry point"""
    print("🚀 Starting MCP DevOps Web Server v2.0...")
    print("   Using: Python 3.12 | OpenAI 1.52+ | Flask 3.0.3")
    
    # Check environment
    if not os.getenv('OPENAI_API_KEY'):
        print("⚠️  OPENAI_API_KEY not set - using mock responses")
        print("   Set with: export OPENAI_API_KEY=your_key_here")
    
    # Check required files
    required_files = ['server.py', 'web_interface.html']
    missing_files = [f for f in required_files if not Path(f).exists()]
    
    if missing_files:
        print(f"❌ Missing required files: {', '.join(missing_files)}")
        print("   Make sure all files are in the same directory")
        return
    
    print("📋 Configuration:")
    print(f"   Web Interface: http://localhost:8082")
    print(f"   MCP Server: server.py (auto-started)")
    print(f"   LLM Client: {'OpenAI GPT-4' if os.getenv('OPENAI_API_KEY') else 'Mock responses'}")
    print(f"   Kubernetes: v1.30.0 | Kind: v0.23.0")
    print("\n" + "="*50)
    print("🌐 Open your browser to: http://localhost:8082")
    print("="*50)
    
    # Start the web server
    try:
        socketio.run(
            app,
            host='0.0.0.0',
            port=8082,
            debug=False,
            allow_unsafe_werkzeug=True
        )
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"❌ Server failed: {e}")
    finally:
        # Cleanup
        if web_server.mcp_process:
            web_server.mcp_process.terminate()

if __name__ == '__main__':
    main()
