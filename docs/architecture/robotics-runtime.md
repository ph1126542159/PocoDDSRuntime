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
cmake --preset robotics
cmake --build --preset robotics
ctest --preset robotics -C Release -V
cmake --install build/robotics --config Release
```

The same preset is valid on Linux with an available C++17 compiler. Generator
selection is intentionally left to CMake. Qt is neither discovered nor built by
this preset. A `cmake.exe` shipped beside an existing Qt installation may be
used as a CMake executable, but no Qt library is required.

## Run the local robot simulation

The portable build produces `pdr-robot-sim`, a deterministic, no-Qt software-
in-the-loop scenario. It exercises the startup interlock, Lifecycle runtime,
behavior orchestration, Action progress, planar base motion, joint feedback,
continuous command watchdog, emergency stop, and backend health in one process:

```powershell
build\robotics\bin\pdr-robot-sim.exe
build\robotics\bin\pdr-robot-sim.exe --steps 1000 --period-ms 2
```

A successful run ends with `PDR_ROBOT_SIM_PASS` and reports the simulated pose.
The same scenario is registered as the `robotics-local-simulation` CTest. It
uses virtual time and normally finishes much faster than wall-clock time; it is
intended for repeatable framework testing, not performance or real-time claims.

## Replaceable business modules

Robot-specific workflows are isolated behind `RobotBusinessModule`. A module
publishes one or more named missions, builds them from reusable Behavior steps,
and receives hardware-independent state and command access through
`BusinessContext`. The core qualifies each Action as `module/mission`, so a new
robot can replace its business module without changing Lifecycle, safety,
hardware, simulation, ROS 2, or observability code.

The reference SDK includes three end-to-end examples:

| Module/mission | Simulated workflow |
|---|---|
| `warehouse/deliver` | Localize, avoid an obstacle, drive to pickup, acquire payload, survive command-source dropout, deliver, release |
| `inspection/patrol` | Sensor self-check, obstacle-aware patrol, anomaly analysis, return home |
| `pick_place/transfer` | Arm approach, close gripper, transfer, open gripper |

Run every workflow in the deterministic no-Qt simulator, or select one:

```powershell
build\robotics\bin\pdr-business-sim.exe --module all
build\robotics\bin\pdr-business-sim.exe --module warehouse
build\robotics\bin\pdr-business-sim.exe --module inspection
build\robotics\bin\pdr-business-sim.exe --module pick_place
```

Every step records its module, mission, status, input, output, tick range and
duration. ROS 2 republishes these records on `robot/business_steps` and accepts
missions through the existing `robot/execute_behavior` Action.

Modules can be compiled into the application or loaded from an explicit
`business_plugins` path. The host never scans a directory automatically. Treat
plugins as trusted native code and build them with the exact same SDK version,
compiler ABI, C++ runtime, architecture and build configuration as the host.
See `robotics/examples/SampleBusinessPlugin.cpp` and
`robotics/examples/README.md` for the minimal replacement pattern.

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
- `robot/execute_behavior` cancellable action;
- `robot/business_steps` durable business-step result stream.

Set `business_modules` to the built-in modules that should be exposed by the
node. Set `business_plugins` to explicit trusted DLL or shared-library paths;
then list those module names in `business_modules`. Empty lists preserve the
framework-only runtime with no robot-specific mission installed.

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
   continuous command watchdogs, vector/joint limits, behavior orchestration,
   cancellation, concurrent shutdown handling, and fault injection.
2. Implemented: ROS 2 messages, Lifecycle, Action, simulation/hardware topic
   backends, and a Gazebo differential-drive closed-loop model.
3. Integration boundary implemented: standard ROS odometry, joint state,
   velocity, and joint-command mappings for Gazebo, Webots, Isaac Sim, and
   MuJoCo adapters.
4. Implemented extension seam: compiled or dynamically loaded business modules,
   reference warehouse/inspection/pick-place missions, and per-step traces.
   A product can additionally bind Nav2, MoveIt 2, or another behavior-tree
   layer behind its module and hardware gateway.
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
interlock, executes the `inspection/patrol` business Action, verifies its four
step records, confirms the Gazebo robot drives to the asset and returns home,
then prints `PDR_GAZEBO_BUSINESS_TRACE` and `PDR_GAZEBO_SIL_PASS`. The same
closed-loop acceptance check runs in the `gazebo-sil` CI job.

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
