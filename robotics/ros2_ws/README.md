# ROS 2 workspace

This workspace replaces direct Fast-DDS usage on the robotics path. ROS 2 owns
the middleware through RMW; the portable core never includes an RMW or DDS
header.

Build the core and install it first, then source ROS 2 and run:

```powershell
colcon build --merge-install --symlink-install --cmake-args -DCMAKE_PREFIX_PATH=E:/PocoDDSRuntime/build/install
```

The workspace contains typed message/service/action contracts, a managed
Lifecycle runtime with a cancellable Action server, a simulator-neutral bridge,
and a headless Gazebo SIL reference robot. Runtime backends are selected by
configuration: `in_memory`, `mock_hardware`, `topic_simulation`, or
`topic_hardware`.

Run the Gazebo reference loop on ROS 2 Jazzy with `ros-jazzy-ros-gz` installed:

```bash
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch pdr_robot_bringup gazebo_sil.launch.py
ros2 run pdr_robot_bringup gazebo_sil_check.py
```

`topic_simulation` uses `robot/sim/command` and `robot/sim/frame`.
`topic_hardware` uses `robot/hardware/command` and `robot/hardware/frame`.
Device drivers must publish complete, time-bounded feedback before the runtime
can activate. Gazebo, Isaac Sim, Webots, MuJoCo, and physical-device adapters
map their channels onto these contracts rather than adding backend-specific
types to behavior code.
