#!/bin/bash

# Variables
SERVICE_NAME="trmnlServer"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_SCRIPT_PATH="$(dirname "$(realpath "$0")")/trmnlServer.py"
WORKING_DIRECTORY="$(dirname "$(realpath "$0")")"
# USER="openhabian"
# GROUP="openhab"
# Function to display help
display_help() {
    echo "Usage: $0 [-doit | -uninstall]"
    echo
    echo "Options:"
    echo "  -doit       Install the service"
    echo "  -uninstall  Uninstall the service"
    echo "  -help       Display this help message"
}

# Check for parameters
if [ -z "$1" ]; then
    display_help
    exit 1
fi

# USER and GROUP variables - with default values when it should be root
# USER="abcdefg"
# GROUP="-----"
# Function to install the service
install_service() {
    # Create systemd service file
    echo "Creating systemd service file..."
    cat <<EOL > ${SERVICE_FILE}
[Unit]
Description=Trmnl Server Service
After=network.target

[Service]
ExecStart=/usr/bin/python3 ${PYTHON_SCRIPT_PATH}
WorkingDirectory=${WORKING_DIRECTORY}
StandardOutput=file:/var/log/trmnlServer.log
StandardError=file:/var/log/trmnlServer_error.log
Restart=always
# User=${USER}
# Group=${GROUP}
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOL

    # Reload systemd to recognize the new service
    echo "Reloading systemd..."
    systemctl daemon-reload

    # Enable the service to start on boot
    echo "Enabling the service to start on boot..."
    systemctl enable ${SERVICE_NAME}.service

    # Start the service
    echo "Starting the service..."
    systemctl start ${SERVICE_NAME}.service

    # Check the status of the service
    echo "Checking the status of the service..."
    systemctl status ${SERVICE_NAME}.service
}

# Function to uninstall the service
uninstall_service() {
    # Stop the service
    echo "Stopping the service..."
    systemctl stop ${SERVICE_NAME}.service

    # Disable the service
    echo "Disabling the service..."
    systemctl disable ${SERVICE_NAME}.service

    # Remove the service file
    echo "Removing the service file..."
    rm -f ${SERVICE_FILE}

    # Reload systemd to recognize the changes
    echo "Reloading systemd..."
    systemctl daemon-reload

    echo "Service uninstalled."
}

# Check for the uninstall parameter
if [ "$1" = "-uninstall" ]; then
    uninstall_service
else
    install_service
fi