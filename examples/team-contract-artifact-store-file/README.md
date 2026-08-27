# File Artifact Store adapter

This SDK example implements the external-command Artifact Store SPI with an
immutable, content-addressed filesystem. It is suitable for local development
or a shared filesystem. Production teams can implement the same protocol over
S3, MinIO, Azure Blob, or another durable object store without changing the
migration workflow.

Generate a configuration with an explicit namespace allow-list:

```powershell
$env:PDR_ARTIFACT_STORE_ROOT = 'D:\pdr-artifacts'
python create_artifact_store_config.py `
  --python (Get-Command python).Source `
  --adapter (Resolve-Path .\file_artifact_store_adapter.py) `
  --store-id team-evidence `
  --namespace-id migration-0001 `
  --root-environment PDR_ARTIFACT_STORE_ROOT `
  --output D:\pdr-config\artifact-store.json
```

The client pins the configuration, executable, and adapter bytes; negotiates
capabilities; enforces a maximum artifact size; verifies every SHA-256 and byte
count; and reads every write back before returning a reference. The reference
contains no host path, only store, namespace, digest, size, and media type.

The file adapter is not a distributed object store. Cross-host production use
requires a shared filesystem or an independently qualified remote adapter.
