# File Backend Config Resolver example

This adapter maps a portable backend configuration reference to a pinned local
backend configuration. Shared migration state contains only
`resolverId/configId/backendId/revision`; the resolver mapping, absolute paths,
executable pins, and credential-environment policy remain local to each host.

Create one resolver config per operator host. Keep the same logical reference
values on every host, while allowing `configPath` and `configSha256` to differ.
The resolver config pins both this adapter and its local mapping file.

```powershell
python create_resolver_config.py `
  --python C:\Python312\python.exe `
  --adapter C:\pdr\file_backend_config_resolver_adapter.py `
  --resolver-id production-registry-backends `
  --entry primary-v1 deploy-2026-08 C:\pdr\primary-backend.json `
  --entry standby-v1 deploy-2026-08 C:\pdr\standby-backend.json `
  --mapping-output C:\pdr\backend-config-map.json `
  --output C:\pdr\backend-config-resolver.json
```

The mapping is a deployment input and may contain host-local paths. It must not
be copied into migration transactions or evidence. Do not place secrets in the
mapping; backend configs should name approved environment variables or a future
credential-provider integration rather than contain secret values.
