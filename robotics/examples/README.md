# Custom robot business module

`SampleBusinessPlugin.cpp` is the smallest dynamically replaceable robot
workflow. It implements `custom_cleaning/clean_zone` without changing the core,
ROS 2 node, simulator adapter, hardware adapter, or safety boundary.

To create a product module:

1. Copy the sample and choose a stable module name and mission names.
2. Implement each mission as Behavior steps. Use `BusinessContext` for state,
   commands, named signals, virtual/control time, and result tracing.
3. Export exactly one `pdrBusinessPluginV1` descriptor.
4. Build the module against the same installed PDR SDK and the same compiler,
   C++ runtime, architecture, and Debug/Release configuration as the host.
5. Test it without Qt or ROS 2:

   ```powershell
   build\robotics\bin\pdr-business-sim.exe `
     --plugin build\robotics\bin\pdr-sample-business-plugin.dll `
     --module custom_cleaning
   ```

6. For ROS 2, put the explicit trusted library path in `business_plugins`, put
   `custom_cleaning` in `business_modules`, and execute the
   `custom_cleaning/clean_zone` Action.

Plugins are native code with process privileges. Do not auto-discover or load
untrusted files. The ABI version catches descriptor mismatches, but it does not
make different compilers or C++ runtimes binary-compatible. The descriptor also
binds the exact Robotics Runtime version and compiler/platform ABI fingerprint;
rebuild plugins whenever either contract changes.
