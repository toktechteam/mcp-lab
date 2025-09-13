# MCP DevOps Agent - Setup Guide for EC2 (Latest Versions Only)

## Prerequisites
- EC2 instance with Ubuntu 22.04 or 24.04 LTS
- Instance type: t3.medium or larger (4GB RAM minimum)
- Storage: 20GB minimum
- Security Group configured (see below)
- Internet connection

## Step 0: EC2 Security Group Configuration

Configure your EC2 Security Group with these inbound rules:

| Type | Protocol | Port Range | Source | Description |
|------|----------|------------|--------|-------------|
| SSH | TCP | 22 | Your IP | SSH access |
| Custom TCP | TCP | 8082 | 0.0.0.0/0 | Web Interface |
| Custom TCP | TCP | 30000-30100 | 0.0.0.0/0 | Kubernetes NodePorts |

```bash
# If using AWS CLI to update security group:
aws ec2 authorize-security-group-ingress \
    --group-id <your-sg-id> \
    --protocol tcp \
    --port 8082 \
    --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
    --group-id <your-sg-id> \
    --protocol tcp \
    --port 30000-30100 \
    --cidr 0.0.0.0/0
```

## Step 1: System Updates and Basic Tools

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install essential tools
sudo apt install -y curl wget git build-essential software-properties-common \
    apt-transport-https ca-certificates gnupg lsb-release net-tools tmux \
    vim nano htop jq unzip
```

## Step 2: Install Python 3.12 (Latest Stable)

```bash
# Add deadsnakes PPA
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update

# Install Python 3.12
sudo apt install -y python3.12 python3.12-dev python3.12-venv python3-pip

# Verify installation
python3.12 --version
# Should show: Python 3.12.x
```

## Step 3: Install Docker (Latest)

```bash
# Remove old versions
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
    sudo apt remove $pkg 2>/dev/null || true
done

# Add Docker's official GPG key
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
# Should show: Docker version 25.x.x or 26.x.x
```

## Step 4: Install kubectl (Latest)

```bash
# Download latest kubectl
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"

# Install
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl

# Verify
kubectl version --client
# Should show: v1.30.x or v1.31.x
```

## Step 5: Install Kind 0.30.0 (Latest)

```bash
# For AMD64 (most EC2 instances)
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-amd64

# Install
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# Verify
kind version
# Should show: kind v0.23.0
```

## Step 6: Install Helm 3 (Latest)

```bash
# Install Helm using the official script
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Verify installation
helm version
# Should show: version.BuildInfo{Version:"v3.15.x"...}
```

## Step 7: Create Project Directory

```bash
# Create and enter project directory
mkdir -p ~/mcp-devops-agent
cd ~/mcp-devops-agent
```

## Step 8: Create Python Virtual Environment

```bash
# Create virtual environment
python3.12 -m venv venv

# Activate it
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip setuptools wheel

# Verify Python version in venv
python --version
# Should show: Python 3.12.x
```

## Step 9: Install Python Dependencies

```bash
# Create requirements.txt (copy the content from the artifact)
cat > requirements.txt << 'EOF'
openai==1.52.0
anthropic==0.39.0
kubernetes==30.1.0
pyyaml==6.0.2
requests==2.32.3
urllib3==2.2.3
prometheus-client==0.21.0
pydantic==2.9.2
pydantic-settings==2.6.1
typing-extensions==4.12.2
python-dotenv==1.0.1
aiofiles==24.1.0
aiohttp==3.10.10
httpx==0.27.2
flask==3.0.3
flask-cors==5.0.0
flask-socketio==5.3.7
python-socketio==5.11.4
eventlet==0.36.1
werkzeug==3.0.4
pytest==8.3.3
pytest-asyncio==0.24.0
black==24.10.0
flake8==7.1.1
mypy==1.11.2
rich==13.9.4
colorama==0.4.6
structlog==24.4.0
loguru==0.7.2
jsonschema==4.23.0
orjson==3.10.7
click==8.1.7
watchdog==5.0.3
python-dateutil==2.9.0.post0
tenacity==9.0.0
cryptography==43.0.1
certifi==2024.8.30
psutil==6.0.0
docker==7.1.0
EOF

