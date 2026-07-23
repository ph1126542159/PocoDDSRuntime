#include "PocoDDS/Protocols/CAN/SocketCanEndpoint.h"

#include <stdexcept>
#include <utility>

#if defined(__linux__)
#include <cerrno>
#include <cstring>
#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace PocoDDS::Protocols::CAN
{
class SocketCanEndpoint::Impl
{
public:
    explicit Impl(std::string interfaceName) : interfaceName(std::move(interfaceName)) {}

    std::string interfaceName;
    FrameHandler handler;
#if defined(__linux__)
    int descriptor{-1};
#else
    bool open{false};
#endif
};

SocketCanEndpoint::SocketCanEndpoint(std::string interfaceName)
    : _impl(std::make_unique<Impl>(std::move(interfaceName)))
{
}

SocketCanEndpoint::~SocketCanEndpoint()
{
    close();
}

std::string SocketCanEndpoint::name() const
{
    return "socketcan:" + _impl->interfaceName;
}

void SocketCanEndpoint::open()
{
#if defined(__linux__)
    if (_impl->descriptor >= 0)
        return;
    const int descriptor = ::socket(PF_CAN, SOCK_RAW, CAN_RAW);
    if (descriptor < 0)
        throw std::runtime_error("cannot create SocketCAN socket: " +
                                 std::string(std::strerror(errno)));

    ifreq request{};
    if (_impl->interfaceName.size() >= IFNAMSIZ)
    {
        ::close(descriptor);
        throw std::invalid_argument("SocketCAN interface name is too long");
    }
    std::strncpy(request.ifr_name, _impl->interfaceName.c_str(), IFNAMSIZ - 1);
    if (::ioctl(descriptor, SIOCGIFINDEX, &request) < 0)
    {
        const std::string error = std::strerror(errno);
        ::close(descriptor);
        throw std::runtime_error("cannot resolve SocketCAN interface: " + error);
    }

    sockaddr_can address{};
    address.can_family = AF_CAN;
    address.can_ifindex = request.ifr_ifindex;
    if (::bind(descriptor, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0)
    {
        const std::string error = std::strerror(errno);
        ::close(descriptor);
        throw std::runtime_error("cannot bind SocketCAN interface: " + error);
    }
    _impl->descriptor = descriptor;
#else
    throw std::runtime_error("SocketCAN is only available on Linux");
#endif
}

void SocketCanEndpoint::close() noexcept
{
#if defined(__linux__)
    if (_impl->descriptor >= 0)
    {
        ::close(_impl->descriptor);
        _impl->descriptor = -1;
    }
#else
    _impl->open = false;
#endif
}

bool SocketCanEndpoint::isOpen() const noexcept
{
#if defined(__linux__)
    return _impl->descriptor >= 0;
#else
    return _impl->open;
#endif
}

void SocketCanEndpoint::send(const CanFrame& frame)
{
#if defined(__linux__)
    if (!isOpen())
        throw std::logic_error("SocketCAN endpoint is not open");
    if (frame.length > CANFD_MAX_DLEN)
        throw std::out_of_range("CAN frame payload exceeds 64 bytes");

    canfd_frame native{};
    native.can_id = frame.id;
    if (frame.extended)
        native.can_id |= CAN_EFF_FLAG;
    if (frame.remoteRequest)
        native.can_id |= CAN_RTR_FLAG;
    native.len = frame.length;
    std::copy_n(frame.data.begin(), frame.length, native.data);
    const auto written = ::write(_impl->descriptor, &native, sizeof(native));
    if (written != sizeof(native))
        throw std::runtime_error("failed to write SocketCAN frame");
#else
    static_cast<void>(frame);
    throw std::runtime_error("SocketCAN is only available on Linux");
#endif
}

bool SocketCanEndpoint::receive(CanFrame& frame, std::chrono::milliseconds timeout)
{
#if defined(__linux__)
    if (!isOpen())
        throw std::logic_error("SocketCAN endpoint is not open");
    pollfd pollDescriptor{_impl->descriptor, POLLIN, 0};
    const int result = ::poll(&pollDescriptor, 1, static_cast<int>(timeout.count()));
    if (result == 0)
        return false;
    if (result < 0)
        throw std::runtime_error("SocketCAN poll failed");

    canfd_frame native{};
    const auto received = ::read(_impl->descriptor, &native, sizeof(native));
    if (received != CAN_MTU && received != CANFD_MTU)
        throw std::runtime_error("invalid SocketCAN frame length");
    frame.id = native.can_id & (native.can_id & CAN_EFF_FLAG ? CAN_EFF_MASK : CAN_SFF_MASK);
    frame.extended = (native.can_id & CAN_EFF_FLAG) != 0;
    frame.remoteRequest = (native.can_id & CAN_RTR_FLAG) != 0;
    frame.length = native.len;
    std::copy_n(native.data, native.len, frame.data.begin());
    if (_impl->handler)
        _impl->handler(frame);
    return true;
#else
    static_cast<void>(frame);
    static_cast<void>(timeout);
    throw std::runtime_error("SocketCAN is only available on Linux");
#endif
}

void SocketCanEndpoint::setFrameHandler(FrameHandler handler)
{
    _impl->handler = std::move(handler);
}
} // namespace PocoDDS::Protocols::CAN
