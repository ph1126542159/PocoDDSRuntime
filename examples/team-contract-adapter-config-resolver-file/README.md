# Adapter Config Resolver file reference

This SDK-only adapter maps portable, typed Adapter configuration references to
host-local, SHA-256-pinned files. Each entry binds a config ID, revision,
Adapter kind and Adapter identity, and is explicitly authorized for one or more
consumer scopes. Production implementations can use a signed configuration
service, workload identity, or a policy engine behind the same protocol.

The reference mapping contains local absolute paths and therefore belongs to
one host. It must never be copied into a Fleet Plan or treated as a portable
deployment artifact.