# Install dependencies
pip install -r requirements.txt

# Verify key packages
pip list | grep -E "openai|flask|kubernetes"
```

## Step 10: Create Kind Cluster Configuration

```bash
cat > kind-config.yaml << 'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: mcp-cluster
nodes:
  - role: control-plane
    image: kindest/node:v1.30.0@sha256:047357ac0cfea04663786a612ba1eaba9702bef25227a794b52890dd8bcd692e
    extraPortMappings:
      # NodePort for services
      - containerPort: 30000
        hostPort: 30000
        protocol: TCP
        listenAddress: "0.0.0.0"
      - containerPort: 30001
        hostPort: 30001
        protocol: TCP
        listenAddress: "0.0.0.0"
      # Grafana
      - containerPort: 30030
        hostPort: 30030
        protocol: TCP
        listenAddress: "0.0.0.0"
      # Web UI
      - containerPort: 30080
        hostPort: 30080
        protocol: TCP
        listenAddress: "0.0.0.0"
      # Prometheus
      - containerPort: 30090
        hostPort: 30090
        protocol: TCP
        listenAddress: "0.0.0.0"
      # Alertmanager
      - containerPort: 30093
        hostPort: 30093
        protocol: TCP
        listenAddress: "0.0.0.0"
networking:
  apiServerAddress: "127.0.0.1"
  apiServerPort: 6443
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
EOF
```

## Step 11: Create Kubernetes Cluster

```bash
# Create cluster
kind create cluster --config kind-config.yaml --wait 120s

# Verify cluster
kubectl cluster-info
kubectl get nodes
# Should show 1 node in Ready state
```

## Step 12: Deploy Prometheus Stack

```bash
# Add Prometheus Helm repository
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add stable https://charts.helm.sh/stable
helm repo update

# Create monitoring namespace
kubectl create namespace monitoring

# Install kube-prometheus-stack
# This includes Prometheus, Grafana, and Alertmanager
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.service.type=NodePort \
  --set prometheus.service.nodePort=30090 \
  --set grafana.enabled=true \
  --set grafana.service.type=NodePort \
  --set grafana.service.nodePort=30030 \
  --set grafana.adminPassword=admin \
  --set alertmanager.service.type=NodePort \
  --set alertmanager.service.nodePort=30093 \
  --wait \
  --timeout 10m

# Verify deployment
kubectl get pods -n monitoring
# Should show prometheus, grafana, and alertmanager pods running

# Check services
kubectl get svc -n monitoring

# Wait for all pods to be ready
kubectl wait --for=condition=ready pod --all -n monitoring --timeout=300s

# Get Grafana admin password (if you forgot it)
kubectl get secret --namespace monitoring prometheus-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo

# Test Prometheus is accessible
curl -s http://localhost:30090/-/healthy
# Should return: Prometheus Server is Healthy.

# Test Grafana is accessible
curl -s http://localhost:30030/api/health
# Should return JSON with database status
```

## Step 13: Set Environment Variables

```bash
# Get EC2 public IP
export EC2_PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
echo "EC2 Public IP: $EC2_PUBLIC_IP"

# Create .env file
cat > .env << EOF
export OPENAI_API_KEY="your-openai-api-key-here"
export PYTHONPATH="\${PYTHONPATH}:\$(pwd)"
export KUBECONFIG="\${HOME}/.kube/config"
export EC2_PUBLIC_IP="$EC2_PUBLIC_IP"
export FLASK_HOST="0.0.0.0"
export FLASK_PORT="8082"
EOF

# Source it
source .env

