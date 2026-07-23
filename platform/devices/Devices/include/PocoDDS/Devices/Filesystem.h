#pragma once

#if defined(__GNUC__) && !defined(__clang__) && (__GNUC__ < 8)
#include <experimental/filesystem>
namespace PocoDDS
{
namespace Filesystem = std::experimental::filesystem;
}
#else
#include <filesystem>
namespace PocoDDS
{
namespace Filesystem = std::filesystem;
}
#endif
