#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace PocoDDS::Devices
{
struct Vector3
{
    double x{0};
    double y{0};
    double z{0};
};

struct GeoPosition
{
    double latitude{0};
    double longitude{0};
    double altitude{0};
    double speed{0};
    double course{0};
    std::int64_t timestampMicroseconds{0};
};

struct Image
{
    std::string encoding;
    std::uint32_t width{0};
    std::uint32_t height{0};
    std::vector<std::uint8_t> data;
};

struct BarcodeRead
{
    std::string format;
    std::string value;
    std::int64_t timestampMicroseconds{0};
};
} // namespace PocoDDS::Devices
