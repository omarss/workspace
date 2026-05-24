# OpenBao server configuration for the local dev / homelab MVP.
#
# Production overlay flips tls_disable = 0, points listener at the right cert,
# and switches to the cloud-KMS auto-unseal seal stanza per ADR 006.

ui = true

# OpenBao 2.5+ removed the disable_mlock knob entirely (the upstream
# dropped mlock support; preventing memory from swapping now relies on the
# host swap being disabled or LUKS-encrypted). See:
#   https://openbao.org/docs/install/#post-installation-hardening
# Both homelab and production hosts satisfy this; we no longer set the
# (now-rejected) disable_mlock key.

listener "tcp" {
  address     = "0.0.0.0:8200"
  # tls_disable = 1 is dev-only. The production overlay layered on top of
  # this base config sets tls_disable = 0 and points at the cert manager-
  # provisioned chain.
  tls_disable = 1
}

storage "file" {
  path = "/openbao/data"
}

api_addr     = "http://0.0.0.0:8200"
cluster_addr = "http://0.0.0.0:8201"

# OpenBao 2.5+ removed API-based audit device management — devices MUST be
# declared in config. The file device below logs every authenticated and
# unauthenticated request to /openbao/logs/audit.log (which lives on a
# named volume so it survives container restarts).
audit "file" "primary" {
  options = {
    file_path = "/openbao/logs/audit.log"
    log_raw   = "false"
  }
}
