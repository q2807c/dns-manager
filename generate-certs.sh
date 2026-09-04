#!/bin/bash
# Generate self-signed SSL certificates for nginx
set -e

CERT_DIR="./nginx/certs"
mkdir -p "$CERT_DIR"

if [ -f "$CERT_DIR/server.crt" ] && [ -f "$CERT_DIR/server.key" ]; then
    echo "SSL certificates already exist. Skipping."
    exit 0
fi

echo "Generating self-signed SSL certificates..."

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/C=CN/ST=Beijing/L=Beijing/O=CNOOC/CN=dns-manager.local"

echo "Certificates generated in $CERT_DIR/"
chmod 600 "$CERT_DIR/server.key"
echo "Done."
