#include "PocoDDS/Core/ComponentRegistry.h"

namespace PocoDDS::Core
{
void ComponentRegistry::upsert(Component component)
{
    std::vector<Observer> observers;
    Component published;
    {
        std::lock_guard lock(_mutex);
        const auto id = component.id;
        _components[id] = std::move(component);
        published = _components.at(id);
        observers = _observers;
    }
    for (const auto& observer : observers)
        observer(published);
}

bool ComponentRegistry::remove(const std::string& id)
{
    std::lock_guard lock(_mutex);
    return _components.erase(id) != 0;
}

std::optional<Component> ComponentRegistry::find(const std::string& id) const
{
    std::lock_guard lock(_mutex);
    const auto it = _components.find(id);
    return it == _components.end() ? std::nullopt : std::optional<Component>(it->second);
}

std::vector<Component> ComponentRegistry::snapshot() const
{
    std::lock_guard lock(_mutex);
    std::vector<Component> result;
    result.reserve(_components.size());
    for (const auto& [id, component] : _components)
    {
        static_cast<void>(id);
        result.push_back(component);
    }
    return result;
}

void ComponentRegistry::observe(Observer observer)
{
    std::lock_guard lock(_mutex);
    _observers.push_back(std::move(observer));
}
} // namespace PocoDDS::Core
