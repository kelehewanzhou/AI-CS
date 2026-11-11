#!/bin/sh
set -eu
# Only configuration variables are substituted: preserve all native $uri/$request_id.
case "${NGINX_SERVER_NAME:-localhost}" in *[!a-zA-Z0-9._-]*|'') echo 'Invalid server name' >&2; exit 1;; esac
export NGINX_SERVER_NAME="${NGINX_SERVER_NAME:-localhost}"
ORIGIN_ENTRIES=''
old_ifs=$IFS
IFS=,
for origin in ${ALLOWED_ORIGINS:?ALLOWED_ORIGINS is required}; do
    if ! printf '%s' "$origin" | grep -Eq '^https?://[a-zA-Z0-9.-]+(:[0-9]+)?$'; then
        echo 'Invalid allowed Origin' >&2; exit 1
    fi
    ORIGIN_ENTRIES="${ORIGIN_ENTRIES}    \"${origin}\" 1;
"
done
TRUSTED_PROXY_ENTRIES=''
for network in ${NGINX_TRUSTED_PROXIES:-}; do
    if ! printf '%s' "$network" | grep -Eq '^[0-9a-fA-F:.]+(/[0-9]{1,3})?$'; then
        echo 'Invalid trusted proxy network' >&2; exit 1
    fi
    case "$network" in 0.0.0.0/0|::/0) echo 'Unrestricted proxy trust is forbidden' >&2; exit 1;; esac
    TRUSTED_PROXY_ENTRIES="${TRUSTED_PROXY_ENTRIES}set_real_ip_from ${network};
"
done
IFS=$old_ifs
if [ -n "$TRUSTED_PROXY_ENTRIES" ]; then
    TRUSTED_PROXY_ENTRIES="${TRUSTED_PROXY_ENTRIES}real_ip_header X-Forwarded-For;
real_ip_recursive on;"
fi
export ORIGIN_ENTRIES TRUSTED_PROXY_ENTRIES
envsubst '${ORIGIN_ENTRIES} ${TRUSTED_PROXY_ENTRIES}' < /opt/kglearn/templates/maps.conf.template > /etc/nginx/conf.d/00-maps.conf
case "${NGINX_TLS:-0}" in
    0) template=http;;
    1) template=https;;
    *) echo 'NGINX_TLS must be 0 or 1' >&2; exit 1;;
esac
envsubst '${NGINX_SERVER_NAME}' < "/opt/kglearn/templates/${template}.conf.template" > /etc/nginx/conf.d/default.conf
nginx -t
