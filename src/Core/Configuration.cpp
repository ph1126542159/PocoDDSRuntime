#include "PocoDDS/Core/Configuration.h"

#include <stdexcept>

namespace PocoDDS::Core
{
Configuration::Values Configuration::snapshot() const
{
    std::lock_guard lock(_mutex);
    return _values;
}

std::optional<std::string> Configuration::get(const std::string& key) const
{
    std::lock_guard lock(_mutex);
    const auto it = _values.find(key);
    return it == _values.end() ? std::nullopt : std::optional<std::string>(it->second);
}

void Configuration::addValidator(Validator validator)
{
    std::lock_guard lock(_mutex);
    _validators.push_back(std::move(validator));
}

void Configuration::observe(Observer observer)
{
    std::lock_guard lock(_mutex);
    _observers.push_back(std::move(observer));
}

void Configuration::apply(const Values& changes)
{
    Values before;
    Values after;
    std::vector<Observer> observers;
    {
        std::lock_guard lock(_mutex);
        before = _values;
        after = before;
        for (const auto& [key, value] : changes)
        {
            if (key.empty())
                throw std::invalid_argument("configuration key must not be empty");
            after[key] = value;
        }
        for (const auto& validator : _validators)
        {
            if (const auto error = validator(after); error.has_value())
                throw std::invalid_argument(*error);
        }
        _values = after;
        observers = _observers;
    }

    try
    {
        for (const auto& observer : observers)
            observer(before, after);
    }
    catch (...)
    {
        std::lock_guard lock(_mutex);
        _values = before;
        throw;
    }
}
} // namespace PocoDDS::Core
