# macchina.io research notes

## What to retain

- OSP BundleActivator and BundleContext make lifecycle explicit and testable.
- ServiceRegistry separates service contracts from providers inside one process.
- Bundle metadata and dependency resolution are a useful deployment model.
- The server owns orderly start/stop and configuration, instead of leaving lifecycle to plugins.

## What to replace

- RemotingNG generated proxies, remote objects, skeletons, ORB registration and transport-specific
  helpers couple business services to RPC machinery.
- The original web bundles mix administration pages with runtime plugins. The new admin plane is a
  private, authenticated service and is not a required dependency of the runtime.
- CppUnit/Make-based testing is replaced by CMake/CTest/GoogleTest.

## Migration rule

Business interfaces become versioned DDS IDL contracts. Events map directly to topics. Synchronous
methods use explicit request/reply topics with correlation IDs, deadlines and cancellation; they must
not pretend DDS is a transparent local method call. Existing bundles migrate one vertical slice at a
time behind `ITransport` so Core never depends on generated DDS types.

