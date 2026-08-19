# ROS 2 workspace

This workspace replaces direct Fast-DDS usage on the robotics path. ROS 2 owns
the middleware through RMW; the portable core never includes an RMW or DDS
header.

Build the core and install it first, then source ROS 2 and run:

```powershell
colcon build --symlink-install --cmake-args
  -DCMAKE_PREFIX_PATH=E:/PocoDDSRuntime/build/install
```

The first package generates the typed message/service/action contracts. The
second package provides a managed Lifecycle node and a cancellable Action
server backed by the deterministic in-memory simulator. Gazebo, Isaac Sim,
Webots and MuJoCo adapters should map their state and command channels onto
these contracts rather than adding simulator-specific types to behavior code.
