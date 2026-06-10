cd "$(dirname "$0")"
security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db ./PRCRootCertificate.crt