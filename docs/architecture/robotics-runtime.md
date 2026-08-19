# Embodied robotics runtime

## Scope

The robotics runtime is a cross-platform, transport-neutral control-plane core.
It defines typed robot state, lifecycle transitions, cancellable actions,
deterministic behavior sequencing, simulation/hardware ports and a fail-closed
safety boundary. It does not put hard real-time motor loops, physical e-stop
circuits or safety PLC functions into a desktop process.

The existing Poco/OSP runtime remains available during migration. The
`robotics` CMake preset builds only the new core and turns Qt, WebUI, Poco/OSP
and direct Fast-DDS code off. ROS 2 communication is built separately with
`colcon`, so ROS 2 selects its own RMW implementation without linking the old
Fast-DDS API into the same process.

## Build and test the portable core

```powershell
C:\Qt\Tools\CMake_64\bin\cmake.exe --preset robotics
C:\Qt\Tools\CMake_64\bin\cmake.exe --build --preset robotics
C:\Qt\Tools\CMake_64\bin\ctest.exe --preset robotics -C Release -V
C:\Qt\Tools\CMake_64\bin\cmake.exe --install build/robotics --config Release
```

The same preset is valid on Linux with an available C++17 compiler. Generator
selection is intentionally left to CMake.

## Build the ROS 2 adapter

After installing and sourcing a supported ROS 2 distribution:

```powershell
$env:CMAKE_PREFIX_PATH = "E:\PocoDDSRuntime\build\install;$env:CMAKE_PREFIX_PATH"
Set-Location E:\PocoDDSRuntime\robotics\ros2_ws
colcon build --merge-install --symlink-install
```

Source `install/local_setup.ps1`, start `pdr_robot_runtime_node`, then use the
standard lifecycle services to configure and activate it. The node exposes:

- `robot/state` and `robot/safety_state` typed topics;
- `robot/command` for base and joint commands, plus `robot/cmd_vel` convenience input;
- `robot/set_emergency_stop` fail-safe service;
- `robot/execute_behavior` cancellable action.

The node supports four backends:

- `in_memory` for deterministic unit tests;
- `mock_hardware` for hardware-path fault injection without a device;
- `topic_simulation` using `robot/sim/command` and `robot/sim/frame`;
- `topic_hardware` using `robot/hardware/command` and
  `robot/hardware/frame`.

The two topic backends require a first feedback frame before activation and
fail closed when feedback exceeds the configured timeout. The hardware backend
reports `simulated=false`; a CAN, EtherCAT, serial, vendor-SDK, or ros2_control
gateway can implement the other side of the contract.

## Simulation adapter contract

Every simulator adapter must support connect, reset, command injection,
deterministic stepping and state extraction. A backend must map simulation time,
world/base frames, joints, sensors and actuator units into the shared model.

| Backend | Integration path | Primary use | Boundary |
|---|---|---|---|
| In-memory | Native `SimulationAdapter` | Fast unit and safety tests | No contacts or sensor physics |
| Gazebo | `pdr_robot_bringup` SDF, `ros_gz_bridge`, and unified bridge | Reference closed-loop SIL | Linux CI installs the official ROS/Gazebo pairing |
| Isaac Sim | NVIDIA ROS 2 bridge | Photorealistic perception and synthetic data | GPU/platform/RMW matrix is narrower |
| Webots | `webots_ros2` driver/control packages | Cross-platform education and system tests | Controller and device mappings are backend-specific |
| MuJoCo | Native C API adapter or a separately qualified ROS 2 bridge | Dynamics and learning/control research | No official first-party ROS 2 bridge is assumed |

Simulation-in-the-loop is not hardware acceptance. Promotion to a real robot
requires the same behavior suite to pass against a hardware adapter, plus an
independent physical e-stop, limits, watchdog, power/current protection and
measured control-loop timing.

## Migration stages

1. Implemented: portable core, deterministic simulation, hardware abstraction,
   watchdogs, limits, behavior orchestration, cancellation, and fault injection.
2. Implemented: ROS 2 messages, Lifecycle, Action, simulation/hardware topic
   backends, and a Gazebo differential-drive closed-loop model.
3. Integration boundary implemented: standard ROS odometry, joint state,
   velocity, and joint-command mappings for Gazebo, Webots, Isaac Sim, and
   MuJoCo adapters.
4. Robot-specific extension: select Nav2, MoveIt 2, or another behavior-tree
   layer and bind a concrete hardware gateway for the target robot.
5. Promotion gate: pass SIL regression, HIL, tethered tests, independent
   physical e-stop validation, and measured control-loop timing.

## Gazebo SIL acceptance

On Ubuntu 24.04 / ROS 2 Jazzy, install `ros-jazzy-ros-gz`, build the workspace,
then run:

```bash
ros2 launch pdr_robot_bringup gazebo_sil.launch.py
ros2 run pdr_robot_bringup gazebo_sil_check.py
```

The checker waits for active Lifecycle state, releases the startup software
interlock, commands forward motion through the runtime, verifies at least
5 cm of displacement from `robot/state`, sends zero velocity, and prints
`PDR_GAZEBO_SIL_PASS`. The same check runs in the `gazebo-sil` CI job.

## External integration references

- Gazebo ROS 2 integration and `ros_gz_bridge`:
  <https://gazebosim.org/docs/harmonic/ros2_integration/>
- NVIDIA Isaac Sim ROS 2 bridge:
  <https://docs.isaacsim.omniverse.nvidia.com/latest/installation/install_ros.html>
- Cyberbotics Webots ROS 2 packages:
  <https://github.com/cyberbotics/webots_ros2>
- MuJoCo cross-platform C API and simulation loop:
  <https://mujoco.readthedocs.io/en/stable/programming/index.html>

These links establish supported integration mechanisms, not project acceptance.
Each selected simulator still needs a version-pinned adapter and closed-loop
test evidence in this repository.
