#include "PocoDDS/RuntimeCore/Transport.h"

#include <utility>

namespace PocoDDS::RuntimeCore
{

Subscription::Subscription(std::function<void()> cancel):
    _cancel(std::move(cancel))
{
}

Subscription::~Subscription()
{
    reset();
}

Subscription::Subscription(Subscription&& other) noexcept:
    _cancel(std::move(other._cancel))
{
    other._cancel = {};
}

Subscription& Subscription::operator=(Subscription&& other) noexcept
{
    if (this != &other)
    {
        reset();
        _cancel = std::move(other._cancel);
        other._cancel = {};
    }
    return *this;
}

void Subscription::reset() noexcept
{
    if (!_cancel)
        return;
    auto cancel = std::move(_cancel);
    _cancel = {};
    try
    {
        cancel();
    }
    catch (...)
    {
    }
}

Subscription::operator bool() const noexcept
{
    return static_cast<bool>(_cancel);
}

} // namespace PocoDDS::RuntimeCore
