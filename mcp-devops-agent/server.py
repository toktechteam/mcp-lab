#!/usr/bin/env python3
"""
server.py - Working MCP Server (No SDK Dependencies)
Educational Lab 6.1: Agent Protocols and Standards

This implements MCP protocol without the problematic SDK
Compatible with Python 3.11-3.12 and works with real kubectl commands
Updated for latest versions 2024-2025
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
import hashlib
import yaml
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class RBACManager:
    """Role-Based Access Control for MCP tools"""
    
    def __init__(self):
        self.roles = {
            "viewer": ["kubernetes_get", "prometheus_query", "logs_search", "system_context"],
            "operator": ["kubernetes_get", "kubernetes_apply", "prometheus_query", 
                        "logs_search", "runbook_execute", "system_context"],
            "admin": ["kubernetes_get", "kubernetes_apply", "kubernetes_delete",
                     "prometheus_query", "logs_search", "runbook_execute", "system_context"]
        }
        self.user_roles = {
            "default": "viewer",
            "student": "viewer", 
            "alice": "admin",
            "bob": "operator",
            "charlie": "viewer",
            "admin": "admin"
        }
        
    def can_execute(self, user: str, tool: str) -> bool:
        """Check if user can execute tool"""
        role = self.user_roles.get(user, "viewer")
        return tool in self.roles.get(role, [])

class MCPCache:
    """Caching for expensive operations"""
    
    def __init__(self):
        self.cache = {}
        self.ttl = {}
        
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if valid"""
        if key in self.cache and key in self.ttl:
            if datetime.now() < self.ttl[key]:
                return self.cache[key]
            else:
                del self.cache[key]
                del self.ttl[key]
        return None
    
    def set(self, key: str, value: Any, ttl_seconds: int = 300):
        """Cache value with TTL"""
        self.cache[key] = value
        self.ttl[key] = datetime.now() + timedelta(seconds=ttl_seconds)

