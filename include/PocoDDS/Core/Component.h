#pragma once

#include <map>
#include <string>

namespace PocoDDS::Core
{
enum class ComponentKind
{
    Process,
    Service,
    Bundle,
    Module
};

enum class ComponentState
{
    Discovered,
    Starting,
    Running,
    Stopping,
    Stopped,
    Failed
};

struct Component
{
    std::string id;
    std::string name;
    std::string host;
    int processId{0};
    ComponentKind kind{ComponentKind::Module};
    ComponentState state{ComponentState::Discovered};
    std::map<std::string, std::string> metadata;
};
} // namespace PocoDDS::Core
