#pragma once

#include <functional>
#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace PocoDDS::Core
{
class Configuration
{
  public:
    using Values = std::map<std::string, std::string>;
    using Validator = std::function<std::optional<std::string>(const Values&)>;
    using Observer = std::function<void(const Values& before, const Values& after)>;

    Values snapshot() const;
    std::optional<std::string> get(const std::string& key) const;
    void addValidator(Validator validator);
    void observe(Observer observer);
    void apply(const Values& changes);

  private:
    mutable std::mutex _mutex;
    Values _values;
    std::vector<Validator> _validators;
    std::vector<Observer> _observers;
};
} // namespace PocoDDS::Core
