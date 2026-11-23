"""HTTPS that verifies certificates in every Sublime Text plugin host, with the standard library.

Sublime Text brings its own Python and OpenSSL. Where that OpenSSL does not find the system's
certificate authorities (it looks in its build's folders), the system's bundle is added; on
Windows and macOS Python reads the system's store. Certificates are always verified.
"""

import os
import ssl

# The system's bundle of certificate authorities, by system (the first one that exists is used).
CA_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",  # Fedora, RHEL, CentOS
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora, RHEL (newer)
    "/etc/ssl/ca-bundle.pem",  # openSUSE
    "/etc/ssl/cert.pem",  # macOS, Alpine, OpenBSD
    "/usr/local/etc/ssl/cert.pem",  # FreeBSD
)


def authorities(context):
    try:
        return context.cert_store_stats().get("x509_ca", 0)
    except Exception:  # noqa: BLE001 (any failure means: none known)
        return 0


def make_context(ca_files=CA_FILES, exists=os.path.isfile):
    """A verifying TLS context that knows the system's certificate authorities."""
    context = ssl.create_default_context()
    if authorities(context) == 0 and not os.environ.get("SSL_CERT_FILE"):
        for path in ca_files:
            if exists(path):
                try:
                    context.load_verify_locations(cafile=path)
                except (OSError, ssl.SSLError):
                    continue
                if authorities(context):
                    break
    return context