# IMPORTANT: Edit .env and add your actual OpenAI API key
nano .env
```

## Step 14: Update Web Server for EC2

```bash
# Modify web_server.py to bind to all interfaces
# The server should already have host='0.0.0.0' in the socketio.run() call
# If not, update it:

# Check current binding
grep -n "socketio.run" web_server.py

# Should show: host='0.0.0.0', port=8082
```

## Step 15: Add Project Files

Place these files in ~/mcp-devops-agent/:
- server.py
- agent.py
- web_server.py
- web_interface.html
- requirements.txt

## Step 16: Test MCP Server

```bash
# Test server directly
python server.py
# Type: {"jsonrpc": "2.0", "method": "initialize", "id": "1", "params": {"protocolVersion": "2024-11-05", "clientInfo": {"name": "test", "version": "1.0"}}}
# Press Ctrl+C to exit
```

## Step 17: Run the System on EC2

### Option A: Direct Run (Recommended for EC2)

```bash
# Start in background with nohup
source venv/bin/activate
source .env

# Start web server in background
nohup python web_server.py > web_server.log 2>&1 &

# Check it's running
ps aux | grep web_server
tail -f web_server.log

# Access from your local machine:
echo "Access the web interface at: http://$EC2_PUBLIC_IP:8082"
echo "Access Prometheus at: http://$EC2_PUBLIC_IP:30090"
echo "Access Grafana at: http://$EC2_PUBLIC_IP:30030 (admin/admin)"
```

### Option B: Using tmux (Persistent Sessions)

```bash
# Create tmux session
tmux new-session -d -s mcp

# Start web server in tmux
tmux send-keys -t mcp 'cd ~/mcp-devops-agent && source venv/bin/activate && source .env && python web_server.py' C-m

# Attach to see logs
tmux attach -t mcp

# Detach with Ctrl+B then D
# List sessions: tmux ls
# Reattach: tmux attach -t mcp
```

### Option C: Systemd Service (Production-Ready)

```bash
# Create systemd service
sudo tee /etc/systemd/system/mcp-agent.service << EOF
[Unit]
Description=MCP DevOps Agent Web Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/mcp-devops-agent
Environment="PATH=/home/ubuntu/mcp-devops-agent/venv/bin"
EnvironmentFile=/home/ubuntu/mcp-devops-agent/.env
ExecStart=/home/ubuntu/mcp-devops-agent/venv/bin/python /home/ubuntu/mcp-devops-agent/web_server.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Start and enable service
sudo systemctl daemon-reload
sudo systemctl start mcp-agent
sudo systemctl enable mcp-agent

# Check status
sudo systemctl status mcp-agent

# View logs
sudo journalctl -u mcp-agent -f
```

## Step 18: Port Forwarding for Local Development (Optional)

If you want to access the EC2 services from your local machine via SSH tunnel:

```bash
# From your LOCAL machine, create SSH tunnel
ssh -i your-key.pem -L 8082:localhost:8082 ubuntu@<EC2_PUBLIC_IP>

# Now access at: http://localhost:8082
```

Or multiple ports:

```bash
# Forward multiple ports
ssh -i your-key.pem \
    -L 8082:localhost:8082 \
    -L 30090:localhost:30090 \
    -L 30030:localhost:30030 \
    -L 30093:localhost:30093 \
    ubuntu@<EC2_PUBLIC_IP>
```

## Verification Commands

```bash
# Check all versions
python --version          # Python 3.12.x
docker --version          # Docker version 25.x or 26.x
kubectl version --client  # Client Version: v1.30.x or v1.31.x
kind version             # kind v0.23.0
helm version             # version.BuildInfo{Version:"v3.15.x"...}
pip show openai          # Version: 1.52.0

# Check Kubernetes cluster
kubectl get nodes
kubectl get pods --all-namespaces

# Check Prometheus stack
kubectl get pods -n monitoring
kubectl get svc -n monitoring

