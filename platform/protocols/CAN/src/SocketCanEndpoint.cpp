#include "PocoDDS/Protocols/CAN/SocketCanEndpoint.h"
#include "PocoDDS/Protocols/ProtocolMetrics.h"

#include <stdexcept>
#include <utility>

#if defined(__linux__)
#include <cerrno>
#include <cstring>
#include <linux/can.h>
#include <linux/can/error.h>
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
    bool fdEnabled{false};
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
    PocoDDS::Protocols::ProtocolMetricTimer metric("socketcan", "open");
    const int descriptor = ::socket(PF_CAN, SOCK_RAW, CAN_RAW);
    if (descriptor < 0)
        throw std::runtime_error("cannot create SocketCAN socket: " +
                                 std::string(std::strerror(errno)));
    const int enableCanFd = 1;
    const bool fdEnabled = ::setsockopt(descriptor, SOL_CAN_RAW, CAN_RAW_FD_FRAMES,
                                       &enableCanFd, sizeof(enableCanFd)) == 0;
    const can_err_mask_t errorMask =
        CAN_ERR_BUSOFF | CAN_ERR_RESTARTED | CAN_ERR_CRTL | CAN_ERR_PROT;
    if (::setsockopt(descriptor, SOL_CAN_RAW, CAN_RAW_ERR_FILTER,
                     &errorMask, sizeof(errorMask)) < 0)
    {
        const std::string error = std::strerror(errno);
        ::close(descriptor);
        throw std::runtime_error("cannot configure SocketCAN error filter: " + error);
    }

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
    _impl->fdEnabled = fdEnabled;
    metric.success();
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
        _impl->fdEnabled = false;
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
    PocoDDS::Protocols::ProtocolMetricTimer metric("socketcan", "send", frame.length);
    if (!isOpen())
        throw std::logic_error("SocketCAN endpoint is not open");
    if (frame.error)
        throw std::invalid_argument("application cannot send a SocketCAN error frame");
    if ((!frame.extended && frame.id > CAN_SFF_MASK) ||
        (frame.extended && frame.id > CAN_EFF_MASK))
        throw std::out_of_range("CAN frame identifier exceeds selected format");
    if (frame.length > CANFD_MAX_DLEN)
        throw std::out_of_range("CAN frame payload exceeds 64 bytes");

    canid_t nativeId = frame.id;
    if (frame.extended) nativeId |= CAN_EFF_FLAG;
    if (frame.remoteRequest) nativeId |= CAN_RTR_FLAG;
    ssize_t written = -1;
    std::size_t expected = 0;
    if (frame.length <= CAN_MAX_DLEN)
    {
        can_frame native{};
        native.can_id = nativeId;
        native.can_dlc = frame.length;
        std::copy_n(frame.data.begin(), frame.length, native.data);
        expected = CAN_MTU;
        written = ::write(_impl->descriptor, &native, expected);
    }
    else
    {
        if (!_impl->fdEnabled)
            throw std::runtime_error("SocketCAN interface does not support CAN FD frames");
        canfd_frame native{};
        native.can_id = nativeId;
        native.len = frame.length;
        std::copy_n(frame.data.begin(), frame.length, native.data);
        expected = CANFD_MTU;
        written = ::write(_impl->descriptor, &native, expected);
    }
    if (written != static_cast<ssize_t>(expected))
        throw std::runtime_error("failed to write SocketCAN frame: " +
                                 std::string(std::strerror(errno)));
    metric.success();
#else
    static_cast<void>(frame);
    throw std::runtime_error("SocketCAN is only available on Linux");
#endif
}

bool SocketCanEndpoint::receive(CanFrame& frame, std::chrono::milliseconds timeout)
{
#if defined(__linux__)
    PocoDDS::Protocols::ProtocolMetricTimer metric("socketcan", "receive");
    if (!isOpen())
        throw std::logic_error("SocketCAN endpoint is not open");
    pollfd pollDescriptor{_impl->descriptor, POLLIN, 0};
    const int result = ::poll(&pollDescriptor, 1, static_cast<int>(timeout.count()));
    if (result == 0)
    {
        metric.timeout();
        return false;
    }
    if (result < 0)
        throw std::runtime_error("SocketCAN poll failed: " +
                                 std::string(std::strerror(errno)));
    if (pollDescriptor.revents & (POLLERR | POLLHUP | POLLNVAL))
        throw std::runtime_error("SocketCAN endpoint reported link or descriptor failure");

    canfd_frame native{};
    const auto received = ::read(_impl->descriptor, &native, sizeof(native));
    if (received != CAN_MTU && received != CANFD_MTU)
        throw std::runtime_error("invalid SocketCAN frame length");
    frame.id = native.can_id & (native.can_id & CAN_EFF_FLAG ? CAN_EFF_MASK : CAN_SFF_MASK);
    frame.error = (native.can_id & CAN_ERR_FLAG) != 0;
    if (frame.error)
        frame.id = native.can_id & CAN_ERR_MASK;
    frame.extended = (native.can_id & CAN_EFF_FLAG) != 0;
    frame.remoteRequest = (native.can_id & CAN_RTR_FLAG) != 0;
    frame.length = native.len;
    std::copy_n(native.data, native.len, frame.data.begin());
    if (_impl->handler)
    {
        try { _impl->handler(frame); } catch (...) {}
    }
    metric.success();
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
