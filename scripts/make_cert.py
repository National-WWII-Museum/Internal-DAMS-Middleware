"""
make_cert.py
Creates a self-signed certificate so uvicorn can serve HTTPS and NetX can
send webhooks to it. Writes certs/server.crt and certs/server.key.

The cert covers this machine's hostname, its full DNS name, and any extra
names/IPs passed on the command line. server.key is private: it never leaves
this VM and is git-ignored. Only server.crt gets copied to the NetX VM and
imported into NetX's Java truststore.

Needs the cryptography package (one-time, not a project dependency):
    python -m pip install cryptography

Run from the repo root:
    python scripts/make_cert.py
    python scripts/make_cert.py 10.0.0.25 dams-mw.example.org
"""
import ipaddress
import socket
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

VALID_DAYS = 365 * 5
CERT_DIR = Path(__file__).resolve().parent.parent / "certs"


def _san_entries(extra):
    names = {socket.gethostname(), socket.getfqdn(), "localhost"}
    ips = {"127.0.0.1"}
    for item in extra:
        try:
            ipaddress.ip_address(item)
            ips.add(item)
        except ValueError:
            names.add(item)
    entries = [x509.DNSName(n) for n in sorted(names) if n]
    entries += [x509.IPAddress(ipaddress.ip_address(i)) for i in sorted(ips)]
    return entries, sorted(names), sorted(ips)


def main():
    CERT_DIR.mkdir(exist_ok=True)
    cert_path = CERT_DIR / "server.crt"
    key_path = CERT_DIR / "server.key"
    if cert_path.exists() or key_path.exists():
        sys.exit(f"{CERT_DIR} already has a cert/key - delete them first to make a new one.")

    san, names, ips = _san_entries(sys.argv[1:])
    common_name = socket.getfqdn() or socket.gethostname()

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "DAMS Middleware (self-signed)"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"Wrote {cert_path}")
    print(f"Wrote {key_path}  (keep private - do not copy off this VM)")
    print(f"Valid until {cert.not_valid_after_utc:%Y-%m-%d}" if hasattr(cert, "not_valid_after_utc")
          else f"Valid until {cert.not_valid_after:%Y-%m-%d}")
    print("Covers names:", ", ".join(names))
    print("Covers IPs:  ", ", ".join(ips))


if __name__ == "__main__":
    main()