# Test Prometheus is accessible
curl -s http://localhost:30090/-/healthy
# Should return: Prometheus Server is Healthy.

# Test Grafana is accessible
curl -s http://localhost:30030/api/health
# Should return: {"commit":"...","database":"ok","version":"..."}

# Check if web server is accessible
curl http://localhost:8082/api/status

# From outside (replace with your EC2 IP)
curl http://$EC2_PUBLIC_IP:8082/api/status
curl http://$EC2_PUBLIC_IP:30090/-/healthy
curl http://$EC2_PUBLIC_IP:30030/api/health

# Check listening ports
sudo netstat -tlnp | grep -E '(8082|30090|30030|30093)'
```

## Troubleshooting

### If can't access from browser:

```bash
# 1. Check Security Group
aws ec2 describe-security-groups --group-ids <your-sg-id>

# 2. Check if service is running
ps aux | grep web_server
sudo netstat -tlnp | grep 8082

# 3. Check firewall (Ubuntu)
sudo ufw status
# If active and blocking:
sudo ufw allow 8082
sudo ufw allow 30090
sudo ufw allow 30030

# 4. Test locally first
curl http://localhost:8082
curl http://localhost:30090/-/healthy
curl http://localhost:30030/api/health

# 5. Check EC2 public IP
curl http://169.254.169.254/latest/meta-data/public-ipv4
```

### If Prometheus/Grafana not working:

```bash
# Check if pods are running
kubectl get pods -n monitoring

# Check service endpoints
kubectl get endpoints -n monitoring

# Check logs
kubectl logs -n monitoring deployment/prometheus-kube-prometheus-operator
kubectl logs -n monitoring deployment/prometheus-grafana

# Restart if needed
kubectl rollout restart deployment -n monitoring
```

### If Kind cluster fails:

```bash
kind delete cluster --name mcp-cluster
docker system prune -af
kind create cluster --config kind-config.yaml
```

### Check logs:

```bash
# If using nohup
tail -f web_server.log

# If using systemd
sudo journalctl -u mcp-agent -f

# Docker logs
docker ps
docker logs <container-id>

# Kubernetes logs
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana
```

## Access Points

From your local browser (replace <EC2_PUBLIC_IP> with actual IP):

- **Web Interface**: http://<EC2_PUBLIC_IP>:8082
- **Prometheus**: http://<EC2_PUBLIC_IP>:30090
- **Grafana**: http://<EC2_PUBLIC_IP>:30030 (admin/admin)
- **Alertmanager**: http://<EC2_PUBLIC_IP>:30093
- **API Status**: http://<EC2_PUBLIC_IP>:8082/api/status
- **API Tools**: http://<EC2_PUBLIC_IP>:8082/api/tools

## Quick Test

After setup:
1. Get your EC2 public IP: `echo $EC2_PUBLIC_IP`
2. Open browser: `http://<EC2_PUBLIC_IP>:8082`
3. Click "Connect" button
4. Type: "Show me all pods"
5. You should see MCP tools being executed
6. Check Prometheus metrics: `http://<EC2_PUBLIC_IP>:30090`
7. Access Grafana dashboards: `http://<EC2_PUBLIC_IP>:30030` (login: admin/admin)

## Security Notes for Production

1. **Use HTTPS**: Add SSL/TLS certificates (Let's Encrypt)
2. **Restrict Security Group**: Limit source IPs to known ranges
3. **API Key Security**: Use AWS Secrets Manager for API keys
4. **Authentication**: Add authentication layer to web interface
5. **Rate Limiting**: Implement rate limiting for API endpoints

## Stopping Services

```bash
# If using nohup
pkill -f web_server.py

# If using tmux
tmux kill-session -t mcp

# If using systemd
sudo systemctl stop mcp-agent

# Stop Prometheus stack
helm uninstall prometheus -n monitoring

# Delete Kind cluster
kind delete cluster --name mcp-cluster
```
