# WebUI Bundle projects

The WebUI is a portal plus independently packaged OSP Bundles:

```text
webui/
├─ src/                 Portal Shell only
└─ bundles/
   ├─ login/            pdr.webui.login entry Bundle
   ├─ home/             pdr.webui.home dashboard Bundle
   └─ <feature>/        one directory, CMakeLists and one .bndl per page
```

Each module owns its React source, Vite configuration, `manifest.json`,
`.bndlspec` and generated `bundle/webui` resources. The C++ server discovers
active OSP Bundles containing `webui/manifest.json`; there is no hard-coded
feature menu.

## Add a feature Bundle

1. Copy an existing Bundle directory and give it a unique package name and
   OSP symbolic name such as `pdr.webui.logs`.
2. Set its reader-facing title, ordering and visibility in
   `static/manifest.json`.
3. Build the frontend so `bundle/webui/index.html` and assets exist.
4. Add a local `CMakeLists.txt` containing
   `pdr_add_webui_bundle(<target> <spec-file>)`. The parent automatically
   discovers the directory; no central registration is required.
5. Build the corresponding `<target>_Package` target. Copy the resulting
   `.bndl` to the configured OSP repository.

The runtime Bundle monitor then performs the normal stop, unload, resolve and
start lifecycle. Once the new Bundle is active, refreshing the portal module
catalog makes it available in navigation.

## Manifest contract

```json
{
  "id": "pdr.webui.logs",
  "title": "日志查询",
  "description": "检索运行时日志",
  "icon": "logs",
  "order": 200,
  "hidden": false,
  "entry": "index.html"
}
```

`id` is replaced at runtime with the actual OSP symbolic name, preventing a
resource manifest from impersonating another installed Bundle.
