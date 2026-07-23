# PocoDDS Runtime WebUI

WebUI is embedded in `pdr-runtime` and uses the live OSP `BundleLoader`,
`ServiceRegistry` and runtime configuration. It provides:

- process, service, module and Bundle inventory;
- in-memory log filtering by level, source and keyword;
- per-entity configuration editing with optional owner-Bundle restart;
- Bundle start, stop, restart and uninstall;
- service/module lifecycle routing to the Bundle that owns the entity;
- process stop and supervisor-command-based restart.

## Start

The normal runtime configuration enables the local console at:

```text
http://127.0.0.1:9080/
```

Relevant settings are in `config/pdr-runtime.properties`:

```properties
webui.enabled = true
webui.bindAddress = 127.0.0.1
webui.port = 9080
webui.bearerToken =
webui.logCapacity = 2000
webui.process.restartCommand =
```

Loopback access can run without a token. A non-loopback bind is rejected unless
`webui.bearerToken` contains at least 16 characters. Process restart is rejected
until `webui.process.restartCommand` is set (for example to a `systemctl restart`
command); this keeps restart ownership with the platform supervisor.

Configuration updates change the live `LayeredConfiguration`. Enabling
"应用后重启所属 Bundle" stops and starts the owner Bundle so Bundle activators
read the new values immediately. These runtime overrides are not written back
to the properties file.

`tests/smoke.properties` is a minimal OSP-only verification profile for WebUI
API tests. It intentionally excludes application Bundles and is not a production
configuration.

The frontend uses React 19 and Vite 8. It is organized as a Portal Shell plus
independent OSP Web Bundle projects. See `bundles/README.md` for the extension
contract. Build all production assets after frontend changes:

```powershell
Set-Location webui
npm install
npm run build
```