class SimpleMCPServer:
    """Simplified MCP server that works without SDK"""
    
    def __init__(self):
        self.rbac = RBACManager()
        self.cache = MCPCache()
        self.request_id = 0
        
        # Available tools
        self.tools = [
            {
                "name": "kubernetes_get",
                "description": "Get Kubernetes resources with safety controls",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "resource_type": {
                            "type": "string",
                            "enum": ["pods", "services", "deployments", "nodes", "configmaps", "secrets"]
                        },
                        "namespace": {"type": "string", "default": "default"},
                        "name": {"type": "string"},
                        "user": {"type": "string", "default": "default"}
                    },
                    "required": ["resource_type"]
                }
            },
            {
                "name": "kubernetes_apply",
                "description": "Apply Kubernetes manifests with validation",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "manifest": {"type": "string"},
                        "namespace": {"type": "string", "default": "default"},
                        "dry_run": {"type": "boolean", "default": True},
                        "user": {"type": "string", "default": "default"}
                    },
                    "required": ["manifest"]
                }
            },
            {
                "name": "prometheus_query",
                "description": "Execute Prometheus queries with caching",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "time_range": {"type": "string", "default": "5m"},
                        "user": {"type": "string", "default": "default"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "logs_search",
                "description": "Search application logs with limits",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "namespace": {"type": "string", "default": "default"},
                        "limit": {"type": "integer", "default": 100, "maximum": 1000},
                        "user": {"type": "string", "default": "default"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "system_context",
                "description": "Get system context and session info",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "default": "default"}
                    }
                }
            }
        ]
    
    async def handle_request(self, request_line: str) -> str:
        """Handle JSON-RPC request"""
        try:
            if not request_line.strip():
                return ""
                
            request = json.loads(request_line.strip())
            method = request.get("method")
            params = request.get("params", {})
            req_id = request.get("id")
            
            logger.info(f"Handling request: {method}")
            
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {}
                    },
                    "serverInfo": {
                        "name": "DevOps MCP Server",
                        "version": "1.0.0"
                    }
                }
            elif method == "tools/list":
                result = {"tools": self.tools}
            elif method == "tools/call":
                result = await self.handle_tool_call(params)
            elif method == "resources/list":
                result = {"resources": []}
            else:
                raise ValueError(f"Unknown method: {method}")
            
            response = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result
            }
            
        except Exception as e:
            logger.error(f"Request error: {e}")
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if 'request' in locals() else None,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }
        
        return json.dumps(response)
    
    async def handle_tool_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tool execution"""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        user = arguments.get("user", "default")
        
        # RBAC check
        if not self.rbac.can_execute(user, tool_name):
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": f"Access denied: User '{user}' cannot execute '{tool_name}'",
                        "user_role": self.rbac.user_roles.get(user, "unknown")
                    })
                }]
            }
        
        try:
            if tool_name == "kubernetes_get":
                result = await self.execute_kubernetes_get(arguments)
            elif tool_name == "kubernetes_apply":
                result = await self.execute_kubernetes_apply(arguments)
            elif tool_name == "prometheus_query":
                result = await self.execute_prometheus_query(arguments)
            elif tool_name == "logs_search":
                result = await self.execute_logs_search(arguments)
            elif tool_name == "system_context":
                result = await self.execute_system_context(arguments)
            else:
                result = {"error": f"Tool not implemented: {tool_name}"}
            
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, indent=2)
                }]
            }
            
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": f"Tool execution failed: {str(e)}",
                        "tool": tool_name
                    })
                }]
            }
    
    async def execute_kubernetes_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute kubectl get commands"""
        resource_type = args.get("resource_type")
        namespace = args.get("namespace", "default")
        name = args.get("name")
        
        # Check cache first
        cache_key = f"k8s_get_{resource_type}_{namespace}_{name or 'all'}"
        cached_result = self.cache.get(cache_key)
        if cached_result:
            return {"cached": True, **cached_result}
        
        try:
            # Build kubectl command
            cmd = ["kubectl", "get", resource_type, "-n", namespace, "-o", "json"]
            if name:
                cmd.append(name)
            
            logger.info(f"Executing: {' '.join(cmd)}")
            
            # Execute command
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
            
            if process.returncode != 0:
                return {
                    "success": False,
                    "error": stderr.decode(),
                    "command": " ".join(cmd)
                }
            
            # Parse and sanitize output
            raw_data = json.loads(stdout.decode())
            sanitized_data = self.sanitize_k8s_data(raw_data)
            
            # Count items for summary
            item_count = 0
            if "items" in sanitized_data:
                item_count = len(sanitized_data["items"])
            elif "kind" in sanitized_data:
                item_count = 1
            
            result = {
                "success": True,
                "resource_type": resource_type,
                "namespace": namespace,
                "item_count": item_count,
                "data": sanitized_data,
                "timestamp": datetime.now().isoformat(),
                "cached": False
            }
            
            # Cache successful results
            self.cache.set(cache_key, result, ttl_seconds=60)
            
            return result
            
        except asyncio.TimeoutError:
            return {"success": False, "error": "Command timeout after 30 seconds"}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid JSON response: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Execution failed: {str(e)}"}
    
    def sanitize_k8s_data(self, data: Any) -> Any:
        """Remove sensitive information from Kubernetes data"""
        if isinstance(data, dict):
            sanitized = {}
            sensitive_fields = ["token", "password", "secret", "key", "cert", "tls"]
            
            for k, v in data.items():
                if any(field in k.lower() for field in sensitive_fields):
                    sanitized[k] = "[REDACTED]"
                elif k == "data" and isinstance(v, dict):
                    sanitized[k] = {key: "[REDACTED]" for key in v.keys()}
                else:
                    sanitized[k] = self.sanitize_k8s_data(v)
            return sanitized
        elif isinstance(data, list):
            return [self.sanitize_k8s_data(item) for item in data]
        else:
            return data
    
    async def execute_kubernetes_apply(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute kubectl apply commands"""
        manifest = args.get("manifest", "")
        namespace = args.get("namespace", "default")
        dry_run = args.get("dry_run", True)
        
        try:
            # Validate YAML
            yaml.safe_load(manifest)
            
            # Build command with server-side dry run for Kubernetes 1.30
            cmd = ["kubectl", "apply", "-n", namespace, "-f", "-"]
            if dry_run:
                cmd.extend(["--dry-run=server"])
            
            # Execute
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=manifest.encode()),
                timeout=60
            )
            
            return {
                "success": process.returncode == 0,
                "stdout": stdout.decode(),
                "stderr": stderr.decode(),
                "dry_run": dry_run,
                "namespace": namespace
            }
            
        except yaml.YAMLError as e:
            return {"success": False, "error": f"Invalid YAML: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Apply failed: {str(e)}"}
    
    async def execute_prometheus_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Prometheus queries (mock for demo)"""
        query = args.get("query", "")
        time_range = args.get("time_range", "5m")
        
        # Mock Prometheus data with more realistic values
        current_time = time.time()
        return {
            "success": True,
            "query": query,
            "time_range": time_range,
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"__name__": "cpu_usage", "instance": "node-1"},
                        "values": [
                            [current_time - 300, "45.2"],
                            [current_time - 240, "48.7"],
                            [current_time - 180, "52.1"],
                            [current_time - 120, "49.3"],
                            [current_time - 60, "47.8"],
                            [current_time, "46.9"]
                        ]
                    }
                ]
            },
            "timestamp": datetime.now().isoformat(),
            "cached": False
        }
    
    async def execute_logs_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search logs with kubectl"""
        query = args.get("query", "")
        namespace = args.get("namespace", "default")
        limit = min(args.get("limit", 100), 1000)
        
        try:
            # First, get pods in the namespace
            get_pods_cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "name"]
            
            process = await asyncio.create_subprocess_exec(
                *get_pods_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            
            if process.returncode != 0:
                return {
                    "success": False,
                    "error": f"Failed to get pods: {stderr.decode()}",
                    "namespace": namespace
                }
            
            # Parse pod names
            pod_names = [line.strip().replace("pod/", "") 
                        for line in stdout.decode().split('\n') 
                        if line.strip()]
            
            if not pod_names:
                return {
                    "success": False,
                    "error": f"No pods found in namespace {namespace}",
                    "namespace": namespace
                }
            
            # Collect logs from all pods
            all_logs = []
            
            for pod_name in pod_names[:5]:  # Limit to first 5 pods for performance
                # Get logs for each pod
                log_cmd = ["kubectl", "logs", pod_name, "-n", namespace, 
                          "--tail", str(limit), "--all-containers=true"]
                
                try:
                    process = await asyncio.create_subprocess_exec(
                        *log_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
                    
                    if process.returncode == 0:
                        pod_logs = stdout.decode().strip()
                        if pod_logs:
                            # Add pod identifier to logs
                            for line in pod_logs.split('\n'):
                                if line.strip():
                                    # Filter by query if provided
                                    if not query or query.lower() in line.lower():
                                        all_logs.append(f"[{pod_name}] {line}")
                                        
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout getting logs for pod {pod_name}")
                    continue
                except Exception as e:
                    logger.warning(f"Error getting logs for pod {pod_name}: {e}")
                    continue
            
            # Limit total logs
            all_logs = all_logs[-limit:] if len(all_logs) > limit else all_logs
            
            if not all_logs:
                return {
                    "success": True,
                    "query": query,
                    "namespace": namespace,
                    "total_lines": 0,
                    "logs": ["No logs found matching the query"],
                    "message": f"Searched {len(pod_names)} pods in namespace {namespace}",
                    "timestamp": datetime.now().isoformat()
                }
            
            return {
                "success": True,
                "query": query,
                "namespace": namespace,
                "total_lines": len(all_logs),
                "pods_searched": len(pod_names),
                "logs": all_logs,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {"success": False, "error": f"Log search failed: {str(e)}"}
    
    async def execute_system_context(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get system context"""
        session_id = args.get("session_id", "default")
        
        return {
            "success": True,
            "session_id": session_id,
            "server_stats": {
                "cache_size": len(self.cache.cache),
                "cached_keys": list(self.cache.cache.keys()),
                "rbac_users": len(self.rbac.user_roles),
                "active_users": list(self.rbac.user_roles.keys()),
                "tools_available": len(self.tools),
                "tool_names": [t["name"] for t in self.tools]
            },
            "server_version": "1.0.0",
            "protocol_version": "2024-11-05",
            "timestamp": datetime.now().isoformat()
        }

async def main():
    """Main server loop"""
    server = SimpleMCPServer()
    logger.info("Starting Simple MCP Server...")
    logger.info(f"Available tools: {[t['name'] for t in server.tools]}")
    logger.info("Server ready. Waiting for requests...")
    
    try:
        while True:
            try:
                # Read from stdin
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                
                if not line:
                    break
                
                # Process request
                response = await server.handle_request(line)
                
                if response:
                    print(response, flush=True)
                    
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Request processing error: {e}")
                
    except KeyboardInterrupt:
        logger.info("Server shutting down...")

if __name__ == "__main__":
    asyncio.run(main())
