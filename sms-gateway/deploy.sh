#!/bin/bash
set -e

# SMS Gateway API Deployment Script for Raspberry Pi
# This script sets up the API server with proper permissions and systemd service

echo "======================================"
echo "SMS Gateway API Deployment"
echo "======================================"
echo ""

# Configuration
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="sms-gateway-api"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
USER=$(whoami)

echo "Project directory: $PROJECT_DIR"
echo "Running as user: $USER"
echo ""

# Step 1: Check Python version
echo "[1/8] Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install it first:"
    echo "   sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip"
    exit 1
fi
PYTHON_VERSION=$(python3 --version)
echo "✅ Found: $PYTHON_VERSION"
echo ""

# Step 2: Create virtual environment
echo "[2/8] Setting up Python virtual environment..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi
echo ""

# Step 3: Install dependencies
echo "[3/8] Installing Python dependencies..."
"$PROJECT_DIR/venv/bin/pip" install --upgrade pip setuptools wheel
"$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
echo "✅ Dependencies installed"
echo ""

# Step 4: Create .env file if it doesn't exist
echo "[4/8] Configuring environment variables..."
if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
        
        # Generate a secure API key
        API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        
        # Update .env with generated key
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s/API_KEY=CHANGE_ME_TO_A_SECURE_RANDOM_STRING/API_KEY=$API_KEY/" "$PROJECT_DIR/.env"
        else
            # Linux
            sed -i "s/API_KEY=CHANGE_ME_TO_A_SECURE_RANDOM_STRING/API_KEY=$API_KEY/" "$PROJECT_DIR/.env"
        fi
        
        echo "✅ Created .env file with generated API key"
        echo "⚠️  IMPORTANT: Your API key is: $API_KEY"
        echo "⚠️  Save this key securely - you'll need it to make API requests"
    else
        echo "❌ .env.example not found. Please create .env manually."
        exit 1
    fi
else
    echo "✅ .env file already exists"
fi
echo ""

# Step 5: Create logs directory
echo "[5/8] Creating logs directory..."
mkdir -p "$PROJECT_DIR/logs"
chmod 755 "$PROJECT_DIR/logs"
echo "✅ Logs directory ready"
echo ""

# Step 6: Test API startup
echo "[6/8] Testing API server..."
if "$PROJECT_DIR/venv/bin/python" -c "import main" 2>/dev/null; then
    echo "✅ API imports successfully"
else
    echo "❌ Failed to import API. Check for errors above."
    exit 1
fi
echo ""

# Step 7: Install systemd service (requires sudo)
echo "[7/8] Installing systemd service..."
if [ -f "$PROJECT_DIR/sms-gateway-api.service" ]; then
    # Update service file with actual paths
    cat "$PROJECT_DIR/sms-gateway-api.service" | \
        sed "s|/home/pi/sms-gateway|$PROJECT_DIR|g" | \
        sed "s|User=pi|User=$USER|g" | \
        sed "s|Group=pi|Group=$USER|g" \
        > /tmp/sms-gateway-api.service
    
    echo "Installing service file (requires sudo)..."
    sudo cp /tmp/sms-gateway-api.service "$SERVICE_FILE"
    sudo systemctl daemon-reload
    echo "✅ Systemd service installed"
else
    echo "⚠️  Service file not found. Skipping systemd installation."
    echo "   You can start the server manually with:"
    echo "   $PROJECT_DIR/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000"
fi
echo ""

# Step 8: Enable and start service
if [ -f "$SERVICE_FILE" ]; then
    echo "[8/8] Starting service..."
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl restart "$SERVICE_NAME"
    
    sleep 2
    
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        echo "✅ Service is running"
        echo ""
        echo "======================================"
        echo "✅ Deployment Complete!"
        echo "======================================"
        echo ""
        echo "Service status:"
        sudo systemctl status "$SERVICE_NAME" --no-pager -l
        echo ""
        echo "Useful commands:"
        echo "  Start:   sudo systemctl start $SERVICE_NAME"
        echo "  Stop:    sudo systemctl stop $SERVICE_NAME"
        echo "  Restart: sudo systemctl restart $SERVICE_NAME"
        echo "  Status:  sudo systemctl status $SERVICE_NAME"
        echo "  Logs:    sudo journalctl -u $SERVICE_NAME -f"
        echo ""
        echo "Test the API:"
        echo "  curl http://localhost:8000/health"
        echo ""
        
        # Show API key reminder
        if [ -f "$PROJECT_DIR/.env" ]; then
            CURRENT_KEY=$(grep "^API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
            echo "⚠️  Remember your API key: $CURRENT_KEY"
        fi
    else
        echo "❌ Service failed to start. Check logs:"
        echo "   sudo journalctl -u $SERVICE_NAME -n 50"
        exit 1
    fi
else
    echo "[8/8] Manual start required"
    echo ""
    echo "======================================"
    echo "✅ Setup Complete!"
    echo "======================================"
    echo ""
    echo "Start the server manually with:"
    echo "  cd $PROJECT_DIR"
    echo "  source venv/bin/activate"
    echo "  uvicorn main:app --host 0.0.0.0 --port 8000"
fi
