#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Robotics
{
struct Vector3
{
    double x{0.0};
    double y{0.0};
    double z{0.0};
};

struct Quaternion
{
    double x{0.0};
    double y{0.0};
    double z{0.0};
    double w{1.0};
};

struct Pose
{
    Vector3 position;
    Quaternion orientation;
};

struct Twist
{
    Vector3 linear;
    Vector3 angular;
};

struct JointState
{
    std::string name;
    double position{0.0};
    double velocity{0.0};
    double effort{0.0};
};

struct RobotState
{
    std::int64_t monotonicTimeNanoseconds{0};
    std::string frameId{"base_link"};
    Pose pose;
    Twist twist;
    std::vector<JointState> joints;
};

enum class JointCommandMode
{
    position,
    velocity,
    effort
};

struct JointCommand
{
    std::string name;
    JointCommandMode mode{JointCommandMode::position};
    double value{0.0};
};

struct RobotCommand
{
    std::uint64_t sequence{0};
    Twist baseVelocity;
    std::vector<JointCommand> joints;
};

enum class SensorType
{
    imu,
    lidar,
    camera,
    depth,
    forceTorque,
    custom
};

struct SensorSample
{
    std::string name;
    SensorType type{SensorType::custom};
    std::string frameId;
    std::int64_t monotonicTimeNanoseconds{0};
    std::string encoding;
    std::vector<std::uint32_t> shape;
    std::vector<double> values;
    std::vector<std::uint8_t> data;
};

struct ContactState
{
    std::string firstBody;
    std::string secondBody;
    Vector3 point;
    Vector3 normal;
    double normalForce{0.0};
};

struct RobotFrame
{
    RobotState state;
    std::vector<SensorSample> sensors;
    std::vector<ContactState> contacts;
};
} // namespace PocoDDS::Robotics
