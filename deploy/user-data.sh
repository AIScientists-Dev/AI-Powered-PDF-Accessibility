#!/bin/bash
set -e

# Log all output
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

echo "=== Starting Accessibility MCP Server Setup ==="
echo "Time: $(date)"

# Update system
echo "=== Updating system ==="
dnf update -y
dnf install -y git python3.11 python3.11-pip java-17-amazon-corretto wget unzip

# Create app user
useradd -m -s /bin/bash mcpuser || true

# Install veraPDF
echo "=== Installing veraPDF ==="
cd /tmp
wget -q https://software.verapdf.org/releases/1.26/verapdf-greenfield-1.26.2-installer.zip || {
    echo "Failed to download veraPDF, trying alternative..."
    wget -q https://github.com/veraPDF/veraPDF-apps/releases/download/v1.26.2/verapdf-greenfield-1.26.2-installer.zip
}
unzip -q verapdf-greenfield-1.26.2-installer.zip
cd verapdf-greenfield-1.26.2

# Create auto-install config
cat > auto-install.xml << 'XMLEOF'
<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<AutomatedInstallation langpack="eng">
  <com.izforge.izpack.panels.htmlhello.HTMLHelloPanel id="welcome"/>
  <com.izforge.izpack.panels.target.TargetPanel id="install_dir">
    <installpath>/opt/verapdf</installpath>
  </com.izforge.izpack.panels.target.TargetPanel>
  <com.izforge.izpack.panels.packs.PacksPanel id="sdk_pack_select">
    <pack index="0" name="veraPDF Mac and *nix Scripts" selected="true"/>
    <pack index="1" name="veraPDF Validation model" selected="true"/>
    <pack index="2" name="veraPDF Documentation" selected="false"/>
    <pack index="3" name="veraPDF Sample Plugins" selected="false"/>
  </com.izforge.izpack.panels.packs.PacksPanel>
  <com.izforge.izpack.panels.install.InstallPanel id="install"/>
  <com.izforge.izpack.panels.finish.FinishPanel id="finish"/>
</AutomatedInstallation>
XMLEOF

java -jar verapdf-greenfield-1.26.2-installer.jar auto-install.xml
ln -sf /opt/verapdf/verapdf /usr/local/bin/verapdf
chmod +x /opt/verapdf/verapdf

# Verify veraPDF
echo "=== Verifying veraPDF ==="
/usr/local/bin/verapdf --version || echo "veraPDF verification will work after path update"

# Create app directory
echo "=== Setting up application directory ==="
mkdir -p /home/mcpuser/app
chown -R mcpuser:mcpuser /home/mcpuser/app

# Setup Python virtual environment
echo "=== Setting up Python ==="
cd /home/mcpuser/app
sudo -u mcpuser python3.11 -m venv venv
sudo -u mcpuser /home/mcpuser/app/venv/bin/pip install --upgrade pip

# Install base dependencies
sudo -u mcpuser /home/mcpuser/app/venv/bin/pip install \
    fastapi \
    uvicorn \
    python-multipart \
    mcp \
    pikepdf \
    PyMuPDF \
    google-generativeai \
    Pillow \
    python-dotenv \
    click \
    rich

# Create placeholder for environment file (will be updated with actual code deployment)
cat > /home/mcpuser/app/.env << 'ENVEOF'
GEMINI_API_KEY=PLACEHOLDER_WILL_BE_UPDATED
PORT=8080
HOST=0.0.0.0
ENVEOF
chmod 600 /home/mcpuser/app/.env
chown mcpuser:mcpuser /home/mcpuser/app/.env

# Create systemd service
echo "=== Creating Systemd Service ==="
cat > /etc/systemd/system/accessibility-mcp.service << 'SERVICEEOF'
[Unit]
Description=Accessibility MCP HTTP Server
After=network.target

[Service]
Type=simple
User=mcpuser
WorkingDirectory=/home/mcpuser/app
Environment=PATH=/home/mcpuser/app/venv/bin:/usr/local/bin:/usr/bin
EnvironmentFile=/home/mcpuser/app/.env
ExecStart=/home/mcpuser/app/venv/bin/python -m uvicorn http_server:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable accessibility-mcp

# Create a ready flag
touch /home/mcpuser/.setup-complete

echo "=== Setup Complete ==="
echo "Time: $(date)"
echo "Next step: Deploy application code to /home/mcpuser/app/"
