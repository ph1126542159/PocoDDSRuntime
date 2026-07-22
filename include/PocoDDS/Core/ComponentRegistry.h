#pragma once

#include "PocoDDS/Core/Component.h"

#include <functional>
#include <mutex>
#include <optional>
#include <unordered_map>
#include <vector>

namespace PocoDDS::Core
{
class ComponentRegistry
{
  public:
    using Observer = std::function<void(const Component&)>;

    void upsert(Component component);
    bool remove(const std::string& id);
    std::optional<Component> find(const std::string& id) const;
    std::vector<Component> snapshot() const;
    void observe(Observer observer);

  private:
    mutable std::mutex _mutex;
    std::unordered_map<std::string, Component> _components;
    std::vector<Observer> _observers;
};
} // namespace PocoDDS::Core
