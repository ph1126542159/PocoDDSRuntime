# Governance Approval Signer reference adapter

This example implements the external-command Governance Approval Signer protocol
with a local Ed25519 PEM key. It is intended for SDK integration tests and local
development. Production deployments should replace this adapter with a KMS,
HSM, Vault, or enterprise signing service implementation so private key material
never leaves the security boundary.

`create_signer_config.py` creates both the public, pinned host configuration and
the adapter-private mapping. The host receives only public keys and invokes the
adapter with a domain-separated canonical payload. That payload binds the
purpose, approval product, approver, key, subject SHA, signer identity, signer
config SHA, and capability-manifest SHA. The host independently verifies every
returned signature before emitting a schema-version 2 approval envelope.

The three supported purposes are `governance-approval`,
`adapter-certifier-trust-approval`, and
`adapter-certifier-trust-migration-approval`. Configure only the purposes that
the particular signer is authorized to serve.

Exactly one signing mode must be selected by an approval command:

- local compatibility mode: `--private-key-environment NAME`
- external signer mode: `--signer-config FILE --expected-signer-config-sha256 SHA256`

The external signer config, executable, mapping, and public keys are all pinned.
Capability negotiation binds signer identity, approver identity, key IDs, and
allowed purposes. Rejection details and adapter stderr are intentionally not
exposed by the host.
