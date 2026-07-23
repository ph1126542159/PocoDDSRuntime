# PocoDDS Runtime WebUI Bundles

This directory contains page Bundles only. HTTP/HTTPS serving, authentication,
request dispatching and Bundle administration are provided by the migrated
`platform/OSP` components:

- `OSP/Web`
- `OSP/WebServer`
- `OSP/SecureWebServer`
- `OSP/SimpleAuth`
- `OSP/BundleAdmin`
- `OSP/WebEvent`

Each direct child directory is an independently packaged OSP Web Bundle:

```text
webui/
├─ home/
├─ login/
├─ tracing/
└─ <new-feature>/
```

Every page directory owns its frontend source, generated `bundle/webui`
resources, `extensions.xml`, Bundle specification and `CMakeLists.txt`.
The root CMake file discovers page directories automatically.

To add a page, copy an existing directory, assign a unique target and symbolic
name, select a unique URL path in `bundle/extensions.xml`, then build its
`<target>_Package` target.

Default development URLs are:

- `/home/`
- `/login/`
- `/tracing/`
- `/bundleAdmin` (provided by `platform/OSP/BundleAdmin`)
