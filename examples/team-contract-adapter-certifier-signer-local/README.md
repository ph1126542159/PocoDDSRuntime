# Local Ed25519 Certifier Signer Example

This installed-SDK example implements the external-command Certifier Signer
protocol with local PEM files. It exists for development and contract tests;
production teams should implement the same bounded JSON protocol over their
KMS, HSM, or enterprise signing client without exporting private key bytes.

The host pins the Python executable, adapter, mapping, public key and signer
config. Only explicitly allowed environment variables reach the signer process.
The response signature is verified locally against the pinned public key before
an Adapter conformance attestation is emitted.
